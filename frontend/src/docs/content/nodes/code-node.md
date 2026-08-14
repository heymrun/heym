# Code

The **Code** node runs Python you write, with its own `requirements.txt`, and returns JSON. Every execution gets a brand new container that is destroyed when the run finishes, so one execution can never see or affect another.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.result` (whatever `main` returned), plus `$nodeLabel.logs` and `$nodeLabel.install` |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `label` | string | Node identifier (camelCase) |
| `codeSource` | string | Python source. Must define `main(params)` and return a JSON-serializable value |
| `codeParameters` | expression | A JSON object wiring workflow data into the code. Expressions are resolved before the code runs |
| `codeRequirements` | string | `requirements.txt` contents, one package per line. Empty skips installation |
| `codeAllowNetwork` | boolean | Whether the code itself may reach the network (default `false`) |

## The `main` function

Your code must define a top-level `main` that takes one argument:

```python
def main(params):
    name = params.name
    return {"message": f"Hello, {name}!", "length": len(name)}
```

Module-level statements do run, but only what `main` returns becomes the node's output.

The editor shows line numbers, and the expand button beside **Format** opens a larger one that closes with `Esc` — edits apply as you type, so there is nothing to save. The **Format** button reformats your code with Ruff, preserving comments. It also repairs the indentation damage that pasting usually causes: a uniformly indented block, tabs mixed with spaces, and a line sitting a space or two off its block are all fixed rather than rejected. A genuine syntax error is reported with its line and column instead. Formatting runs in the same isolated container the node runs in — no network, no backend environment — so it needs Docker just like execution does.

## Reading parameters

`params` supports dot notation, including through nested objects and lists:

```python
def main(params):
    city = params.user.address.city
    first_order = params.orders[0].id
    return {"city": city, "first_order": first_order}
```

- `params["my key"]` reads keys that are not valid Python identifiers
- `params.get("maybe")` returns `None` instead of raising when a key is absent
- `params.to_dict()` returns the plain dictionary
- Reading a key that was never provided raises an error naming the key and listing what is available

## Output

```json
{
  "result": { "message": "Hello, Heym!", "length": 4 },
  "logs": "",
  "install": { "ok": true, "tool": "none", "log": "" }
}
```

- `result` — the return value of `main`. Downstream nodes read `$nodeLabel.result.message`
- `logs` — everything the code sent to `print`, captured separately so it never corrupts the result
- `install` — which tool installed the dependencies (`uv`, `pip`, or `none`) and its output

## Dependencies

List packages in `requirements.txt` exactly as you would locally:

```
requests==2.32.3
feedparser
```

Packages are installed with `uv` into a throwaway directory before the code runs; if `uv` cannot handle a package, Heym retries with `pip`. Nothing is cached between runs, so heavy dependencies add several seconds to every execution. Leaving `requirements.txt` empty skips the install step entirely and is noticeably faster.

Packages that ship no wheel and need a C compiler will fail to install. The reason appears in `install.log`.

## Network

| Phase | Network |
|-------|---------|
| Installing dependencies | Always on — pip and uv have to reach PyPI |
| Running your code | Off by default. `codeAllowNetwork` turns it on |

With `codeAllowNetwork` off, an outbound call such as `requests.get(...)` fails with a connection error. That is the intended default: most Code nodes transform data that another node already fetched. Prefer fetching with an **HTTP** node and passing the body in through `codeParameters`.

## Sandbox and limits

Your code runs as a non-root user in a container with all Linux capabilities dropped, `no-new-privileges` set, and a read-only root filesystem. It receives no Docker socket and none of the backend's secrets or environment.

| Limit | Value |
|-------|-------|
| Memory | 512 MB |
| CPUs | 1 |
| Processes | 256 |
| Dependency install timeout | 120 seconds |
| Execution timeout | 60 seconds |

These are fixed properties of the sandbox, not configuration.

> **Docker is required.** Unlike Agent Python tools and skills, the Code node has no local fallback mode and no environment variable to relax it. Without a reachable Docker daemon the node fails with a clear error rather than running your code in the backend process. On native `./run.sh` development, start Docker before using this node. See [Security → Code node sandbox](../reference/security.md#code-node-sandbox).

## Use another node when one fits

| You want to | Use |
|-------------|-----|
| Parse or build CSV, TSV, XML, or OCR a file | [Converter](converter-node.md) |
| Call an HTTP API | [HTTP](http-node.md) |
| Map or rename fields | [Set](set-node.md) |
| Run another workflow | [Execute](execute-node.md) |

Reach for **Code** when the logic genuinely does not fit those — custom maths, bespoke parsing, or an algorithm.

## Example

Score rows produced by an upstream node:

```python
def main(params):
    rows = params.rows
    total = sum(r.amount * r.weight for r in rows)
    return {"total": round(total, 2), "count": len(rows)}
```

With `codeParameters` set to `{ "rows": "$fetchRows.result" }`, downstream nodes read `$scoreRows.result.total`.
