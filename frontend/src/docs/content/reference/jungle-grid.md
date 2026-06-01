# Jungle Grid

Jungle Grid is a managed GPU execution layer for AI workloads and agents. In Heym, use it through the Agent node's MCP support: Heym handles workflow orchestration, approval, observability, and downstream steps while Jungle Grid handles GPU placement, execution, logs, retries, and artifacts.

## When to use it

Use Jungle Grid when a workflow needs GPU-backed inference, training, image generation, or batch execution without manually choosing or managing GPU infrastructure.

The recommended pattern is:

```text
User Request -> AI Agent with Jungle Grid MCP tools -> estimate_job -> Human Approval -> submit_job -> monitor logs/status -> retrieve artifacts -> return response
```

## Create the credential

1. In Jungle Grid, create an API key from the portal's API key settings.
2. In Heym, open **Credentials** and create a **Jungle Grid** credential.
3. Name it `jungle_grid` if you want to use the bundled example workflow unchanged.
4. Paste the API key into the credential dialog. Do not paste it into prompts, node text fields, workflow JSON, screenshots, or docs.

Heym stores the key encrypted and references it at runtime as `$credentials.jungle_grid`.

## Add Jungle Grid MCP to an Agent

1. Add or select an **Agent** node.
2. Configure the agent's LLM credential and model.
3. In **MCP Connections**, click **Jungle Grid**.
4. Select the Jungle Grid credential.
5. Optionally set an API URL override. Leave it blank for `https://api.junglegrid.dev`.
6. Click **Fetch tools** to verify discovery.

The preset config is:

```json
{
  "transport": "stdio",
  "label": "Jungle Grid",
  "command": "npx",
  "args": ["-y", "@jungle-grid/mcp"],
  "env": {
    "JUNGLE_GRID_API_KEY": "$credentials.jungle_grid"
  }
}
```

For alternate environments, add:

```json
{
  "JUNGLE_GRID_API_URL": "https://your-orchestrator.example.com"
}
```

## Available tools

| Tool | Purpose |
| --- | --- |
| `estimate_job` | Estimate cost, GPU tier, route, queue wait, and runtime before starting work. |
| `submit_job` | Submit a GPU workload and return a job ID immediately. |
| `get_job` | Poll current job status and details. |
| `list_jobs` | List recent jobs. |
| `cancel_job` | Cancel a queued or running job. |
| `get_job_logs` | Fetch stdout/stderr from a job. |
| `stream_job_logs` | Stream logs while the job runs. |
| `list_job_artifacts` | List files captured from `/workspace/artifacts`. |
| `get_artifact_download_url` | Create a temporary download URL for an artifact. |

## Agent instructions

Use a system instruction like:

```text
You orchestrate GPU workloads through Jungle Grid MCP. Always call estimate_job first. Summarize estimated cost, likely GPU tier, queue/runtime range, and the exact workload payload. Ask for human approval before submit_job, cancel_job, or any action that spends credits or starts execution. After approval, call submit_job, monitor with stream_job_logs or get_job polling, retrieve logs and artifacts with list_job_artifacts and get_artifact_download_url, then return the final result or artifact URL. Never ask the user to paste API keys into chat.
```

Enable **Human-in-the-Loop** on the Agent node and use this approval summary:

```text
Require approval before submit_job, cancel_job, or any Jungle Grid MCP tool call that starts execution or spends credits. estimate_job, get_job, list_jobs, get_job_logs, stream_job_logs, list_job_artifacts, and get_artifact_download_url may run without approval.
```

## Example workflow

An importable example is available at `docs/examples/jungle-grid-mcp-workflow.json`. Before running it:

1. Create the `jungle_grid` credential.
2. Select an LLM credential and model on the Agent node.
3. Run a request such as:

```text
Estimate a small inference job using python:3.11-slim that writes output.json to /workspace/artifacts. Show me the estimate and ask before submitting.
```

Automated tests and examples must not submit real paid workloads. Manual verification should use `estimate_job` only unless you intentionally approve a real run.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Missing API key | Create a Jungle Grid credential and select it in the preset. Do not type the key directly into MCP env. |
| Tools not discovered | Confirm Node.js 18+ is available, then retry **Fetch tools**. The preset runs `npx -y @jungle-grid/mcp`. |
| `JUNGLE_GRID_API_KEY is required` | The env value did not resolve. Check the credential name and that the workflow owner can access it. |
| Job failed | Use `get_job`, `get_job_logs`, and `stream_job_logs` to inspect status and logs. Return the failure reason through the workflow output. |
| Long-running job | `submit_job` returns quickly. Poll with `get_job` or stream logs instead of blocking on one long tool call. |
| Missing artifacts | Ensure the job writes files under `/workspace/artifacts`, then call `list_job_artifacts` after completion. |
| Alternate API environment | Set `JUNGLE_GRID_API_URL` in the preset's optional API URL field. |

## Security

- Never put `JUNGLE_GRID_API_KEY` in prompts, public workflow values, screenshots, fixtures, logs, or committed files.
- Store the API key only as a Heym Jungle Grid credential.
- Prefer `estimate_job` before any `submit_job`.
- Use Human-in-the-Loop approval for credit-spending or execution-starting tools.
- Do not pass unrelated secrets through Jungle Grid job environment variables, callback metadata, command args, or artifacts.

## Related

- [Agent Node](/docs/nodes/agent-node)
- [Human-in-the-Loop](/docs/reference/human-in-the-loop)
- [Credentials](/docs/reference/credentials)
- [Third-Party Integrations](/docs/reference/integrations)
