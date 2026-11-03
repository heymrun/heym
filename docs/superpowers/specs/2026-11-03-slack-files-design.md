# Slack files: download and send (Core + Heym Work Flows)

Date: 2026-11-03. Status: approved by Burak in chat ("okey devam et"). Local diff only, no commits.

## Goal

Heym's Slack node can read a Slack message's files (and its text) into Heym Drive, and can
send Drive files to a Slack channel, person or thread. Core workflows use it directly; Heym
Work Flows use it for the legal intake case: a case file dropped in Slack is downloaded,
analyzed by an agent in the file sandbox, reviewed and approved in Work (or in Slack), and the
outcome posted back.

Out of scope (decided): release tour work, a base64 output mode, partial success per file, a
separate node type.

## Core (heymrun)

### Operation `downloadFile` ("Download files")

Field `slackFile` ("Message or files"), placeholder `$slackEvent.event`. A value that is exactly
one `$expression` keeps its type (list/dict), as in the Code node's parameters. Accepted:

| Value | Files | Text, channel, ts, user |
| --- | --- | --- |
| A Slack message or event object (has `files`) | its `files` | from the message |
| The Slack Trigger output (has `event`) | the event's `files` | from the event |
| A message object with `channel` + `ts` but no `files` | fetched message's files | fetched |
| A message permalink `…/archives/C…/p…` (with `?thread_ts=` for replies) | fetched message's files | fetched |
| A file id `F…`, a file object (`slack_file_id` or an `F…` `id`), a file permalink `…/files/U…/F…/…`, or a list of these (also comma/space/newline separated text) | those files | empty |

A message is fetched with `conversations.history` (`latest`=`oldest`=ts, inclusive, limit 1) or,
for a reply, `conversations.replies` on its thread, picking the matching `ts`.

Each file: `files.info` (bot token) → reject external links (`is_external` / `mode == external`),
`hidden_by_limit` / `tombstone`, missing `url_private_download`, and `size` over
`settings.file_max_size_mb`. The download URL must come from Slack's own response and be
`https://files.slack.com/...`; the bot token is sent only there, never to a URL taken from the
node's input. The guarded client does not follow redirects; a redirect or an HTML body for a
non-HTML file means Slack served a sign-in page (missing `files:read`) and fails with that hint.
The body is streamed with a byte cap.

At most 10 files per call. All files are fetched and stored in one DB session; if any file fails,
the node fails, the session rolls back and files already written to disk are removed.

Storage: `file_storage.store_file_sync` with owner `executor.trace_user_id` (as Converter),
`workflow_id` = the run's workflow (so `RunFileScope` covers it and an Agent given the ids turns
file analysis on), `metadata_json = {"slack_file_id": …}`.

Output:

```
{
  "files": [{"id", "slack_file_id", "filename", "mime_type", "size_bytes", "download_url"}],
  "file_ids": ["<drive id>", …],
  "count": n,
  "text": "<message text or empty>", "channel": "…", "ts": "…", "user": "…",
  # first file's fields, when there is one:
  "id", "slack_file_id", "filename", "mime_type", "size_bytes", "download_url"
}
```

A message with no files returns `count: 0` and its text (not an error). An input that names no
message and no file fails: "no Slack message or file found".

### Operation `sendFile` ("Send files")

Fields: `slackChannel` (channel or person, as other operations), `slackThreadTs` (optional),
`slackUploadFile` ("Files", placeholder `$files.file_ids`), `message` (optional comment, Markdown
converted to mrkdwn).

Files resolve through `file_sandbox.manifest.resolve_files(db, actor_id, refs,
scope=executor.file_scope)`: only files uploaded to this workflow, written by its nodes, or handed
in by Chat, or fetched by a Drive node `get` in the same run (`scope.grant_run_files`, added
2026-11-03 after Burak's Drive get → Send files run failed). A typed Drive id outside the run's scope
fails as "not found", so a workflow posts its actor's Drive only through a visible Drive step. Refs: an id, an object with `id`/`file_id`, a list, or
comma/newline separated text (the Code node's normalizer, moved to a shared helper). At most 10.

Per file: `files.getUploadURLExternal` (form POST: `filename`, `length`) → upload URL must be
`https://files.slack.com/...` → POST the bytes there (multipart, no token) → one
`files.completeUploadExternal` (`files`, `channel_id`, optional `thread_ts`, `initial_comment`)
shares all files in one message.

Output: `{"channel", "threadTs", "files": [{"slack_file_id", "title", "id" (Drive id)}], "count"}`.
Slack does not return the message `ts` from this API (documented).

### Slack Trigger

- `slackEventFilesOnly` (bool, "Only messages with files"): an event without `files` does not start
  the run. Applied after the scope check, including scope `all`.
- Loop guard: an event whose `user` is the app's own bot user (`authorizations[].user_id` with
  `is_bot`) is an echo, like bot posts already are. A bot's own upload must not restart a
  files-only flow.

### Everything else

- `SLACK_BOT_SCOPES` (`slackBotSetup.ts`) gains `files:read`, `files:write`. Existing apps must be
  reinstalled; the missing-scope error already names the scope.
- Placement: `slack` gets a predicate, `MAIN_ONLY` for `downloadFile` / `sendFile` (FILE_STORAGE_DIR),
  `ANYWHERE` otherwise. `_agent_placement` docstring lists the Slack download among file producers.
- Panel: "Files" operation group (`Download files`, `Send files`) in `slackOperations.ts`; new field
  keys `slackFile`, `slackUploadFile` (types in `types/workflow.ts`); Slack Trigger panel checkbox.
- DSL prompt: operations, fields, outputs, scopes, and "give `$label.file_ids` to an agent's user
  message to analyze the files".
- Docs: `slack-node.md`, `slack-trigger-node.md`.
- Tests (backend): input shapes, message fetch by permalink, token only to `files.slack.com` and
  never to an input URL (negative), redirect / HTML sign-in page, size cap, rollback removes written
  files, Drive row carries `workflow_id`; `sendFile` scope (out-of-scope id fails, negative), upload
  host check, no token on the upload POST, one complete call; trigger files-only and bot-user echo;
  placement predicate.

## Heym Work Flows

- `FlowTrigger.slack_files: bool` (Slack trigger only). On: the trigger node gets
  `slackEventFilesOnly: true`; a `files` node (`slack` / `downloadFile`, `slackFile:
  "$slackEvent.event"`) follows the trigger, before the read step and the AI step.
- With files on, the AI step is an `agent` node (same fields as `llm`), so file analysis turns on.
  Its user message is `$files.text` plus "Files shared with the message (Heym Drive ids):
  $files.file_ids". `$draft.text` stays the draft.
- New step action `sendFile` ("Send the files"): sends `$files.file_ids` to the step's channel, or the
  message's thread, with an optional message. Only valid with `slack_files`. It never anchors the
  Slack conversation (it returns no `ts`).
- Checks (backend `flow_checks.py` and `lib/flowChecks.ts`, same wording): files need a Slack
  trigger; Send the files needs the trigger's files option.
- Tokens: `$files.count`, `$files.filename`, `$files.text`.
- AI idea "Review the case file" (Slack trigger): turns `slack_files` on; instructions extract
  parties, claims, key dates and deadlines, risks, missing documents, and mark the result as a draft
  for a lawyer.
- The review and approval use the existing `requestApproval` step: it shows in Work's Activity as a
  pending review and in Slack. A lawyer's email or a private channel as its channel keeps the
  analysis out of the intake channel.
- Tests: graph shape with and without files, agent vs llm, sendFile data and anchors, checks.
- Work runs the workflow on Heym, so the vendor pin needs no change for Flows; bump it after the
  Core change lands.
