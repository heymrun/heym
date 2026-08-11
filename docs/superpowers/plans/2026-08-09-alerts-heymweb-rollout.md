# Alerts — heymweb Rollout Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell the story of the Alerts feature on heym.run — a Solutions entry, a row in every comparison table, and one new blog post produced through the full SEO pipeline.

**Architecture:** Three independent deliverables in `/Users/mbakgun/Projects/heym/heymweb`. The Solutions entry and comparison rows are data edits to typed TypeScript files. The blog post is an MDX file produced by an eleven-skill research and writing pipeline whose topic is chosen by the research, not assumed up front.

**Tech Stack:** Next.js App Router + TypeScript + MDX + Bun.

**Companion plan:** [`2026-08-09-alerts-tab.md`](./2026-08-09-alerts-tab.md) — the heymrun feature itself. **Task 8 of that plan (the product docs) should be complete before writing the blog post**, so the article can link to real doc pages.

---

## ⚠️ Repository policy

- **No commits. No pushes.** Both repos stay dirty. This is explicit user instruction.
- heymweb has **no lint and no test runner** for app code. Verification is `bunx tsc --noEmit` and `bun run build`.
- `tests/seo/invariants.test.ts` hardcodes counts and **breaks type-checking, not just the test** when a count changes. Check it after any data-file edit.
- The heymweb `.env` is git-tracked. Never add a secret to it.
- Research writing plans stay under `.claude/memory/research/`, uncommitted.

**Standing content constraints — all of these are hard requirements:**

| Constraint | Rule |
|---|---|
| Author | Ceren Kaya Akgün (`authorKey: ceren`) |
| Em dashes | Minimal. Prefer commas, colons, or a new sentence. Natural English throughout. |
| FlowDiagram | Every post gets one. `steps` / `branches` pass as **single-quoted JSON strings** — the MDX map forwards string props only. No apostrophes and no `{...}` inside them. |
| Keywords | Every target keyword verified by counting occurrences **programmatically on the rendered string**, not by eye. A phrase at 0 occurrences has shipped before. |
| Citations | 2025 or newer only. Fetch the abstract or primary source — never cite a stat or affiliation from a search snippet. |
| Competitors | No competitor roundups against product rivals. Heym-only focus. |
| Titles | No year in the title if the previous post has one. |
| Templates | Grep `templates.ts` and `operationsTemplates.ts`; wire reciprocal article ↔ template links. |
| Meta | Description length must stay within the 120-160 character invariant. |

**Research tooling:** `brave_search_api` for search (jq-extract the large JSON), `website_loader` when WebFetch fails or returns nothing, `heym_google_analytics` and `heym_google_search_console` for real site data. Do not substitute WebSearch.

> **Connector reality check:** GA and GSC connectors returned fabricated data on 2026-07-25. Sanity-check any figure they return against a known real path before building an argument on it.

---

## Phase 1 — Solutions

### Task 1: Add the Alerts solution

**Files:**
- Modify: `src/lib/solutions.ts`

- [ ] **Step 1: Read an existing `productSurface` solution as the template**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && grep -n "productSurface" src/lib/solutions.ts
```

Alerts belongs in the `productSurface` shape, not the canvas-workflow shape: the story lives in a tab, not in a single workflow on a canvas. Read the whole solution object that uses it and match its field-by-field voice.

- [ ] **Step 2: Write the new `SolutionDefinition`**

Required fields, from the `SolutionDefinition` interface at the top of the file: `slug`, `name`, `shortName`, `tagline`, `flow`, `problem`, `today`, `withHeym`, `controlPoint`, `outcome`, `examples`, `capabilities`, `templateSlug`, `templateNote`, `productSurface`, `ctaLabel`, `metaTitle`, `metaDescription`.

Content guidance, in the house voice (plain, direct, no hype):

- `slug`: `workflow-monitoring`
- `problem`: automation platforms record failures, latency, and spend but never volunteer any of it; a broken workflow is found when somebody happens to look.
- `today`: someone checks a dashboard, or a customer reports it first.
- `withHeym`: threshold rules over a time window across four metrics, built in a wizard, optionally routed through a workflow.
- `controlPoint`: the Review-step backtest, which shows how often the rule would have fired before it is saved.
- `productSurface.steps`: one step per wizard stage, four to five total.
- `templateSlug`: pick a real existing slug. **Verify it resolves** — `grep -n "slug: '<slug>'" src/lib/templates.ts src/lib/operationsTemplates.ts`.

- [ ] **Step 3: Verify the solution surfaces everywhere it should**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && grep -rn "SOLUTIONS" src/lib/ src/components/ src/app/ --include=*.ts --include=*.tsx | grep -v "solutions.ts:"
```

The list feeds the nav dropdown, the search index, the company solution grid, and agent discovery. Confirm each consumer picks the new entry up from the array rather than from a hardcoded list.

- [ ] **Step 4: Typecheck and build**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && bunx tsc --noEmit && bun run build
```

Expected: both clean. If `tests/solutions/solutions.test.tsx` or `tests/seo/invariants.test.ts` asserts a solution count, update it.

- [ ] **Step 5: Checkpoint** — no commit. `git status --short` should show `src/lib/solutions.ts` modified.

---

## Phase 2 — Comparison tables

### Task 2: Research the competitor claims

**Files:** none yet — this task produces evidence.

- [ ] **Step 1: Establish what each competitor actually offers**

For n8n, Zapier, and Make.com, find in **official documentation** whether each supports **user-defined threshold alerts evaluated over a time window** on: error count, execution duration, LLM token/USD spend, and execution count.

Use `brave_search_api`, then `website_loader` on the official docs domain. Do not rely on a search snippet.

The distinction that matters: all three have per-execution failure notification. That is not the same as "tell me when errors exceed 20 in 15 minutes." Cost-threshold and duration-threshold alerts are where the real gap is likely to be.

- [ ] **Step 2: Record the evidence**

Write findings to `.claude/memory/research/competitor-analysis/alerts-2026-08-09.md`: per competitor, the exact capability, the doc URL, and the date checked. This file is the source for both the heymrun footnote and the heymweb notes.

- [ ] **Step 3: Verify citation domains are not Semrush-blocked**

```bash
curl -sI -A "Mozilla/5.0 (compatible; SemrushBot/7~bl; +http://www.semrush.com/bot.html)" <url>
```

`mckinsey.com` is known blocked. Drop any blocked domain rather than citing it.

---

### Task 3: Add the comparison row

**Files:**
- Modify: `src/lib/comparisons.ts`
- Modify: `src/components/sections/ComparisonSection.tsx`

- [ ] **Step 1: Add the row to `ComparisonSection.tsx`**

The `ComparisonRow` interface is at line 11; rows are in the `comparisons` array from line 26. Add after the `LLM token cost tracking (USD)` row:

```typescript
  {
    label: 'Metric alerts (errors, duration, cost, run count)',
    heym: 'yes', n8n: '<from Task 2>', zapier: '<from Task 2>', make: '<from Task 2>',
    notes: {
      heym:
        'Threshold rules evaluated over a user-defined time window across four metrics: error count, execution duration, LLM token or USD spend, and execution count. Built in a five-step wizard that AI can prefill, with a backtest before saving, and optionally routed through a workflow.',
      n8n: '<official doc finding, with the date checked>',
      zapier: '<official doc finding, with the date checked>',
      make: '<official doc finding, with the date checked>',
    },
  },
```

Match the `FeatureStatus` union exactly — read its definition rather than guessing which of `'yes' | 'partial' | 'limited' | 'no'` are valid.

- [ ] **Step 2: Update `COMPARISON_LAST_REVIEWED`** in `src/lib/comparisons.ts` to `2026-08-09` and `COMPARISON_LAST_REVIEWED_LABEL` to `August 9, 2026`.

- [ ] **Step 3: Check whether per-competitor comparison pages mention monitoring**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && grep -n "observability\|monitoring\|traces" src/lib/comparisons.ts
```

Where `heymFit` or `competitorFit` already discusses observability, add one clause about alerting. Do not rewrite those paragraphs.

- [ ] **Step 4: Typecheck and build** — `bunx tsc --noEmit && bun run build`. Expected: clean. Watch `tests/seo/invariants.test.ts` for a hardcoded comparison-row count.

---

## Phase 3 — Blog post

> Run the skills in this exact order. Each one's output feeds the next. Do not skip ahead to writing.

### Task 4: SERP analysis

- [ ] **Step 1: Invoke the `serp-analysis` skill.**

- [ ] **Step 2: Analyze the SERP for the candidate query cluster**

Seed queries: `workflow monitoring alerts`, `ai workflow cost alerts`, `llm cost monitoring`, `automation error rate alerting`, `llm token budget alert`.

For each: SERP features present, AI Overview presence, who ranks, what content type wins, and whether the intent is informational or comparison.

- [ ] **Step 3: Save to** `.claude/memory/research/serp-analysis/alerts-2026-08-09.md`.

---

### Task 5: Content gap analysis

- [ ] **Step 1: Invoke the `content-gap-analysis` skill.**

- [ ] **Step 2: Map coverage**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && ls src/content/blog
```

47 posts exist. **List them before claiming any gap.** Identify which existing post is closest to the alerting topic and how the new post differs — if it substantially overlaps, the topic is wrong, not the framing.

- [ ] **Step 3: Check whether this founds a new cluster or joins an existing one**, then save to `.claude/memory/research/content-gap-analysis/alerts-2026-08-09.md`.

---

### Task 6: Keyword research

- [ ] **Step 1: Invoke the `keyword-research` skill.**

- [ ] **Step 2: Pull real site data**

Call `heym_google_search_console` for current impressions and CTR on any existing monitoring, observability, or cost-related query. Call `heym_google_analytics` for the landing pages that already draw operations-shaped traffic.

> The `ai-agent-observability` post is a known case: 5,977 impressions at 0.13% CTR. If the new topic overlaps it, the right move may be refreshing that post rather than publishing a new one. **Decide this explicitly and say so** — a CTR refresh has repeatedly scored as the site's biggest lever, and this is the third session where that has been the open recommendation.

- [ ] **Step 3: Build the keyword set** — one primary keyword, four to six secondaries, with volume, difficulty, and intent. Prefer a tail with genuine demand over a fat head the site cannot rank for.

- [ ] **Step 4: Present the topic recommendation to the user before drafting.**

State: the proposed title, primary keyword, why it wins, and whether it founds a cluster. Include the "refresh instead" option if Step 2 supports it. **Wait for confirmation before Task 7** — a wrong topic wastes the entire remaining pipeline.

- [ ] **Step 5: Save to** `.claude/memory/research/keyword-research/alerts-2026-08-09.md`.

---

### Task 7: Write the draft

- [ ] **Step 1: Invoke the `seo-content-writer` skill.**

- [ ] **Step 2: Verify every Heym claim against heymrun source before writing it**

Any feature statement about Heym must be confirmed in `/Users/mbakgun/Projects/heym/heymrun`. For this post the relevant source of truth is the Alerts implementation from the companion plan plus `frontend/src/docs/content/tabs/alerts-tab.md`. Do not describe behavior the code does not have.

- [ ] **Step 3: Create `src/content/blog/<slug>.mdx`** with frontmatter matching the existing posts exactly:

```yaml
---
title: "<from Task 6>"
slug: <slug>
description: "<120-160 characters>"
date: 2026-08-09
author: Ceren Kaya Akgün
authorKey: ceren
tags: [<from Task 6>]
primaryKeyword: <from Task 6>
secondaryKeywords:
  - <...>
seoScore: <set after Task 11>
status: published
faq:
  - question: "..."
    answer: "..."
---
```

- [ ] **Step 4: Add the FlowDiagram**

Single-quoted JSON strings, no apostrophes and no braces inside them:

```mdx
<FlowDiagram
  steps='[{"title":"...","detail":"..."}]'
/>
```

- [ ] **Step 5: Commit the draft to the working tree only.**

Per the standing lesson: a mid-session `git pull` once wiped an entire untracked draft plus every edit. **`git add` the file so it is at least staged**, or keep a copy in the scratchpad. Do not push. If a file seems to vanish, check `git reflog` before rewriting it.

---

### Task 8: GEO optimization

- [ ] **Step 1: Invoke the `geo-content-optimizer` skill.**
- [ ] **Step 2: Optimize for citation by ChatGPT, Perplexity, AI Overviews, Gemini, and Claude** — self-contained claims, clear entity naming, answer-first structure, and quotable stat sentences.
- [ ] **Step 3: Re-verify** that no optimization pass introduced an unsourced or pre-2025 statistic.

---

### Task 9: Meta tags

- [ ] **Step 1: Invoke the `meta-tags-optimizer` skill.**
- [ ] **Step 2: Optimize title and description.** The description must land between 120 and 160 characters — this is an enforced invariant, not a guideline.
- [ ] **Step 3: Check the title against the previous post.** If the most recent post's title carries a year, this one must not.
- [ ] **Step 4: Do not set an OG image in `generateMetadata`.** Per-post OG images are generated by `next/og`; setting `images` there breaks them.

---

### Task 10: Content quality audit

- [ ] **Step 1: Invoke the `content-quality-auditor` skill.**
- [ ] **Step 2: Run CORE-EEAT scoring with veto checks.** Fix anything that fails a veto before proceeding.

---

### Task 11: On-page audit

- [ ] **Step 1: Invoke the `on-page-seo-auditor` skill.**
- [ ] **Step 2: Verify keyword placement programmatically**

Count exact-phrase occurrences on the rendered string, not the MDX source, and not by eye:

```bash
cd /Users/mbakgun/Projects/heym/heymweb && \
  grep -o -i "<exact phrase>" src/content/blog/<slug>.mdx | wc -l
```

Repeat for the primary keyword and every secondary. **A zero count is a shipping bug** — three posts have gone out with a target keyword at zero occurrences.

- [ ] **Step 3: Run a numeric consistency sweep.** Every number in the post must agree with every other mention of it and with its source.
- [ ] **Step 4: Set `seoScore` in the frontmatter** from the audit result.

---

### Task 12: Schema markup

- [ ] **Step 1: Invoke the `schema-markup-generator` skill.**
- [ ] **Step 2: Confirm the FAQ frontmatter produces valid FAQPage JSON-LD** through the existing blog schema pipeline. Check how a current post does it rather than adding new markup by hand.

---

### Task 13: Internal linking

- [ ] **Step 1: Invoke the `internal-linking-optimizer` skill.**

- [ ] **Step 2: Wire reciprocal template links**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && grep -n "slug:" src/lib/templates.ts src/lib/operationsTemplates.ts | head -60
```

Find the templates this article naturally pairs with, link to them from the article, and add a "Built from the walkthrough in ..." line to each template's `longDescription`. The link must go both ways.

- [ ] **Step 3: Link to the new Solutions page** from Task 1, and to the heymrun Alerts doc page.

- [ ] **Step 4: Link from related existing posts.** The observability and cost posts are the strongest candidates. Add the inbound links; do not rewrite those posts.

---

### Task 14: Competitor analysis

- [ ] **Step 1: Invoke the `competitor-analysis` skill.**
- [ ] **Step 2: Benchmark the ranking pages for the primary keyword** — what they cover that the draft does not, and where the draft is genuinely stronger. Fill real gaps only; do not pad to match a word count.
- [ ] **Step 3: This is analysis input, not article content.** The post stays Heym-only with no competitor roundup.
- [ ] **Step 4: Save to** `.claude/memory/research/competitor-analysis/alerts-post-2026-08-09.md`.

---

### Task 15: Verify the site builds

- [ ] **Step 1: Typecheck and build**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && bunx tsc --noEmit && bun run build
```

Expected: both clean.

> A stale `next-server` survives `pkill` and will happily serve an old build. If output looks wrong, confirm the process actually restarted before debugging the code.

- [ ] **Step 2: Check the SEO invariants**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && grep -n "length\|toBe([0-9]" tests/seo/invariants.test.ts | head -20
```

Update any hardcoded post, solution, or comparison-row count. These break `tsc`, not just the test.

- [ ] **Step 3: Confirm the post appears** in the blog index, the sitemap, `feed.xml`, and the Cmd+K search index.

- [ ] **Step 4: Re-run `bun run sync-docs`** if the heymrun docs changed, so site search picks up the new Alerts doc page.

---

## Phase 4 — Close out

### Task 16: Update memory

- [ ] **Step 1: Invoke the `memory-management` skill** and refresh the hot cache with this session's findings.

- [ ] **Step 2: Write a project memory** for the Alerts feature at
`/Users/mbakgun/.claude/projects/-Users-mbakgun-Projects-heym-heymrun/memory/`, type `project`,
covering: what shipped in both repos, that everything is LOCAL and uncommitted, the four alert types,
the `on_recovery` default, the system-scope-means-owner-accessible decision, and any non-obvious
implementation traps found during the build.

- [ ] **Step 3: Update the blog progress memory** — `project_heymweb_blog_progress.md` — with the new post number, slug, date, author, wedge, and whether it founds a cluster. Note whether the CTR-refresh recommendation is still open.

- [ ] **Step 4: Add the one-line pointer** to `MEMORY.md`.

- [ ] **Step 5: Confirm nothing was committed in either repo**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && git log --oneline -1
cd /Users/mbakgun/Projects/heym/heymweb && git log --oneline -1
```

Both must show the same commit they showed at session start. heymrun's was `52f6acc7`.

---

## Verification summary

| Check | Command |
|---|---|
| heymweb types | `bunx tsc --noEmit` |
| heymweb build | `bun run build` |
| SEO invariants | inspect `tests/seo/invariants.test.ts` counts |
| Keyword occurrences | `grep -o -i "<phrase>" <file> \| wc -l` per target keyword, all non-zero |
| Meta description length | 120-160 characters |
| Citation freshness | every source dated 2025 or newer, fetched from primary |
| Template reciprocity | article links to template AND template `longDescription` links back |
| Nothing committed | `git log --oneline -1` unchanged in both repos |
