# Plugin Authoring

Heym plugins are trusted zip packages installed by an operator. A package can
add one or more custom action or trigger nodes without changing the core app.

## Package Layout

A plugin zip must contain `plugin.json` at the package root and the Python entry
file named by `entry` (defaults to `handler.py`).

```text
acme-crm-plugin.zip
|-- plugin.json
|-- handler.py
|-- README.md
|-- icon.svg
`-- assets/
    `-- publisher.svg
```

`README.md` is optional and is served as the plugin's documentation page. Put an
`icon.svg` at the package root for the default node icon, or set a node-specific
`icon` path in `plugin.json`.

## Manifest

Use a multi-node `plugin.json` when one package exposes several nodes:

```json
{
  "id": "acme-crm",
  "name": "Acme CRM",
  "version": "1.0.0",
  "description": "Internal CRM actions and triggers",
  "entry": "handler.py",
  "dependencies": ["requests>=2.32.0"],
  "nodes": [
    {
      "key": "createContact",
      "name": "Create Contact",
      "kind": "action",
      "function": "create_contact",
      "description": "Create a CRM contact",
      "icon": "assets/publisher.svg",
      "dslHint": "Use this when the workflow needs to create an Acme CRM contact.",
      "fields": [
        {
          "key": "email",
          "label": "Email",
          "type": "string",
          "required": true
        },
        {
          "key": "sendWelcome",
          "label": "Send welcome email",
          "type": "boolean",
          "default": false
        }
      ]
    },
    {
      "key": "contactCreated",
      "name": "Contact Created",
      "kind": "trigger",
      "function": "contact_created",
      "description": "Start when a contact event arrives"
    }
  ]
}
```

Legacy single-node manifests are also accepted: omit `nodes` and provide
top-level `kind`, `fields`, `dslHint`, and `docSlug`.

## Manifest Fields

| Field | Notes |
|-------|-------|
| `id` | Lowercase package id using letters, numbers, and hyphens. |
| `name` | Human-readable package name. |
| `version` | Package version used for display and handler caching. |
| `description` | Short description shown in the UI and assistant context. |
| `entry` | Python handler file path inside the zip; defaults to `handler.py`. |
| `dependencies` | Optional pip requirements installed with `uv pip install`. |
| `nodes` | Custom nodes exposed by this package. |

Each node needs a unique `key`, a `name`, and a `kind` of either `action` or
`trigger`. If `function` is omitted, actions call `run` and triggers call
`trigger`.

Supported field types are `string`, `number`, `boolean`, and `select`. Select
fields use an `options` array of `{ "label": "...", "value": "..." }` objects.
Set `required` for required fields and `secret` for masked inputs. The manifest
also accepts `default`, `dynamic`, and `expression` metadata for fields; these are
stored with the manifest, but plugin nodes currently read the saved node config
at runtime rather than auto-populating missing config from defaults.

Non-secret string fields are rendered with the expression input UI. At runtime,
any saved string config value that starts with `$` is resolved before the handler
is called.

## Handler Functions

Action handlers receive workflow inputs, resolved config, and a small context:

```python
def create_contact(inputs, config, ctx):
    email = config["email"]
    return {
        "email": email,
        "nodeId": ctx["node_id"],
    }
```

Trigger handlers receive resolved config and context:

```python
def contact_created(config, ctx):
    return {
        "event": "contact.created",
        "nodeLabel": ctx["node_label"],
    }
```

Return a dictionary to expose named output fields. If a handler returns another
type, Heym wraps it as `{ "value": result }`.

## Installation And Runtime

Plugins are disabled by default. Operators enable them with
`HEYM_PLUGINS_ENABLED=true` and restrict management to
`HEYM_PLUGIN_ADMIN_EMAILS`. Installed plugin files live under
`HEYM_PLUGINS_DIR` and should be mounted persistently in container deployments.

Plugin code is trusted, operator-installed Python that runs in-process with the
backend. It can access the network and installed libraries, so only install
packages you are willing to run with the same trust level as Heym itself.
