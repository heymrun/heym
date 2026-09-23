# Chat credential selection and creation design

Date: 2026-09-23
Status: approved, not yet implemented

## Summary

When a workflow the assistant is about to build needs a credential, the assistant asks
which one to use. If the user has credentials of a fitting type, the question lists them
plus an option to create a new one. If not, it asks whether to create one. Every question
also lets the user continue without a credential.

Picking "create" opens the existing credential dialog inside the conversation, preset to
the type and a suggested name. The dialog posts to `POST /api/credentials` exactly as it
does on the Credentials tab, so the model never sees a value. Once the credential is
saved, the card shows its name and the create button turns off; the user presses
**Submit answers**, the model says it added the credential and carries on, and the new
credential is wired into the node's `credentialId`, or into an `http` node's header for
an operation no node covers.

The same card also serves requests that are only about credentials: "create a GitHub
credential" opens an empty form, and "update my sheet credential" opens the form on that
existing credential (an `edit` option carrying its id), with its secrets masked.

This works on the canvas AI builder, the Chat tab (including its `create_workflow` and
`edit_workflow` tools) and Docs chat. The `heym_chat` MCP tool never lists, picks or
creates credentials: it builds without them and tells the user which nodes still need
one in the UI.

### Example: "list my GitHub repositories"

1. The GitHub node's `listUserRepositories` operation needs a `github` credential.
2. With no GitHub credential the assistant asks "You have no GitHub credential. Create
   one?" with `Create GitHub credential` and `Continue without a credential`. With a
   `github-work` credential it asks "Which GitHub credential should I use?" with
   `github-work`, `Create a new credential` and `Continue without a credential`.
3. The user picks create, clicks **Create…**, and the dialog opens with type `github`
   and name `github-personal`. The user pastes a token and saves.
4. The card shows "Created github-personal" and the user presses **Submit answers**, which
   sends `[Plan answers] github: Created credential "github-personal" (github)`.
5. The next turn's prompt lists `github-personal` with its id. The model replies that it
   added the credential and builds the workflow with `credentialId` set to that id.

### Example: an operation the node lacks

"Add a tab to my Google Sheet" needs `addSheet`, which the Google Sheets node does not
have (`readRange`, `appendRows`, `updateRange`, `getSheetInfo`). The assistant asks for a
`google_sheets` credential the same way and sends the `batchUpdate` request through an
`http` node with `Authorization: Bearer $credentials["<name>"]`. Creating a
`google_sheets` credential runs its OAuth flow inside the dialog.

## Surfaces

| Surface | Picks a credential | Offers to create one |
|---|---|---|
| Canvas AI builder (`POST /api/ai/workflow-assistant`) | yes, clarify card | yes |
| Chat tab, turns typed in the UI (`/api/chats`) | yes, clarify card | yes |
| Chat tab `create_workflow` / `edit_workflow` tools | yes: applies the choice the chat collected, and refuses to save a credential-bearing node nobody decided on | yes, through the chat's card |
| Docs chat (`POST /api/ai/dashboard-chat`) | yes, clarify card | yes |
| `heym_chat` MCP tool turns | no | no |

## Decisions and rejected alternatives

- **Reuse `CredentialDialog`, not an inline form.** The dialog already renders all 36
  credential types, including the OAuth ones (Google Sheets, Google Drive, BigQuery,
  Linear, Notion) and Codex sign-in. An inline form driven by a new field schema would
  keep field definitions in two places that drift apart, and would still need the
  dialog for OAuth. Extracting a shared fields component from the 3,983-line dialog was
  judged too large and risky for this change.
- **Extend `heym-clarify` with a `create` option, not a new block or a tool.** One
  question, one round trip, and the canvas builder and both chats share it. A separate
  `heym-credential` block costs an extra LLM turn and a second parser. A
  `request_credential` chat tool would pause the turn in a way the canvas builder cannot
  copy, because the canvas builder has no tools.
- **Always ask**, even when exactly one credential fits. This keeps the rule from the
  HTTP credentials work.
- **MCP cannot act with credentials.** Selection and creation happen in the UI only.
- **The model sees names, types and ids, never values.** A credential id is not a
  secret: it is already in every workflow JSON and on the canvas.

## Non-goals

- Editing or deleting credentials from chat.
- Shared or team credentials in the catalog. Owned credentials only, as in today's HTTP
  catalog and sanitize code.
- An inline form or a new credential field schema.
- Basic-auth HTTP credentials (Jira), and Linear in the HTTP list: Linear API keys and
  Linear OAuth tokens use different header shapes.
- Any change to how `$credentials` resolves at run time beyond the header keys listed
  below.

## Backend

### Credential catalog

`app/services/http_credential_catalog.py` becomes `app/services/credential_catalog.py`.
Its only importers are `app/api/ai_assistant.py` and `tests/test_http_credential_catalog.py`.
It keeps the HTTP header rules and adds the following.

**`NODE_CREDENTIAL_FIELDS: dict[str, tuple[CredentialField, ...]]`.** For each node type
with a credential field: the field name, the credential types it accepts, and whether
it is required. It mirrors the per-node `credentialsApi.listByType` calls in
`usePropertiesPanelController.ts` and the fields the handlers read.

| Node type | Field | Accepted types |
|---|---|---|
| `bigquery` | `credentialId` | `bigquery` |
| `clickhouse` | `credentialId` | `clickhouse` |
| `codex` | `credentialId`, `githubCredentialId` | `codex`, `github` |
| `crawler` | `credentialId` | `flaresolverr` |
| `decision` | `credentialId` | `decision` |
| `discord` | `credentialId` | `discord` |
| `discordTrigger` | `credentialId` | `discord_trigger` |
| `github` | `credentialId` | `github` |
| `googleDrive` | `credentialId` | `google_drive` |
| `googleSheets` | `credentialId` | `google_sheets` |
| `grist` | `credentialId` | `grist` |
| `imapTrigger` | `credentialId` | `imap` |
| `jira` | `credentialId` | `jira` |
| `linear` | `credentialId` | `linear` |
| `notion` | `credentialId` | `notion` |
| `opencodeGo` | `credentialId`, `githubCredentialId` | `opencode`, `github` |
| `rabbitmq` | `credentialId` | `rabbitmq` |
| `rag` | `rerankerCredentialId` (optional) | `cohere` |
| `redis` | `credentialId` | `redis` |
| `s3` | `credentialId` | `s3` |
| `sendEmail` | `credentialId` | `smtp` |
| `sentry` | `credentialId` | `sentry` |
| `slack` | `credentialId` | `slack` |
| `slackTrigger` | `credentialId` | `slack_trigger` |
| `supabase` | `credentialId` | `supabase` |
| `telegram` | `credentialId` | `telegram` |
| `telegramTrigger` | `credentialId` | `telegram` |

`llm` and `agent` (`credentialId`, `fallbackCredentialId`, `guardrailCredentialId`) and
Playwright `aiStep` steps stay out of the map. The existing sanitize code keeps filling
them from the model credential selected for the chat or the builder. Because the catalog
now lists LLM credentials with their ids, the prompt tells the model to leave the
credential of `llm` and `agent` nodes as a placeholder unless the user asks for a
specific model credential, which is today's behavior.

**`CREDENTIAL_TYPE_PURPOSE: dict[CredentialType, str]`.** One line per type saying what
it holds and what uses it, for example `github: "GitHub personal access token; GitHub,
Codex and OpenCode Go nodes; GitHub REST API over http"`. The model picks the type for a
create option from this list and the node map, so every type is recognized without
per-type prompt code.

**HTTP header keys** gain `github`, `notion` and `sentry`, all with `Authorization`. The
existing "every other type is a raw key" rule sends them as `Bearer <token>`, and
`credential_context_value` already resolves all three to a token. This lets an operation
a node lacks go through `http` with that service's own credential.

**`load_credential_catalog(db, user_id) -> list[CatalogCredential]`** selects `id`,
`name` and `type` of the user's owned credentials. It never selects `encrypted_config`.

### Prompt modes

```python
class CredentialPromptMode(str, Enum):
    ASK_AND_CREATE = "ask_and_create"  # canvas builder, Chat tab UI turns, Docs chat
    APPLY_CHOICES = "apply_choices"    # the builder inside create_workflow / edit_workflow
    OFF = "off"                        # heym_chat MCP turns
```

`build_credentials_prompt(db, user_id, mode)` replaces
`build_http_credentials_prompt(db, user_id, interactive=...)`.

In `OFF` mode the MCP turn's outer chat prompt gets nothing. The builder inside
`create_workflow` / `edit_workflow` gets a short block that names no credentials:
"You cannot use credentials in this step. Build new `http` requests without
authentication, leave credential fields on new nodes empty, and keep every existing
`$credentials` reference and credential id unchanged." It carries over the two
`_NO_ASK_RULES` instructions that stop an MCP edit today from copying a credential into
an `http` node: build without authentication when no credential is named, and keep
existing references. Dropping the block entirely would lose both. The one intended
change is that an MCP caller who names a credential in the request no longer gets it
wired in; that now happens in the UI.

The prompt section lists every owned credential with its name, type and id. HTTP-capable
credentials also get their `$credentials` reference and header line. The section then
lists the node map (node type, field, accepted types) and the type purposes.

### ASK_AND_CREATE rules

0. The assistant can open the credential form. A plain request to create, add or connect a
   credential gets a card with a create option and a cancel option, never directions to
   the Credentials tab. A request to update, edit, rename, rotate, reconnect or
   re-authorize a credential gets a card with an `edit` option
   (`{"label": "...", "edit": {"id": "<credential id>"}}`) for each listed credential that
   matches; the answer comes back as `Updated credential "<name>" (<type>)`.
1. Before building a node with a required field in `NODE_CREDENTIAL_FIELDS`, or an
   `http` call that needs authentication, ask one `single` `heym-clarify` question per
   service. Prefer a dedicated node and use `http` only for operations no node covers;
   this rule is unchanged.
2. When the user owns credentials of a fitting type, offer each of them, then a create
   option, then a "continue without a credential" option. For `http`, existing
   credentials keep today's `{label, prefill: <header key>}` shape with
   `prefillLabel: "Header"`.
3. When the user owns none, ask whether to create one. The options are the create
   option and "continue without a credential".
4. The create option is
   `{"label": "<text in the user's language>", "create": {"type": "<credential type>", "name": "<suggested name>"}}`.
   The type is the node field's accepted type. For `http` it is the service's own
   HTTP-capable type (for example `google_sheets`); if the service has none, it is
   `bearer` or `header`, whichever matches the API's documented auth. The suggested
   name must not collide with an existing credential name, because names are unique per
   owner (`uq_credential_name`).
5. Answers come back as `<name>`, `<name> (Header: "<key>")`,
   `Created credential "<name>" (<type>)`, or the no-credential label. Because the prompt
   is rebuilt for every request, a created credential appears in the catalog with its id
   on the next turn. Set the node's credential field to that id. For `http`, use the
   catalog's suggested header key without asking again.
6. Do not ask again for a service already answered in this conversation. Do not ask for
   a node being edited that already has a credential.
7. With no credential, leave the field empty or build the request without
   authentication, and tell the user where to add the credential later.

`CLARIFY_PROTOCOL_PROMPT` documents two additions: the `create` option shape, and a
question-level `optional: true` for questions the workflow can be built without. A
skipped optional question comes back as `(skipped)`. Credential questions are never
optional, because "continue without a credential" is already an explicit answer. The
constant stays outside `WORKFLOW_DSL_SYSTEM_PROMPT`, so heymweb `/convert` stays free of
clarification (`test_synced_dsl_prompt_stays_clean`).

### Chat workflow CRUD

`create_workflow` and `edit_workflow` get an optional `credential_choices` argument:

```json
[
  {"credential_type": "github", "credential_name": "github-personal"},
  {"credential_type": "google_sheets", "credential_name": "sheet", "header_key": "Authorization"},
  {"credential_type": "slack", "credential_name": ""}
]
```

An empty `credential_name` means the user chose to continue without a credential. The
schema uses plain strings rather than `null`, because some providers reject union types
in tool schemas.

The choices are appended to the builder's user message as explicit instructions, and
the builder runs with the `APPLY_CHOICES` catalog. After generation, one deterministic
pass replaces the credential handling in `_sanitize_generated_workflow_nodes`. It is
driven by `NODE_CREDENTIAL_FIELDS` instead of the 16-type
`_INTEGRATION_CREDENTIAL_NODE_TYPES` set, which today never checks `github`, `jira`,
`linear`, `notion`, `sentry`, `clickhouse`, `s3`, `codex`, `opencodeGo` or `decision`.

0. On a node that already existed, a value the builder left unchanged is kept as it is,
   even a shared credential: it was the user's own earlier choice. A value the builder
   changed into something unusable reverts to the old one.
1. A field holding the exact name of an owned credential of an accepted type is
   rewritten to that credential's id.
2. A field holding an id that is not owned, or whose type the field does not accept, is
   cleared. Placeholders are cleared by the same rule.
3. An empty required field is filled from `credential_choices` when exactly one choice
   names an owned credential of an accepted type.
4. **Safety net.** A node is new in this call when the old workflow has no node with the
   same id, and none with the same label and type. If a new node still has an empty
   required field and no choice covers any of the field's accepted types, the workflow
   is not saved. The tool returns:

   ```json
   {
     "status": "requires_credentials",
     "needs": [
       {"node": "fetchRepos", "node_type": "github", "field": "credentialId",
        "credential_types": ["github"], "existing": ["github-work"]}
     ],
     "instructions": "Ask one heym-clarify question per service (existing credentials, create, continue without), then call this tool again with credential_choices."
   }
   ```

   The chat shows the card and calls the tool again. On edits, nodes that already
   existed are never re-asked, so a credential left empty on purpose stays a decision.

In `OFF` mode, `credential_choices` is ignored, the safety net is off, and credential
fields on new nodes are cleared. Existing nodes keep theirs. The saved workflow's result
carries `credentials_to_assign_in_ui: [{node, node_type, credential_types}]`, so the MCP
reply can tell the user what to set in the UI.

### Wiring the surfaces

- **Chat tab.** `_assemble_system_prompt_parts` appends the credentials block for
  `ASK_AND_CREATE` turns. `SystemPromptParts` gets a `credentials_block` field. The parts
  only feed the context breakdown and are never used to rebuild the prompt, so the block
  is counted under `system` there.
- **The mode is per turn, not per conversation.** `ChatTurn.credential_mode` is
  `ASK_AND_CREATE` for turns from `send_message` and the queue, and `OFF` for
  `run_mcp_chat_turn`. A user who opens an MCP-started conversation in the Chat tab and
  types gets the full capability for that turn.
- **Tool handlers.** `stream_dashboard_chat(..., credential_mode=...)` passes the mode to
  `create_and_run_generated_workflow_tool` and `edit_and_run_generated_workflow_tool`.
- **Docs chat** keeps the catalog #575 added and moves to `ASK_AND_CREATE`.
- **Canvas builder** uses `ASK_AND_CREATE`.
- **No new endpoint.** Creation uses `POST /api/credentials`, so its validation and the
  router's `audit()` call apply unchanged.

## Frontend

### Clarify types and parser

- `ClarifyOption.create?: { type: CredentialType; name: string }` and
  `ClarifyOption.edit?: { id: string }`, on single-choice questions only. `edit` needs a
  UUID; a malformed id falls back to the plain label.
- `parseClarify` accepts `create` only when `type` is a key of `CREDENTIAL_TYPE_LABELS`
  (`types/credential.ts`) and `name` is a non-empty string of at most 100 characters.
  Otherwise the option falls back to its plain label.
- `serializeAnswers` writes `Created credential "<saved name>" (<type>)`, or
  `Updated credential "<name>" (<type>)` for an `edit` option. It uses the name the dialog
  saved, which may differ from the suggestion. The backend prompt describes
  the same format, as it does for prefill answers today.
- `ClarifyQuestion.optional?: boolean`, validated as a boolean like `allowOther`. An
  unanswered optional question serializes as `- <question> → (skipped)`.

### `CredentialFormButton.vue` (new, `components/Credentials/`)

A button that opens `CredentialDialog` with `completeOnConnect`, either with `presetType`
and `presetName` for a new credential or with the credential loaded by id for an edit, and
emits `saved({ id, name, type })`. After saving, the button stays visible but disabled and
the credential's name shows next to it in green. Field values never leave the dialog.

### ClarifyCard

- A selected option with `create` or `edit` shows `CredentialFormButton` where a prefill
  input would be. The question counts as unanswered until the credential is saved.
- On `saved`, the card sets the answer and emits `credential-saved` to its host. It does
  not submit itself; the user presses **Submit answers**.
- Closing the dialog without saving leaves the card waiting. The user can pick another
  option.
- Optional questions say so inside their input as the placeholder: "Optional" on a
  `text` question (instead of "Your answer") and "Other… (optional)" on a choice
  question with `allowOther`. `canSubmit` no longer waits for optional questions; today
  it requires an answer to every question.

### CredentialDialog

- **`presetName?: string`** fills the name for a new credential. `presetType` already
  sets the initial type, and the type select stays editable.
- **`completeOnConnect?: boolean`**: when an OAuth connection succeeds, emit `saved` and
  `close` right away. The Credentials tab keeps today's Connected, then Done behavior.
- **`useOAuthPopup`** (new composable beside the dialog) replaces the popup code copied
  across the five popup flows: Google Sheets, Google Drive, BigQuery, Linear and Notion.
  1. It tries `window.open(authUrl, name, features)`, as today.
  2. It always shows "Popup didn't open? Open the authorization page ↗" under Connect.
     Clicking the link calls `window.open` again from the user's gesture, so popup
     blockers allow it and `window.opener` survives for the callback's `postMessage`. A
     blocked popup is no longer an error.
  3. While waiting, it polls `credentialsApi.get(id)` every 2 seconds and treats
     `masked_value === "connected"` as success. The flow therefore completes even when
     the page was opened without an opener, for example with a middle-click or a copied
     link. Polling stops on success, when the dialog closes, or after 10 minutes.
  4. Once OAuth succeeds for a new credential, the Connect button is disabled and reads
     "Connected". Today it turns into an enabled "Reconnect" that calls `create` again and
     fails with "Credential with this name already exists". Editing an existing
     credential keeps today's enabled Reconnect, because that path already updates.
  5. After a failed or cancelled attempt, Connect and the link stay available, and the
     retry updates the credential the first attempt created instead of creating another.
- **Codex ChatGPT sign-in**, the paste-the-redirect flow, also shows its `authorize_url`
  as a link.

### Surfaces

- **Chat tab** (`ChatConversation.vue`) already renders `ClarifyCard`; nothing else
  changes there.
- **Canvas** (`DebugPanel.vue`) reloads `allCredentialsForSanitize` on
  `credential-saved`. Without the reload, the sanitize step clears the new id because
  the list was loaded at mount. The sanitize step also drops its hard-coded 17-type set:
  every `credentialId` and `*CredentialId` field on non-LLM nodes is kept only if it is an
  owned credential or the value the node already had on the canvas, and an exact owned
  credential name is rewritten to its id. These are the same rules as the backend.
- **Docs chat** (`DocsChatDialog.vue`, `useDocsChatDialog.ts`) renders `ClarifyCard` the
  way the Chat tab does: it strips the block from the markdown, shows the card, and sends
  the answers as a `[Plan answers]` message. Today a `heym-clarify` block, such as the
  #575 credential question or board selection, renders there as a raw JSON code block.

All UI strings are in English. The model writes question and option labels in the
user's language.

## Security

- The model receives credential names, types, ids, `$credentials` references and header
  lines, and never values. `load_credential_catalog` does not select `encrypted_config`.
- Values go from the dialog straight to `POST /api/credentials`. The conversation stores
  only the answer text, which holds a name and a type.
- MCP turns never get the catalog, never assign credentials to new nodes, and cannot
  create credentials.
- Existing protections do not change: owned-only credentials, `mask_sensitive_output`
  on node outputs, and the HTTP node's SSRF guard.

## Error handling

- **Save fails** (validation or a duplicate name): the dialog shows the error as today,
  and the card keeps waiting.
- **OAuth fails or is cancelled:** the dialog shows the error. Connect and the link can
  be retried, and a retry reuses the credential created in this session.
- **OAuth succeeds:** Connect is disabled, so the new credential cannot be created twice.
- **The model proposes an unknown type:** the option falls back to a plain label.
- **`requires_credentials`** tells the chat what to ask, and to call the tool again with
  `credential_choices`.

## Known limitations

- An abandoned OAuth flow leaves a credential without tokens, and the catalog lists it
  like any other, as the Credentials tab does today. The catalog does not read
  `encrypted_config`, so it cannot tell the two apart.
- When two nodes of the same type need different credentials, step 3 of the
  deterministic pass fills empty fields only from a single choice. The builder's own id
  assignment decides the rest.
- The canvas builder has no safety net. The frontend applies its JSON directly, so the
  canvas relies on the prompt rules alone. A node the model forgot to ask about keeps an
  empty credential field, and the node shows that on the canvas.

## Testing

Backend (pytest, `unittest` style, `AsyncMock` for the database):

- `test_credential_catalog.py`, replacing `test_http_credential_catalog.py`:
  - every `CredentialType` has a purpose, and a missing one fails the build, like
    `test_cluster_node_placement.py`;
  - every `NODE_CREDENTIAL_FIELDS` key is registered in `node_execution/registry.py`, and
    every accepted type is a `CredentialType`;
  - prompt output per mode: `OFF` gives the MCP outer prompt nothing and gives the
    builder the no-credentials block (no credential names, build `http` without
    authentication, keep existing references and ids); `APPLY_CHOICES` has no ask rules;
    `ASK_AND_CREATE` documents the create option;
  - header lines for `github`, `notion` and `sentry`.
- `test_advisory_credential_catalog_no_values.py`: with credentials holding known secret
  values, the prompt contains none of them in any mode, and the catalog query does not
  select `encrypted_config`.
- Chat CRUD:
  - names are rewritten to ids;
  - unowned and wrong-type ids are cleared;
  - empty fields are filled from choices;
  - the safety net returns `requires_credentials` and does not add the workflow;
  - an empty-name choice saves with the field empty;
  - edits do not re-ask for pre-existing nodes, matched by id and then by label and type;
  - `OFF` saves without the safety net and returns `credentials_to_assign_in_ui`.
- Chat tab: the catalog is in the system prompt for UI turns and absent for MCP turns,
  and `credential_mode` reaches the tool handlers.
- `test_clarify_protocol_prompt.py` is extended for the create option, `optional` and
  `(skipped)`. `test_synced_dsl_prompt_stays_clean` keeps passing.

Frontend: the existing `parseClarify.test.ts` is extended with create-option validation
and serialization, `optional` validation, and `(skipped)` serialization. No new UI or
E2E tests, per project preference. `bun run lint` and
`bun run typecheck` must pass, and the release-tour registry test in
`releaseTourMapper.test.ts` stays green.

Manual smoke:

- "List my GitHub repositories" in Chat, on the canvas and in Docs chat, with and
  without a GitHub credential.
- "Add a tab to my Google Sheet" with no Sheets credential: OAuth through the popup, then
  with the popup blocked through the link, then with the link opened in a new tab, which
  exercises the polling path.
- `heym_chat` over MCP: no credential question, and the reply lists the nodes to set up
  in the UI.

Run `./check.sh`, with `HEYM_OTEL_ENABLED=false` if the local `.env` enables tracing.

## Documentation and release tour

- Docs under `frontend/src/docs/content/`:
  - `reference/ai-assistant.md`, `tabs/chat-tab.md` and `reference/chat-with-heym.md`
    describe picking and creating credentials;
  - `reference/credentials.md` and `tabs/credentials-tab.md` cover creating from chat and
    the OAuth link;
  - `tabs/mcp-tab.md` states that `heym_chat` does not act on credentials.
- Release tour: a new `2026.15` release in `releaseRegistry.ts` with `tourEnabled: false`
  until the release commit. It has one section, for example `chat-credentials`, listed in
  `sectionOrder`, and an animated mock visual under
  `features/release-tour/components/visuals/` registered in `tourVisuals.ts`. The visual
  shows the card, the dialog, and the "created, continuing" reply.
  `frontend/e2e/support.ts` derives the seen id from the registry, so it needs no manual
  update.

## Findings this design fixes along the way

- #575 wired the HTTP credential catalog into `/api/ai/dashboard-chat`, which only Docs
  chat calls. The Chat tab (`/api/chats`) never got it.
- Docs chat has never rendered `heym-clarify` blocks.
- The backend and frontend credential sanitize sets skip about ten credential-bearing
  node types.
- A second OAuth Connect in the same dialog session fails on the duplicate name.
