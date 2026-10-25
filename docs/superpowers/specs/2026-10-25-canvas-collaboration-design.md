# Canvas collaboration: presence, live editing, follow mode, voice

Date: 2026-10-25
Status: implemented

## Goal

People who open the same workflow canvas work on it together:

1. **Presence.** Round avatars of everyone on the canvas, top left of the canvas.
2. **Cursors.** Each person's pointer, in their own color, labelled with their name.
3. **Live editing.** An edit (add, delete, move, connect, property change) reaches every
   other open canvas within about 100 ms, without a save in between.
4. **Follow mode.** Clicking someone's avatar mirrors what they look at: viewport, pointer,
   selected node, properties panel, expression dialog, debug panel, the execution they
   inspect, and the run they start. Anyone with at least read access can follow.
5. **Voice.** A mic toggle next to the avatars; everyone on the canvas hears whoever has it on.

Heym Work does not get this feature.

## Constraints

- No new npm or pip packages. Browser WebSocket and WebRTC, FastAPI's WebSocket, and the
  `websockets` package already in `backend/pyproject.toml` cover everything.
- Light on the server. The server relays and stores nothing. A canvas with one person on it
  produces only heartbeats.
- Voice is peer to peer. No SFU (LiveKit, mediasoup, Janus), no TURN server, nothing for the
  operator to install. Two public STUN servers are hard-coded constants.
- No new settings or environment variables.

## Architecture

```
browser A ──ws──▶ worker 3 ──pg_notify('heym_collab')──▶ Postgres
                                                         │ (commit order = one total order)
browser B ◀──ws── worker 7 ◀── per-process LISTEN ◀──────┘
browser A ◀──ws── worker 3 ◀── per-process LISTEN ◀──────┘   (A gets its own ops back as acks)

browser A ◀════ WebRTC audio (P2P, STUN only) ════▶ browser B
```

The release image runs 8 uvicorn workers, so two people on one canvas usually sit on
different processes. Every collab message therefore goes through Postgres `NOTIFY`, the same
pattern as `chat_stream_bus.py`: one LISTEN connection per process, plus one publish
connection per process. Both open lazily on the first collab socket in that process.

Postgres delivers notifications in commit order to every listener, so every browser sees the
same sequence of messages. Live editing relies on that order.

### Room

A room is one workflow id. Dashboard widgets open in the editor too and use the same room
model; access comes from `get_workflow_permission`, which already handles widgets.

## Backend

### Files

| File | Responsibility |
| --- | --- |
| `app/api/collab.py` | `WS /api/workflows/{workflow_id}/collab`: auth, origin, permission, receive loop, periodic permission recheck. |
| `app/services/collab/protocol.py` | Inbound message models (Pydantic), which types each permission may send, size and rate constants. |
| `app/services/collab/bus.py` | Publish (with chunking) and LISTEN (with reassembly) on `heym_collab`; reconnect loop and connection probe as in `chat_stream_bus.py`. |
| `app/services/collab/hub.py` | Process-local registry of open sockets per room; delivers a bus message to the local sockets it addresses. |
| `app/services/workflow_save.py` | `announce_workflow_saved` also publishes a `saved` message to the room. |
| `app/api/workflows.py` | The update endpoint reads the two collab headers and passes them to `announce_workflow_saved`. |
| `app/main.py` | Register the router; stop the bus in the lifespan shutdown. |

### Connection

1. **Origin.** Reject unless `Origin` is in `settings.cors_origins_list`, or its host equals the
   `Host` or `X-Forwarded-Host` header (same-origin deployments). The socket authenticates with
   the `access_token` cookie, so without this check any site could open a socket as the
   signed-in user (cross-site WebSocket hijacking). Close code 4403.
2. **User.** Read `access_token` from the cookies and resolve it with `resolve_token_user_id`.
   Close 4401 when it is missing or invalid.
3. **Permission.** `get_workflow_permission`; close 4403 when there is none. The socket holds
   no database session; auth and rechecks use short-lived sessions.
4. **Room cap.** At most 50 local sockets per room per process; beyond that close 4429.
5. **Welcome.** The server assigns the session id (`sid`, UUID) and sends
   `welcome {sid, userId, name, permission}`. It then publishes `join` for this session.
6. **Recheck.** Every 60 s the permission is read again. None: close 4403. Write demoted to
   read: the stamp changes and further write-only messages are rejected.
7. **Close.** On disconnect the server publishes `leave {sid}`.

### Identity stamping

Every relayed message carries `from: {sid, userId, name, permission}` added by the server.
Clients cannot claim another identity or permission.

### Messages

Client to server (JSON text frames, `t` is the type):

| `t` | Who may send | Delivered to | Purpose |
| --- | --- | --- | --- |
| `presence` | any | room, not the sender | Follow state, mic flag, dirty flag, `joinedAt`. Sent on change (viewport at most 10 Hz), on every `join`, and every 20 s. |
| `cursor` | any | room, not the sender | `{x, y}` in flow coordinates, or `null` when the pointer leaves the canvas. Client sends at most 15 Hz and only while other peers exist. |
| `ops` | write | room, **including** the sender | `{seq, ops: [...]}`. The copy that returns to the sender is its acknowledgement. |
| `sync_req` | any | `to` | Ask a peer for the current draft. |
| `snapshot` | write | `to` | `{nodes, edges, hash, baseUpdatedAt}` answer to `sync_req`. |
| `reload` | write | room, including the sender | Everyone discards the shared draft and loads the saved version. |
| `signal` | any | `to` | WebRTC description or ICE candidate. |

Server to client: `welcome`, `join`, `leave`, `saved`, `resync`, `error`, and every relayed
message with its `from` stamp.

`snapshot` and `reload` are write-only because a read-only user could otherwise inject
content that a writer later saves.

### Limits (module constants)

- Inbound frame: 2 MB maximum; larger frames close the socket with 1009.
- Rate: token bucket of 100 messages per second, burst 200. Excess is dropped; three seconds
  of sustained excess closes with 1008.
- Unknown `t` or a message type the permission does not allow: `error` reply, message dropped.

### Bus and chunking

`NOTIFY` payloads are limited to 8000 bytes. A message that encodes larger (a node with a long
prompt or code, a snapshot) is split into chunks of at most 7000 UTF-8 bytes, split on
character boundaries, and every chunk is sent with `pg_notify` inside one transaction on the
publish connection. Postgres holds a lock from pre-commit until commit while it queues a
transaction's notifications, so the chunks of one message arrive contiguously and in order.
The listener reassembles them by message id and drops a partial message whose remaining
chunks do not arrive.

Chunk format: `"<room>|<msg_id>|<index>/<count>|<chunk>"`. The hub filters by room before
reassembly, so a process ignores rooms it has no sockets for.

A process publishes through one connection guarded by an `asyncio.Lock`, and each socket's
receive loop handles its frames one at a time. A single client's messages therefore keep
their order.

If the publish connection drops, publishes fail fast with an `error` frame and the
connection is reopened. If the LISTEN connection drops, every local socket in a room receives
`resync` once the listener reconnects. The client then treats itself as a late joiner (see
below).

### Save announcements

`_executeSave` in the editor sends two headers with the update request:

- `X-Heym-Collab-Session`: the tab's `sid`.
- `X-Heym-Collab-Hash`: hash of the nodes and edges it sends.

`updateMetadata` (name, description) sends the session header only. After commit,
`announce_workflow_saved` publishes
`saved {updatedAt, sid | null, hash | null, byUserId}` to the room. A save that did not come
from a canvas session has `sid: null`: MCP and Chat build mode, Edit History restore, the
API. The headers are not secrets.

## Frontend

All new code lives in `frontend/src/features/collab/`. None of it is imported by components
Heym Work renders (`frontend/src/ports/presentationalImports.test.ts` stays untouched).

| File | Responsibility |
| --- | --- |
| `types.ts` | Protocol types. |
| `collabClient.ts` | WebSocket lifecycle: connect, reconnect with backoff (1 s up to 30 s), typed send and receive, outgoing queue while disconnected. |
| `liveSync.ts` | Pure logic: canonical node and edge keys, diffing against the last synced state, pending-key tracking, applying remote ops, rebasing the undo history, state hash. |
| `useLiveSync.ts` | Binds `liveSync.ts` to the workflow store. |
| `usePresence.ts` | Peer list, TTL expiry, de-duplication by user, colors. |
| `colors.ts` | Twelve-color palette; color from a hash of the user id. |
| `useFollow.ts` | Publishes this tab's follow state; applies a leader's state while following. |
| `useVoice.ts` | Microphone, peer connections, perfect negotiation, speaking detection. |
| `CollabOverlay.vue` | Avatar stack and mic toggle, top left of the canvas. |
| `CollabCursors.vue` | Remote cursors inside the Vue Flow viewport. |
| `FollowFrame.vue` | Colored frame and "Following A · Esc" label while following. |

The workflow store gains a small surface for this module: `applyRemoteChanges`,
`adoptPeerSave`, a hook for extra save headers, and a way to reset the sync baseline after
`loadWorkflow`. Everything else stays in the feature module.

### Live editing

**Keys.** Every node has two keys, `node:<id>:data` (the node without its position) and
`node:<id>:pos`. Every edge has one, `edge:<id>`. UI-only fields such as `selected` and
`dragging` are excluded from the canonical form.

**Outgoing.** A deep watcher on the store's nodes and edges schedules a diff at most every
80 ms. It compares each key's canonical JSON against the last synced value and emits
`node.put`, `node.pos`, `node.del`, `edge.put`, `edge.del`. The diff does not need to know
which of the store's many mutation sites changed something. While a node is being dragged,
`onNodeDrag` sends `node.pos` at 15 Hz directly, because the store only learns the position on
drag stop.

**Conflicts.** This is the method Figma uses for properties:

- Messages are applied in server order.
- Each op that a client sends marks its key pending with that op's `seq`.
- An incoming op for a key that is pending locally is ignored.
- When the client's own op returns with the latest `seq` for that key, the key stops being
  pending.

Two people changing the same key at once end up with the later one in server order, on both
screens. A person typing never sees their own field jump back. Position and data are separate
keys, so dragging a node never overwrites someone's concurrent property edit.

**Remote apply.** `applyRemoteChanges` mutates nodes and edges, updates the sync baseline so
the change is not sent back, sets `hasUnsavedChanges`, and does not push a local undo entry.

**Undo.** Undo restores whole snapshots, so a remote change must not be undone by someone
else's Ctrl+Z. Every applied remote op is also applied to each snapshot in the undo history
(at most 50). Ctrl+Z then reverts only the user's own changes.

**Late joiner.**

1. The tab loads the saved workflow over REST as today, then opens the socket.
2. It buffers every incoming `ops` message from the moment it is connected.
3. Presence replies to its `join` tell it who is dirty. If any write session is dirty, it sends
   `sync_req` to the dirty write session with the earliest `joinedAt`.
4. When the `snapshot` arrives, it replaces nodes and edges with it, then replays the buffered
   ops in order. Ops are whole values per key, so replaying ones the snapshot already
   contains is harmless.
5. If no reply arrives in 3 s, it asks the next dirty writer. If none answers, it keeps the
   saved version.

After a reconnect, or a `resync` from the server, the client does the same, and also keeps
its own pending keys: the snapshot does not overwrite them, and its queued ops are sent once
the snapshot has been applied.

**Last writer leaves.** Unsaved changes belong to the people who can save them. When the
last write session leaves a dirty room, read-only peers reload the saved version.

**Saving.**

- `saved` from a session in the room is a peer save. Every peer:
  - adopts `updatedAt` as its known revision, so peers never get 409 against each other;
  - clears "Unsaved changes" when its own state hash equals `hash`, and keeps it otherwise;
  - re-reads the workflow's settings over REST (one `GET`), keeping its nodes and edges.
    Owner-only fields keep their masking.
- `saved` with no session, or from an unknown session, is an external save.
  - If the room is clean, every peer reloads silently and keeps its viewport.
  - If the room is dirty, writers get the existing stale-save dialog. "Reload" sends `reload`
    so the whole room loads the saved version together. "Overwrite" force-saves, which every
    peer then receives as a peer save. Read-only peers wait for the writers.
- When two peers save at the same moment, one of them gets 409. If a peer `saved` with the
  conflicting `updated_at` arrives within 1 s, the client adopts it and retries once instead of
  opening the dialog.

**Read-only sessions** receive everything and send no ops. Their canvas is already locked.

### Presence and avatars

- `CollabOverlay.vue` sits top left over the canvas. It shows round `UserAvatar`s with a ring
  in the person's color, at most five, then `+N`. One avatar per user even with several tabs
  open. Hover shows name and permission.
- A peer disappears on `leave`, or 60 s after its last presence.
- Color comes from the user id, so it is the same on every screen: avatar ring, cursor and
  follow frame.

### Cursors

`CollabCursors.vue` renders inside the Vue Flow viewport. Positions are flow coordinates, so a
cursor sits over the same node whatever each person's pan and zoom. It is an arrow with a name
tag, moved with a short CSS transition. It hides after 10 s without movement, and immediately
when `cursor: null` arrives.

### Follow mode

Presence carries the follow state:

```ts
interface FollowState {
  viewport: { x: number; y: number; zoom: number; width: number; height: number };
  selectedNodeId: string | null;
  panel: { open: boolean; tab: string | null };
  expression: { nodeId: string; field: string } | null;
  debugOpen: boolean;
  historyExecutionId: string | null;
  runningExecutionId: string | null;
  ownerDialog: string | null; // "share" | "portal" | "curl" | ... (label only)
}
```

- Clicking someone else's avatar starts following them. Clicking your own avatar does
  nothing.
- **Viewport.** The follower fits the leader's visible flow rectangle (from `viewport`, `width`
  and `height`) into its own canvas, so different screen sizes show the same region.
- **What the follower renders.** Selection, properties panel and tab, expression dialog,
  debug panel and the execution open in History come from the **follower's own data and
  permissions**. A read-only follower sees the panels read-only.
- **Runs.** When `runningExecutionId` appears, the follower calls `observeExecution`, the same
  path the editor already uses for runs started elsewhere.
- **Owner-only dialogs** (Share, Portal, cURL token, credentials) are never mirrored. The frame
  label says "A is in Share settings" instead.
- **Stopping.** Following stops when the follower pans or zooms by hand, presses Esc, clicks
  the leader's avatar again, or the leader leaves.
- `FollowFrame.vue` draws a frame in the leader's color around the canvas with
  "Following A · Esc to stop".

### Voice

- **Mic toggle.** Next to the avatar stack. The first use asks for permission with
  `getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } })`.
  Turning the mic on or off updates `mic` in presence.
- **Topology.** One `RTCPeerConnection` per remote session. It opens when either side turns
  the mic on and stays open until that peer leaves; turning the mic off removes the audio
  track. Audio uses Opus, the browser default. A listener needs no microphone permission.
- **Signalling.** `signal` messages carry the WebRTC data, using the perfect-negotiation
  pattern. The session with the lexicographically smaller `sid` is the polite peer.
- **ICE servers.** Constants: `stun:stun.cloudflare.com:3478` and `stun:stun.l.google.com:19302`.
  No TURN. On an air-gapped install the STUN request times out and peers on the same LAN or VPN
  still connect over local candidates.
- **Failures.**
  - A pair that cannot connect within 10 s shows a small "no audio" mark on that avatar.
  - If the browser blocks autoplay, an "Enable audio" chip appears and one click resumes
    playback.
- **Speaking indicator.** Each browser runs an `AnalyserNode` on the streams it receives and on
  its own, and pulses the matching avatar ring. Nothing about speaking goes over the network.
- **Cleanup.** Leaving the canvas stops the tracks and closes every peer connection.
- **Scale.** A mesh comfortably handles about eight simultaneous speakers; more people can
  listen.

### Mobile

The mobile tree editor uses the same store, so it receives live edits. Avatars, cursors,
follow mode and voice are desktop only.

## Delivery

- **README.** Add scene 21 "REAL-TIME COLLABORATION" to
  `docs/readme-assets/full-feature-showcase.svg`. The loop grows from 100 s to 105 s, so the
  scene keyframes and delays are recomputed for 21 scenes. Mention the feature in the README's
  feature text.
- **Docs.** Use the `heym-documentation` skill to:
  - add `reference/canvas-collaboration.md` and register it in `manifest.ts`;
  - add an entry in `reference/features.md`;
  - add a short mention in `reference/canvas-features.md`;
  - add Esc ("stop following") to `reference/keyboard-shortcuts.md`.
- **Release tour.** Release `2026.21` is already enabled, so start release `2026.22` with
  `tourEnabled: false`. Add the section `canvas-collaboration` and list it in `sectionOrder`.
  Add `CanvasCollaborationTourVisual.vue`, a mock with avatars, two moving cursors, a node
  appearing on both canvases and a speaking ring, and register it in `tourVisuals.ts`. Bump
  the seeded release id in `frontend/e2e/support.ts` only when the release is enabled.
- **Git.** Not committed. The work stays as a local diff.

## Testing

Backend (`backend/tests/test_canvas_collab.py`, unittest with `AsyncMock`):

- Chunking round trip, including multibyte text at chunk boundaries, and rejection of a
  message over the cap.
- Partial chunk sets are dropped without blocking later messages.
- Hub delivery: room filtering, `to` targeting, no self-echo for `cursor` and `presence`, echo
  for `ops`.
- Protocol: read-only `ops`, `snapshot` and `reload` are rejected; unknown types are rejected;
  oversized frames close the socket.
- Endpoint, using the Starlette test client:
  - no cookie gives 4401; a foreign origin gives 4403; no access gives 4403;
  - a read share receives `welcome` with `permission: "read"`;
  - the server stamp overrides any `from` the client sends.
- Recheck: revoked access closes the socket; demotion to read rejects later `ops`.
- `announce_workflow_saved` publishes `saved` with the session and hash from the headers, and
  with `sid: null` when they are absent.

Frontend (Vitest, pure logic only, no component tests):

- `liveSync.ts`:
  - diff output for add, delete, move and data change;
  - UI-only fields are ignored;
  - two simulated clients with interleaved server order converge;
  - a pending key ignores remote ops until its ack arrives;
  - a late joiner's snapshot plus buffered replay gives the same state as the room;
  - undo history rebase.
- `colors.ts`: the same user gets the same color everywhere.

Manual: two browsers (one write, one read share) on `./run.sh`. Check cursors, live edits both
ways, a save by either side, an external save from Chat build, follow mode including a run,
and voice between them.

Gates: `./check.sh`, `bun run lint`, `bun run typecheck`, `bun run test`.

## Out of scope

- Merging two people's text inside one field character by character. The later write wins
  for the whole node data key.
- Comments, chat, video, screen sharing, recording.
- A TURN server or a server-side audio relay.
- Presence outside the editor, such as in the workflow list.
- Per-person mute of other speakers.
