# Contextual Showcase

The **Contextual Showcase** is a lightweight in-app guide rail that explains the page you are currently on without pushing you into a full documentation flow immediately.

## What It Does

- Shows a short summary for the current page
- Keeps the first layer concise so you are not overloaded
- Lets you expand a small amount of extra detail only when needed
- Links out to the full docs page for deeper reading

## Where It Appears

In v1, the showcase is available on Heym's authenticated main surfaces:

- Dashboard tabs
- [Evals](../tabs/evals-tab.md)
- [Documentation](../getting-started/introduction.md)
- The workflow editor canvas

Public pages such as login, register, chat portal, and HITL review do not show the showcase.

## Access

### Desktop

- A fixed **Page Guide** trigger appears on the right edge of the screen
- The showcase opens as a right-side drawer
- It stays closed by default
- A one-time teaser helps reveal that the guide exists without forcing it open

### Mobile

- The same content is available from a floating **Page Guide** button
- It opens in a bottom sheet instead of a right rail

## Content Model

Each showcase entry uses a structured definition instead of a fully custom component.

- **Title** – What this page is
- **Summary** – One short explanation
- **Bullets** – A few scannable cues
- **Highlights** – Small cards for key value or usage patterns
- **More Detail** – Collapsed sections for extra context
- **Actions** – Usually one or two links, most often to full documentation

This keeps the system flexible while avoiding long, noisy help panels.

## Context Awareness

The showcase changes with the current surface.

- Dashboard tabs each have their own summary
- The editor points to [Canvas Features](./canvas-features.md)
- The docs page uses a generic docs overview and, when possible, points to the current article you already have open

## Persistence

The showcase stores a small amount of personal UI state in browser storage:

- Whether the panel or sheet was last open
- Which page contexts already showed the teaser
- The last expanded detail section per context

## Why It Exists

The goal is to make Heym easier to learn without adding more heavy UI chrome.

- Short, always-near guidance for orientation
- Clear path to deeper documentation
- Low interruption for experienced users

## Related

- [Workflows Tab](../tabs/workflows-tab.md) – Main dashboard surface
- [Evals Tab](../tabs/evals-tab.md) – Evaluation workflows
- [Canvas Features](./canvas-features.md) – Editor behavior and debugging
- [Quick Drawer](./quick-drawer.md) – The other fixed right-side utility surface
