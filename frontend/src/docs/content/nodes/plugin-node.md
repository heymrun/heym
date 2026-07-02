# Plugin Node

The **Plugin** node runs a custom action provided by an installed plugin. Plugins
extend Heym with new node types — actions, third‑party integrations, or anything
expressible as Python — without modifying the core application.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.<keys returned by the plugin>` |

A plugin **package** (one zip) can ship **multiple nodes** — any mix of actions
and triggers. Each node appears in the palette under **Plugins** with its own
name and description. Dragging one onto the canvas creates a Plugin node bound to
that package (`pluginId`) and node (`pluginNodeKey`).

## When to Use

Use a Plugin node when an operator has installed a plugin that performs the action
you need — for example calling a private API, talking to an internal system, or
running bespoke logic written for your deployment.

For trigger‑style plugins that start a workflow, see the
[Plugin Trigger node](./plugin-trigger-node.md).

## Configuration

The node's configuration form is generated from the plugin's manifest. Each field
declared by the plugin (`string`, `number`, `boolean`, or `select`) is rendered
automatically. Fields marked as expression‑capable accept `$` expressions and can
be filled from the expression dialog, just like built‑in nodes.

Secret fields (such as API keys) are masked in the UI and never written to logs.

## How Plugins Run

Plugins are delivered by Heym and installed by an operator, so plugin code is
**trusted** and runs in‑process like a built‑in node, with full network and
library access. A plugin may declare pip `dependencies` that are installed into
the instance at install time.

Installing and removing plugins is restricted to operators whose email is listed
in `HEYM_PLUGIN_ADMIN_EMAILS`, and the whole subsystem is gated by
`HEYM_PLUGINS_ENABLED` (disabled by default). See
[Running & Deployment](../getting-started/running-and-deployment.md) for the
environment variables.

## Custom Icons

A plugin can ship custom SVG logos. Put an `icon.svg` at the package root to set a
default for every node, and/or give a node its own `"icon": "<file>.svg"` in the
manifest. The icon shows on both the palette card and the canvas node; nodes
without an icon fall back to the default puzzle‑piece glyph.

## AI Builder

Installed plugins are surfaced to the AI assistant and chat canvas, so you can ask
Heym to "use the Acme CRM plugin to create a record" and it will generate the
Plugin node with the right `pluginId` and `config`.
