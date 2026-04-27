# Templates Feature Design

**Date:** 2026-04-18  
**Repos:** heymweb (Next.js) + heymrun (Vue.js)  
**Status:** Approved

---

## Overview

Add a public Templates gallery to heymweb (heym.run/templates) and wire heymrun's internal Templates screen to browse it via an iframe dialog. Users can preview templates with an interactive React Flow canvas, download them as `.json`, or copy JSON to clipboard and paste directly onto the heymrun canvas.

---

## Decisions Made

| Question | Decision |
|---|---|
| Template data source | Static curated JSON in heymweb repo (`src/lib/templates.ts`) |
| Canvas preview on heymweb | React Flow (`@xyflow/react`) — same UX as heymrun's CanvasPreviewModal |
| heymrun iframe target | heymweb `/templates` public page |
| Import actions | Download `.json` + Copy JSON to clipboard |
| Clipboard paste in heymrun | Already supported — no changes needed |
| Page structure | Kategorili gallery + `/templates/[slug]` detail pages |
| Backend changes | None required |

---

## heymweb Changes

### 1. Template Data — `src/lib/templates.ts`

Static array of curated `WorkflowTemplate` objects. Each entry:

```typescript
interface StaticTemplate {
  slug: string;               // URL slug, e.g. "ai-email-triage"
  name: string;
  description: string;        // short (card)
  longDescription: string;    // markdown string, rendered with react-markdown
  tags: string[];             // e.g. ["AI", "Email", "Automation"]
  category: TemplateCategory; // "AI" | "Data" | "Integration" | "Automation" | "Multi-Agent"
  nodes: WorkflowNode[];      // heymrun WorkflowNode format (same as backend response)
  edges: WorkflowEdge[];      // heymrun WorkflowEdge format
  featured: boolean;          // shown on homepage
}
```

`nodes`/`edges` use heymrun's existing `WorkflowNode`/`WorkflowEdge` types (same format returned by the backend templates API). React Flow conversion (`{id, type, position, data}`) is done inside `TemplatePreviewModal` at render time — not stored in the static data.

Start with 10–15 curated templates. Managed manually in the repo.

### 2. `/templates` — Listing Page (`src/app/templates/page.tsx`)

- **Hero:** "Workflow Templates" heading + subtitle
- **Category tabs:** All · AI · Data · Integration · Automation · Multi-Agent
- **Grid:** Responsive (1/2/3/4 col). Each `TemplateCard`:
  - Name, short description
  - Category badge + tag chips
  - Node count
  - "Preview" button → opens `TemplatePreviewModal`
  - "Import" dropdown → Download `.json` | Copy JSON
- **SEO:** `generateMetadata`, OG tags, JSON-LD `ItemList` schema with all template names/URLs

### 3. `/templates/[slug]` — Detail Page (`src/app/templates/[slug]/page.tsx`)

- `generateStaticParams` — generates all slug pages at build time
- `generateMetadata` — per-template title/description/OG
- **Layout:**
  - Breadcrumb: Home → Templates → [Name]
  - Large title + long description (markdown rendered)
  - Tag list + node count
  - Full React Flow canvas (read-only, interactive — click node → config sidebar)
  - Import bar: Download `.json` + Copy JSON buttons
- **SEO:** JSON-LD `SoftwareApplication` schema per template

### 4. `TemplatePreviewModal` — `src/components/templates/TemplatePreviewModal.tsx`

React port of heymrun's `CanvasPreviewModal`:
- Full-screen backdrop
- Header: name, tags, node count, close button
- Body: React Flow canvas (read-only)
  - Nodes rendered as styled cards (type label + icon + color)
  - Click node → right panel slides in with field list
- Footer: Cancel | Download `.json` | Copy JSON

**Dependencies:** `@xyflow/react` (React Flow v12)

### 5. `TemplateCard` — `src/components/templates/TemplateCard.tsx`

Card component for grid. Shows name, description, category badge, tags, node count. Two action buttons: Preview + Import (dropdown).

### 6. `TemplatesSection` — `src/components/sections/TemplatesSection.tsx`

Homepage section (inserted before `LatestBlogSection`):
- Section heading: "Ready-made Workflow Templates"
- 3 featured templates (where `featured: true`) as cards
- "Browse All Templates →" CTA button linking to `/templates`
- Wrapped in `WaveSeparator` like other sections

### 7. Navbar (`src/components/sections/Navbar.tsx`)

Add to `navigation` array:
```typescript
{ name: 'Templates', href: '/templates' }
```

### 8. Footer (`src/components/sections/Footer.tsx`)

Add to `footerLinks.product`:
```typescript
{ name: 'Templates', href: '/templates' }
```

---

## heymrun Changes

### 9. `TemplatesBrowseDialog.vue` — new component

**Path:** `frontend/src/features/templates/components/TemplatesBrowseDialog.vue`

Full-screen dialog containing an `<iframe>` pointing to `https://heym.run/templates`.

- Props: `open: boolean`
- Emits: `close`
- Loading state: spinner overlay until iframe `load` event fires
- Header: "Browse Public Templates" title + X close button
- iframe has no border, fills dialog body

### 10. `TemplatesPage.vue` — add "Browse" button

Add a "Browse Public Templates" button to the existing top bar (right side, alongside search).

- Button icon: `Globe` (lucide)
- Opens `TemplatesBrowseDialog`

---

## Data Flow

```
heymweb /templates
  └── static JSON (src/lib/templates.ts)
        └── TemplateCard → Import dropdown
              ├── Download .json  →  browser downloads {name}.json
              └── Copy JSON       →  navigator.clipboard.writeText(JSON.stringify({nodes, edges}))
                                        └── user switches to heymrun
                                              └── Cmd+V on canvas → nodes pasted ✅

heymrun TemplatesPage
  └── "Browse Public Templates" button
        └── TemplatesBrowseDialog (iframe → heym.run/templates)
```

---

## File Checklist

**heymweb (new):**
- `src/lib/templates.ts` — static template data
- `src/app/templates/page.tsx` — listing page
- `src/app/templates/[slug]/page.tsx` — detail page
- `src/components/templates/TemplateCard.tsx`
- `src/components/templates/TemplatePreviewModal.tsx`
- `src/components/sections/TemplatesSection.tsx`

**heymweb (modified):**
- `src/components/sections/Navbar.tsx` — add Templates link
- `src/components/sections/Footer.tsx` — add Templates link
- `src/app/page.tsx` — add `<TemplatesSection />`

**heymrun (new):**
- `frontend/src/features/templates/components/TemplatesBrowseDialog.vue`

**heymrun (modified):**
- `frontend/src/features/templates/components/TemplatesPage.vue` — add Browse button + dialog

---

## Out of Scope

- Backend API changes (none needed)
- heymrun canvas paste handler (already exists — verify expected `{nodes, edges}` format before implementation)
- Auth/user-submitted templates on heymweb
- Search on heymweb (category filter is sufficient for 10–15 templates)
