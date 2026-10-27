# A2A

Heym serves the **Heym Agent** over the Agent2Agent protocol (A2A 1.0, JSON-RPC binding). The Heym Agent is the engine behind the [Chat tab](../tabs/chat-tab.md); MCP clients reach the same agent as the `heym_chat` tool (see [MCP / A2A tab](../tabs/mcp-tab.md)). With A2A on, another agent can send it a task in plain language and get the reply, with the same abilities Chat has.

## Turn it on

1. Open the **MCP / A2A** tab.
2. Turn on the **Heym Agent** on the default server or on a named server, and pick its credential and model.
3. Tick **Enable A2A**. The card shows the **Agent Card** URL and the **JSON-RPC endpoint**.

A2A rides on the Heym Agent: turning the agent off turns A2A off as well.

## Endpoints

| | Default server | Named server |
|---|---|---|
| Agent Card | `{origin}/.well-known/agent-card.json` | `{origin}/api/a2a/servers/{server_id}/agent-card.json` |
| JSON-RPC | `POST {origin}/api/a2a` | `POST {origin}/api/a2a/servers/{server_id}` |

The Agent Card needs no credentials and names no user, server or workflow. It exists only while A2A is on: the domain card while at least one user has A2A on for the default server, a named server's card while that server's A2A is on. Otherwise the address answers 404.

## Authentication

Send the same credentials as for MCP, in headers only:

- `X-MCP-Key: <key>`: the default server's key or the named server's key
- `Authorization: Bearer <token>`: an OAuth token from Heym's OAuth server

Credentials in the URL are refused. The Agent Card declares both schemes, so an A2A client can read them from the card.

## Methods

| Method | What it does |
|---|---|
| `SendMessage` | Starts a task, or continues one waiting for input. Waits for the reply unless `configuration.returnImmediately` is `true`. |
| `SendStreamingMessage` | The same, as a Server-Sent Events stream of the task's progress and its result. |
| `GetTask` | A task's state, reply and history (`historyLength` limits the history). |
| `ListTasks` | Your tasks on this server, newest first, filtered by `contextId` or `status`, with `pageSize` and `pageToken`. |
| `CancelTask` | Stops a task that is still working or waiting. |
| `SubscribeToTask` | Follows a task that is still working. |
| `GetExtendedAgentCard` | The card with the server's name and its assigned workflows as skills. |

Push notifications are not offered: the card says `pushNotifications: false`, and the push methods answer `PushNotificationNotSupportedError`. Requests use A2A 1.0; send `A2A-Version: 1.0`. A2A 0.3 method names such as `message/send` answer `VersionNotSupportedError`.

## Tasks and conversations

Every task is a conversation in the Chat tab, marked with a network icon. The task's `contextId` is that conversation: send a new message with the same `contextId` and no `taskId` to continue it.

| What the agent did | Task state |
|---|---|
| Answered | `TASK_STATE_COMPLETED`, with the reply as text and, when it saved any, the links to workflows and eval suites as data |
| Asked a clarifying question | `TASK_STATE_INPUT_REQUIRED`: answer with the same `taskId` |
| Needs a credential | `TASK_STATE_AUTH_REQUIRED`: the status message holds a link to Heym's credential page. The user opens it in a browser signed in to Heym; the value never passes through the other agent. Then send a message on the same task to continue. |
| Failed | `TASK_STATE_FAILED`, with the reason |
| Was canceled | `TASK_STATE_CANCELED` |

A message to a finished task, or to one still working, is refused with `UnsupportedOperationError`. Messages take `text` and `data` parts, up to 20,000 characters together; file parts are refused, so send files as links.

## Progress

While a task works, the stream sends a status update for every step, in the words the Chat tab shows, for example `Running workflow "Invoice Parser"` or `Testing the workflow · attempt 2/5`. MCP clients get the same steps as `notifications/progress` from `heym_chat`.

## Example

```bash
curl -s https://heym.example.com/.well-known/agent-card.json

curl -s -X POST https://heym.example.com/api/a2a \
  -H "X-MCP-Key: $HEYM_MCP_KEY" \
  -H "A2A-Version: 1.0" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"SendMessage","params":{"message":{"messageId":"m1","role":"ROLE_USER","parts":[{"text":"List my workflows"}]}}}'
```

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "task": {
      "id": "…",
      "contextId": "…",
      "status": { "state": "TASK_STATE_COMPLETED", "timestamp": "2026-10-27T10:30:00.000Z" },
      "artifacts": [
        { "artifactId": "response", "name": "Heym Agent reply", "parts": [{ "text": "You have 12 workflows: …" }] }
      ]
    }
  }
}
```

## Limits

- `CancelTask` stops a running turn at once on the Heym instance running it, as the Chat tab's Stop does. Elsewhere the task is marked canceled and the turn's late result is not recorded.
- No push notifications, no REST or gRPC binding, no signed Agent Cards.

## Related

- [MCP / A2A tab](../tabs/mcp-tab.md): turn the Heym Agent and A2A on
- [Chat tab](../tabs/chat-tab.md): the engine behind the agent
- [Security](./security.md): how keys are stored
