# Plugin Trigger Node

The **Plugin Trigger** node is the trigger‑style counterpart of the
[Plugin node](./plugin-node.md). It is provided by an installed plugin whose
`kind` is `trigger`, and produces the initial data a workflow starts from.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 0 |
| Outputs | 1 |
| Output | `$nodeLabel.<keys returned by the plugin>` |

A trigger plugin can represent any source — a different application, a third‑party
service, or another technology — as long as the plugin's handler returns the data
the workflow should begin with.

## When to Use

Use a Plugin Trigger node when an installed plugin defines a trigger that starts
your workflow. For plugins that perform an action mid‑workflow, use the
[Plugin node](./plugin-node.md) instead.

## Configuration

Like the Plugin node, the configuration form is generated from the plugin's
manifest fields. Non-secret string fields use the expression input, and secret
fields are masked.

## How Plugins Run

Plugin code is trusted (Heym-delivered, operator-installed) and runs in-process.
Installation is restricted to `HEYM_PLUGIN_ADMIN_EMAILS` and the subsystem is
gated by `HEYM_PLUGINS_ENABLED`. See
[Running & Deployment](../getting-started/running-and-deployment.md).

## Author Plugins

To build a trigger plugin package, see
[Plugin Authoring](../reference/plugin-authoring.md) for the zip layout,
manifest fields, handler signatures, icons, dependencies, and runtime trust
model.
