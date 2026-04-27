---
name: heym-documentation
description: Create and update documentation articles for the Heym platform. Use when adding docs pages, writing reference articles from summaries, or when the user provides an outline for a new article.
---

# Heym Documentation

## Quick Start

When creating an article from a summary or outline:

1. **Choose category**: `getting-started`, `nodes`, or `reference`
2. **Pick slug**: kebab-case (e.g. `expression-dsl`, `node-types`)
3. **Add to manifest**: `frontend/src/docs/manifest.ts`
4. **Create markdown**: `frontend/src/docs/content/{category}/{slug}.md`

## File Structure

```
frontend/src/docs/
├── manifest.ts           # DOCS_MANIFEST – add new items here
└── content/
    ├── getting-started/
    │   ├── introduction.md
    │   ├── quick-start.md
    │   └── core-concepts.md
    ├── nodes/
    │   └── agent-node.md
    └── reference/
        ├── node-types.md
        ├── expression-dsl.md
        └── workflow-structure.md
```

## Manifest Update

Add the new item to the correct category in `DOCS_MANIFEST`:

```ts
// frontend/src/docs/manifest.ts
"reference": {
  id: "reference",
  label: "Reference",
  items: [
    // ...existing
    { slug: "your-new-slug", title: "Your New Title" },
  ],
},
```

Order matters: prev/next navigation follows manifest order.

## Article Format

- **H1**: Page title (single `#`)
- **H2/H3**: Section headings
- **Tables**: Use markdown tables for reference (Node Types, API params)
- **Code blocks**: Use ` ``` ` with language when relevant (e.g. `dsl`, `json`)
- **Expressions**: Use backticks for `$input.text`, `$nodeName.field`
- **Lists**: Use `-` for bullets, `1.` for numbered

## Style

- Concise, scannable
- One idea per paragraph
- Code examples for reference pages
- Link to related articles when useful

## After Adding a New Doc

When a new doc is created, **update existing md files** so they link to it:

1. **Scan all** `frontend/src/docs/content/**/*.md` files
2. **Find relevant mentions** – keywords, topic names, or concepts that relate to the new doc
3. **Add hyperlinks** – wrap relevant text in `[text](/docs/{category}/{slug})`
4. **Update Related sections** – add the new doc to the Related list of any doc that references its topic

Example: Adding `nodes/llm-node.md` → search for "LLM", "language model", "userMessage" in existing docs; add links where appropriate; add `[LLM Node](/docs/nodes/llm-node)` to Related in node-types.md, expression-dsl.md, quick-start.md, etc.

## Example: From Summary to Article

**Input (summary):**
> Credentials store API keys. Users add them in Settings. Nodes reference by name.

**Output steps:**
1. Add `{ slug: "credentials", title: "Credentials" }` to `reference` in manifest
2. Create `frontend/src/docs/content/reference/credentials.md`:

```markdown
# Credentials

Credentials store API keys and secrets used by nodes.

## Adding Credentials

Add credentials in **Settings** → Credentials. Each credential has a name used to reference it in nodes.

## Using in Nodes

Reference credentials by name in node configuration (e.g. LLM model API key, HTTP auth).
```
