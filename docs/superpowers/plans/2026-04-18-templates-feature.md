# Templates Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a public `/templates` gallery to heymweb with categorised cards, React Flow canvas preview (same UX as heymrun's CanvasPreviewModal), Download .json + Copy JSON import, detail pages per template for SEO; and wire heymrun's Templates screen to browse that page via an iframe dialog.

**Architecture:** heymweb serves static TypeScript template data (`src/lib/templates.ts`). A client-side React Flow canvas (`@xyflow/react`) renders interactive node graphs. heymrun adds a single `TemplatesBrowseDialog.vue` that iframes `https://heym.run/templates`.

**Tech Stack:** Next.js 15, Vue 3, `@xyflow/react` (React Flow v12), `next-mdx-remote/rsc` (already installed), Tailwind CSS, Shadcn/ui (dialog, tabs already present in heymweb)

---

## File Map

**heymweb — create**
| File | Responsibility |
|---|---|
| `src/lib/templates.ts` | `StaticTemplate` type + 12 curated template objects |
| `src/components/templates/TemplateCanvasNode.tsx` | React Flow custom node component (client) |
| `src/components/templates/TemplatePreviewContent.tsx` | Canvas + right sidebar + import actions (client) |
| `src/components/templates/TemplatePreviewModal.tsx` | Modal wrapper around TemplatePreviewContent (client) |
| `src/components/templates/TemplateCard.tsx` | Grid card with Preview + Import dropdown (client) |
| `src/components/templates/TemplatesPageClient.tsx` | Category tabs + template grid (client) |
| `src/app/templates/page.tsx` | Listing page — metadata + JSON-LD (server) |
| `src/app/templates/[slug]/page.tsx` | Detail page — generateStaticParams + metadata + canvas (server) |
| `src/components/sections/TemplatesSection.tsx` | Homepage featured section (server) |

**heymweb — modify**
| File | Change |
|---|---|
| `src/components/sections/Navbar.tsx` | Add Templates nav link |
| `src/components/sections/Footer.tsx` | Add Templates to product links |
| `src/app/page.tsx` | Add `<TemplatesSection />` before `<LatestBlogSection />` |
| `src/lib/site.ts` | Add `/templates` to `STATIC_ROUTES` |
| `src/app/sitemap.ts` | Add template slug routes |

**heymrun — create**
| File | Responsibility |
|---|---|
| `frontend/src/features/templates/components/TemplatesBrowseDialog.vue` | Full-screen iframe dialog |

**heymrun — modify**
| File | Change |
|---|---|
| `frontend/src/features/templates/components/TemplatesPage.vue` | Add Globe button + dialog |

---

## Task 1: Install `@xyflow/react` in heymweb

**Files:**
- Modify: `package.json` (heymweb)

- [ ] **Step 1: Install**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npm install @xyflow/react
```

- [ ] **Step 2: Verify**

```bash
grep '"@xyflow/react"' /Users/mbakgun/Projects/heym/heymweb/package.json
```

Expected: line with `"@xyflow/react": "^..."`.

- [ ] **Step 3: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add package.json package-lock.json
git commit -m "feat(templates): install @xyflow/react"
```

---

## Task 2: Create `src/lib/templates.ts`

**Files:**
- Create: `/Users/mbakgun/Projects/heym/heymweb/src/lib/templates.ts`

- [ ] **Step 1: Create the file**

```typescript
export type TemplateCategory = 'AI' | 'Multi-Agent' | 'Integration' | 'Automation' | 'Data'

export interface TemplateNode {
  id: string
  type: string
  position: { x: number; y: number }
  data: { label: string } & Record<string, unknown>
}

export interface TemplateEdge {
  id: string
  source: string
  target: string
  sourceHandle?: string
  targetHandle?: string
}

export interface StaticTemplate {
  slug: string
  name: string
  description: string
  longDescription: string
  tags: string[]
  category: TemplateCategory
  nodes: TemplateNode[]
  edges: TemplateEdge[]
  featured: boolean
}

const TEMPLATES: StaticTemplate[] = [
  {
    slug: 'ai-email-triage',
    name: 'AI Email Triage',
    description: 'Classify incoming emails by priority and route urgent ones to Slack instantly.',
    longDescription: `## AI Email Triage

Automatically classify every incoming email as urgent, normal, or low priority using GPT-4o, then route urgent messages to a Slack channel while logging the rest.

### What this workflow does

1. **Webhook trigger** receives the raw email payload
2. **LLM node** classifies priority and extracts a one-line reason
3. **Condition node** checks if priority is urgent
4. Urgent → **Slack notification** to \`#alerts\`
5. Non-urgent → **Output node** logs the email

### Use cases

- Customer support inbox triage
- Sales lead prioritisation
- IT incident detection from email alerts

### Customisation

Replace the Slack channel, adjust the classification prompt, or add more branches for different priority levels.`,
    tags: ['AI', 'Email', 'Slack', 'Automation'],
    category: 'AI',
    featured: true,
    nodes: [
      { id: '1', type: 'textInput', position: { x: 0, y: 0 }, data: { label: 'Email Webhook', value: '' } },
      { id: '2', type: 'llm', position: { x: 220, y: 0 }, data: { label: 'Classify Priority', model: 'gpt-4o', systemInstruction: 'Classify the email as urgent, normal, or low priority. Return JSON: {"priority":"urgent|normal|low","reason":"one sentence"}' } },
      { id: '3', type: 'condition', position: { x: 440, y: 0 }, data: { label: 'Is Urgent?', condition: "$output.priority === 'urgent'" } },
      { id: '4', type: 'slack', position: { x: 660, y: -110 }, data: { label: 'Alert Team', channel: '#alerts', message: '🚨 Urgent email: $output.reason' } },
      { id: '5', type: 'output', position: { x: 660, y: 110 }, data: { label: 'Log Email', outputKey: 'result' } },
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2' },
      { id: 'e2-3', source: '2', target: '3' },
      { id: 'e3-4', source: '3', target: '4', sourceHandle: 'true' },
      { id: 'e3-5', source: '3', target: '5', sourceHandle: 'false' },
    ],
  },
  {
    slug: 'rag-document-qa',
    name: 'RAG Document Q&A',
    description: 'Answer questions from your documents using vector search and GPT-4o.',
    longDescription: `## RAG Document Q&A

Build a question-answering system over your own documents with retrieval-augmented generation. Upload documents to Qdrant, then let this workflow find the most relevant chunks and synthesise an accurate answer.

### What this workflow does

1. **Input node** receives the user question
2. **Qdrant RAG node** performs hybrid vector + keyword search across your collection
3. **LLM node** synthesises an answer from the retrieved chunks
4. **Output node** returns the final answer with source references

### Use cases

- Internal knowledge base Q&A
- Product documentation assistant
- Legal document analysis

### Prerequisites

Create a Qdrant vector store in the Vector Stores panel and upload your documents before running this workflow.`,
    tags: ['RAG', 'AI', 'Qdrant', 'Q&A'],
    category: 'AI',
    featured: true,
    nodes: [
      { id: '1', type: 'textInput', position: { x: 0, y: 0 }, data: { label: 'User Question', value: '' } },
      { id: '2', type: 'rag', position: { x: 220, y: 0 }, data: { label: 'Search Docs', ragOperation: 'search', collectionName: 'my-docs', topK: 5 } },
      { id: '3', type: 'llm', position: { x: 440, y: 0 }, data: { label: 'Generate Answer', model: 'gpt-4o', systemInstruction: 'Answer the question using only the provided context. Cite sources. If unsure, say so.' } },
      { id: '4', type: 'output', position: { x: 660, y: 0 }, data: { label: 'Return Answer', outputKey: 'answer' } },
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2' },
      { id: 'e2-3', source: '2', target: '3' },
      { id: 'e3-4', source: '3', target: '4' },
    ],
  },
  {
    slug: 'multi-agent-research',
    name: 'Multi-Agent Research Pipeline',
    description: 'A researcher agent gathers facts, a writer agent produces a polished report.',
    longDescription: `## Multi-Agent Research Pipeline

Delegate research and writing to two specialised agents. The researcher agent searches the web and summarises findings; the writer agent turns raw notes into a polished report.

### What this workflow does

1. **Input node** receives the research topic
2. **Researcher Agent** uses HTTP tools to gather information from multiple sources
3. **Writer Agent** receives the researcher's notes and produces a structured report
4. **Output node** returns the final document

### Use cases

- Competitive intelligence reports
- Market research summaries
- Technical overview documents

### Customisation

Add MCP server connections to give the researcher agent access to specialised data sources, or connect the writer agent to a Google Docs tool to publish directly.`,
    tags: ['Multi-Agent', 'Research', 'AI', 'Orchestration'],
    category: 'Multi-Agent',
    featured: true,
    nodes: [
      { id: '1', type: 'textInput', position: { x: 0, y: 0 }, data: { label: 'Research Topic', value: '' } },
      { id: '2', type: 'agent', position: { x: 220, y: 0 }, data: { label: 'Researcher Agent', model: 'gpt-4o', systemInstruction: 'You are a research assistant. Search the web, gather facts, and return structured notes on the given topic.' } },
      { id: '3', type: 'agent', position: { x: 440, y: 0 }, data: { label: 'Writer Agent', model: 'gpt-4o', systemInstruction: 'You are a technical writer. Turn the research notes into a clear, well-structured report with sections and bullet points.' } },
      { id: '4', type: 'output', position: { x: 660, y: 0 }, data: { label: 'Final Report', outputKey: 'report' } },
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2' },
      { id: 'e2-3', source: '2', target: '3' },
      { id: 'e3-4', source: '3', target: '4' },
    ],
  },
  {
    slug: 'webhook-slack-notifier',
    name: 'Webhook → Slack Notifier',
    description: 'Receive a webhook, enrich the payload via HTTP, and post a formatted Slack message.',
    longDescription: `## Webhook → Slack Notifier

A general-purpose integration pattern: receive events from any external system, optionally enrich them with a secondary API call, then post a formatted message to Slack.

### What this workflow does

1. **Webhook trigger** accepts POST requests from any external service
2. **HTTP node** optionally fetches additional context (e.g. user details from your database)
3. **Slack node** posts a formatted message to the target channel
4. **Output node** returns a 200 acknowledgement

### Use cases

- GitHub / GitLab push notifications
- Stripe payment alerts
- PagerDuty incident forwarding`,
    tags: ['Webhook', 'Slack', 'Integration', 'Notifications'],
    category: 'Integration',
    featured: false,
    nodes: [
      { id: '1', type: 'textInput', position: { x: 0, y: 0 }, data: { label: 'Webhook', value: '' } },
      { id: '2', type: 'http', position: { x: 220, y: 0 }, data: { label: 'Enrich Payload', method: 'GET', url: 'https://api.example.com/lookup?id=$input.id' } },
      { id: '3', type: 'slack', position: { x: 440, y: 0 }, data: { label: 'Notify Slack', channel: '#notifications', message: '📣 New event: $output.summary' } },
      { id: '4', type: 'output', position: { x: 660, y: 0 }, data: { label: 'Ack', outputKey: 'status' } },
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2' },
      { id: 'e2-3', source: '2', target: '3' },
      { id: 'e3-4', source: '3', target: '4' },
    ],
  },
  {
    slug: 'scheduled-report-generator',
    name: 'Scheduled Report Generator',
    description: 'Fetch data on a schedule, summarise with AI, and email the report automatically.',
    longDescription: `## Scheduled Report Generator

Run this workflow on a cron schedule to pull data from any API, generate an AI-written summary, and deliver it by email — no manual work required.

### What this workflow does

1. **Cron trigger** fires on your schedule (e.g. every Monday at 8 AM)
2. **HTTP node** fetches the latest data from your API
3. **LLM node** writes a concise executive summary
4. **Send Email node** delivers the report to your inbox
5. **Output node** logs the run

### Use cases

- Weekly sales dashboards
- Daily infrastructure cost summaries
- Monthly user growth reports`,
    tags: ['Cron', 'Email', 'AI', 'Reporting'],
    category: 'Automation',
    featured: false,
    nodes: [
      { id: '1', type: 'cron', position: { x: 0, y: 0 }, data: { label: 'Every Monday 8AM', cronExpression: '0 8 * * 1' } },
      { id: '2', type: 'http', position: { x: 200, y: 0 }, data: { label: 'Fetch Metrics', method: 'GET', url: 'https://api.example.com/metrics' } },
      { id: '3', type: 'llm', position: { x: 400, y: 0 }, data: { label: 'Write Summary', model: 'gpt-4o', systemInstruction: 'Write a concise executive summary of the metrics data. Use bullet points. Highlight any anomalies.' } },
      { id: '4', type: 'sendEmail', position: { x: 600, y: 0 }, data: { label: 'Email Report', to: 'team@example.com', subject: 'Weekly Report — $date', body: '$output.summary' } },
      { id: '5', type: 'output', position: { x: 800, y: 0 }, data: { label: 'Log Run', outputKey: 'result' } },
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2' },
      { id: 'e2-3', source: '2', target: '3' },
      { id: 'e3-4', source: '3', target: '4' },
      { id: 'e4-5', source: '4', target: '5' },
    ],
  },
  {
    slug: 'google-sheets-sync',
    name: 'Google Sheets Data Sync',
    description: 'Pull data from an API on a schedule and append rows to a Google Sheet automatically.',
    longDescription: `## Google Sheets Data Sync

Keep a Google Sheet up to date automatically. This workflow fetches data from any REST API, transforms it with the Set node, and appends new rows to your spreadsheet.

### What this workflow does

1. **Cron trigger** fires on your desired schedule
2. **HTTP node** fetches the latest records from your API
3. **Set node** maps API fields to spreadsheet columns
4. **Google Sheets node** appends the transformed rows
5. **Output node** logs the sync result

### Use cases

- CRM data exports to sheets
- Financial data archiving
- Inventory tracking dashboards`,
    tags: ['Google Sheets', 'Data', 'Cron', 'Sync'],
    category: 'Data',
    featured: false,
    nodes: [
      { id: '1', type: 'cron', position: { x: 0, y: 0 }, data: { label: 'Daily Sync', cronExpression: '0 6 * * *' } },
      { id: '2', type: 'http', position: { x: 200, y: 0 }, data: { label: 'Fetch Records', method: 'GET', url: 'https://api.example.com/records?since=$yesterday' } },
      { id: '3', type: 'set', position: { x: 400, y: 0 }, data: { label: 'Map Fields', assignments: [{ key: 'row', value: '[$id, $name, $value, $date]' }] } },
      { id: '4', type: 'googleSheets', position: { x: 600, y: 0 }, data: { label: 'Append Rows', spreadsheetId: 'your-sheet-id', range: 'Sheet1!A:D' } },
      { id: '5', type: 'output', position: { x: 800, y: 0 }, data: { label: 'Log Result', outputKey: 'synced' } },
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2' },
      { id: 'e2-3', source: '2', target: '3' },
      { id: 'e3-4', source: '3', target: '4' },
      { id: 'e4-5', source: '4', target: '5' },
    ],
  },
  {
    slug: 'web-scraper-summarizer',
    name: 'Web Scraper Summarizer',
    description: 'Scrape any URL and get an AI-generated summary in seconds.',
    longDescription: `## Web Scraper Summarizer

Enter a URL and receive a structured AI summary. The Crawler node extracts the page content; the LLM node turns it into a concise briefing.

### What this workflow does

1. **Input node** receives the URL
2. **Crawler node** fetches and extracts the page text
3. **LLM node** generates a structured summary (key points, main topic, sentiment)
4. **Output node** returns the summary

### Use cases

- Competitor page monitoring
- News article digests
- Research note generation`,
    tags: ['Crawler', 'AI', 'Scraping', 'Summarisation'],
    category: 'Automation',
    featured: false,
    nodes: [
      { id: '1', type: 'textInput', position: { x: 0, y: 0 }, data: { label: 'Target URL', value: 'https://' } },
      { id: '2', type: 'crawler', position: { x: 220, y: 0 }, data: { label: 'Scrape Page', url: '$input.text', selector: 'body' } },
      { id: '3', type: 'llm', position: { x: 440, y: 0 }, data: { label: 'Summarise', model: 'gpt-4o', systemInstruction: 'Summarise the text. Return JSON: {title, main_points: string[], sentiment, word_count}' } },
      { id: '4', type: 'output', position: { x: 660, y: 0 }, data: { label: 'Summary', outputKey: 'summary' } },
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2' },
      { id: 'e2-3', source: '2', target: '3' },
      { id: 'e3-4', source: '3', target: '4' },
    ],
  },
  {
    slug: 'api-health-monitor',
    name: 'API Health Monitor',
    description: 'Ping your API on a schedule and alert Slack when it goes down.',
    longDescription: `## API Health Monitor

Set up a lightweight uptime monitor for any HTTP endpoint. The workflow pings your API every N minutes and sends a Slack alert the moment it returns a non-2xx response.

### What this workflow does

1. **Cron trigger** fires every 5 minutes (configurable)
2. **HTTP node** pings the health endpoint
3. **Condition node** checks if the status code is not 200
4. Failure → **Slack alert** to the on-call channel
5. Success → **Output node** logs the healthy check

### Use cases

- Production API uptime monitoring
- Database connectivity checks
- Third-party integration health checks`,
    tags: ['Monitoring', 'Slack', 'Cron', 'HTTP'],
    category: 'Integration',
    featured: false,
    nodes: [
      { id: '1', type: 'cron', position: { x: 0, y: 0 }, data: { label: 'Every 5 Min', cronExpression: '*/5 * * * *' } },
      { id: '2', type: 'http', position: { x: 200, y: 0 }, data: { label: 'Health Check', method: 'GET', url: 'https://api.example.com/health' } },
      { id: '3', type: 'condition', position: { x: 400, y: 0 }, data: { label: 'Status != 200?', condition: '$output.statusCode !== 200' } },
      { id: '4', type: 'slack', position: { x: 620, y: -110 }, data: { label: 'Alert On-Call', channel: '#oncall', message: '🔴 API down! Status: $output.statusCode' } },
      { id: '5', type: 'output', position: { x: 620, y: 110 }, data: { label: 'Log Healthy', outputKey: 'status' } },
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2' },
      { id: 'e2-3', source: '2', target: '3' },
      { id: 'e3-4', source: '3', target: '4', sourceHandle: 'true' },
      { id: 'e3-5', source: '3', target: '5', sourceHandle: 'false' },
    ],
  },
  {
    slug: 'lead-scoring-agent',
    name: 'Lead Scoring Agent',
    description: 'Score inbound leads with AI and auto-notify sales for hot prospects.',
    longDescription: `## Lead Scoring Agent

When a new lead comes in, an AI agent evaluates their profile, assigns a score from 0–100, and automatically notifies the sales team via Slack for high-value prospects.

### What this workflow does

1. **Input node** receives the lead data (name, company, role, source)
2. **AI Agent** analyses the lead against your ideal customer profile and assigns a score with reasoning
3. **Condition node** checks if score ≥ 70
4. Hot lead → **Slack notification** to the sales channel
5. Cold lead → **Output node** logs for CRM import

### Use cases

- SaaS inbound lead qualification
- E-commerce VIP customer identification
- B2B sales pipeline prioritisation`,
    tags: ['AI', 'Sales', 'Slack', 'Automation'],
    category: 'Multi-Agent',
    featured: false,
    nodes: [
      { id: '1', type: 'textInput', position: { x: 0, y: 0 }, data: { label: 'Lead Data', value: '' } },
      { id: '2', type: 'agent', position: { x: 220, y: 0 }, data: { label: 'Score Lead', model: 'gpt-4o', systemInstruction: 'Score this lead from 0-100 based on company size, role seniority, and intent signals. Return JSON: {score, reasoning, tier}' } },
      { id: '3', type: 'condition', position: { x: 440, y: 0 }, data: { label: 'Score ≥ 70?', condition: '$output.score >= 70' } },
      { id: '4', type: 'slack', position: { x: 660, y: -110 }, data: { label: 'Notify Sales', channel: '#sales-hot-leads', message: '🔥 Hot lead! Score: $output.score — $output.reasoning' } },
      { id: '5', type: 'output', position: { x: 660, y: 110 }, data: { label: 'Log Lead', outputKey: 'lead' } },
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2' },
      { id: 'e2-3', source: '2', target: '3' },
      { id: 'e3-4', source: '3', target: '4', sourceHandle: 'true' },
      { id: 'e3-5', source: '3', target: '5', sourceHandle: 'false' },
    ],
  },
  {
    slug: 'redis-cache-pipeline',
    name: 'Redis Cache Pipeline',
    description: 'Check Redis for cached results before hitting a slow API — serve stale data in milliseconds.',
    longDescription: `## Redis Cache Pipeline

A classic cache-aside pattern. For every request, first check Redis for a cached result. On a cache hit, return immediately. On a miss, call the real API, cache the result, and return it.

### What this workflow does

1. **Input node** receives the request key
2. **Redis GET** checks the cache
3. **Condition node** checks if a cached value exists
4. Cache miss → **HTTP node** calls the real API, then **Redis SET** caches the result
5. Cache hit → **Output node** returns the cached value directly

### Use cases

- High-traffic API response caching
- Expensive AI inference result caching
- Repeated database query caching`,
    tags: ['Redis', 'Cache', 'HTTP', 'Performance'],
    category: 'Data',
    featured: false,
    nodes: [
      { id: '1', type: 'textInput', position: { x: 0, y: 0 }, data: { label: 'Request Key', value: '' } },
      { id: '2', type: 'redis', position: { x: 200, y: 0 }, data: { label: 'Check Cache', redisOperation: 'get', key: '$input.text' } },
      { id: '3', type: 'condition', position: { x: 400, y: 0 }, data: { label: 'Cache Hit?', condition: '$output !== null' } },
      { id: '4', type: 'http', position: { x: 600, y: 110 }, data: { label: 'Fetch from API', method: 'GET', url: 'https://api.example.com/data?key=$input.text' } },
      { id: '5', type: 'output', position: { x: 800, y: 0 }, data: { label: 'Return Result', outputKey: 'data' } },
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2' },
      { id: 'e2-3', source: '2', target: '3' },
      { id: 'e3-5', source: '3', target: '5', sourceHandle: 'true' },
      { id: 'e3-4', source: '3', target: '4', sourceHandle: 'false' },
      { id: 'e4-5', source: '4', target: '5' },
    ],
  },
  {
    slug: 'ai-support-chatbot',
    name: 'AI Support Chatbot',
    description: 'An AI agent that answers support questions using your documentation as context.',
    longDescription: `## AI Support Chatbot

Power a support chatbot with your own documentation. The RAG node retrieves the most relevant docs for each question; the Agent node crafts a helpful, accurate response.

### What this workflow does

1. **Input node** receives the user's question
2. **Qdrant RAG node** searches your documentation for relevant context
3. **Agent node** uses the retrieved context plus its system prompt to answer accurately
4. **Output node** returns the answer

### Setup

1. Upload your documentation to a Qdrant vector store (Vector Stores panel)
2. Set the collection name in the RAG node
3. Publish the workflow as a Portal to get a shareable chat URL

### Use cases

- Developer documentation assistant
- Product FAQ bot
- Onboarding guide chatbot`,
    tags: ['AI', 'RAG', 'Chatbot', 'Support'],
    category: 'AI',
    featured: false,
    nodes: [
      { id: '1', type: 'textInput', position: { x: 0, y: 0 }, data: { label: 'User Question', value: '' } },
      { id: '2', type: 'rag', position: { x: 220, y: 0 }, data: { label: 'Search Docs', ragOperation: 'search', collectionName: 'support-docs', topK: 4 } },
      { id: '3', type: 'agent', position: { x: 440, y: 0 }, data: { label: 'Support Agent', model: 'gpt-4o', systemInstruction: 'You are a helpful support agent. Answer the question using only the provided documentation context. Be concise and friendly.' } },
      { id: '4', type: 'output', position: { x: 660, y: 0 }, data: { label: 'Answer', outputKey: 'answer' } },
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2' },
      { id: 'e2-3', source: '2', target: '3' },
      { id: 'e3-4', source: '3', target: '4' },
    ],
  },
  {
    slug: 'slack-command-bot',
    name: 'Slack Command Bot',
    description: 'Handle slash commands from Slack, process with AI, and reply in-thread.',
    longDescription: `## Slack Command Bot

Turn Slack slash commands into AI-powered actions. This workflow receives a command, routes it by type, processes it with GPT-4o, and replies directly in the Slack thread.

### What this workflow does

1. **Slack Trigger** receives the slash command payload
2. **Condition node** routes by command type (e.g. \`/summarise\` vs \`/translate\`)
3. **LLM node** processes the command text
4. **Slack node** posts the reply to the original channel/thread
5. **Output node** logs the interaction

### Use cases

- \`/summarise\` — paste a block of text and get a summary
- \`/translate\` — translate text to any language
- \`/explain\` — explain code or technical concepts in plain English`,
    tags: ['Slack', 'AI', 'Commands', 'Integration'],
    category: 'Integration',
    featured: false,
    nodes: [
      { id: '1', type: 'slackTrigger', position: { x: 0, y: 0 }, data: { label: 'Slack Command', value: '' } },
      { id: '2', type: 'condition', position: { x: 220, y: 0 }, data: { label: 'Has Text?', condition: '$input.text.length > 0' } },
      { id: '3', type: 'llm', position: { x: 440, y: -80 }, data: { label: 'Process Command', model: 'gpt-4o', systemInstruction: 'Process the Slack command. Summarise, translate, or explain as requested. Be concise.' } },
      { id: '4', type: 'slack', position: { x: 660, y: -80 }, data: { label: 'Reply in Thread', channel: '$input.channel_id', message: '$output.result' } },
      { id: '5', type: 'output', position: { x: 880, y: 0 }, data: { label: 'Log', outputKey: 'result' } },
    ],
    edges: [
      { id: 'e1-2', source: '1', target: '2' },
      { id: 'e2-3', source: '2', target: '3', sourceHandle: 'true' },
      { id: 'e3-4', source: '3', target: '4' },
      { id: 'e4-5', source: '4', target: '5' },
      { id: 'e2-5', source: '2', target: '5', sourceHandle: 'false' },
    ],
  },
]

export function getAllTemplates(): StaticTemplate[] {
  return TEMPLATES
}

export function getTemplateBySlug(slug: string): StaticTemplate | undefined {
  return TEMPLATES.find((t) => t.slug === slug)
}

export function getFeaturedTemplates(): StaticTemplate[] {
  return TEMPLATES.filter((t) => t.featured)
}

export function getTemplatesByCategory(category: TemplateCategory | 'All'): StaticTemplate[] {
  if (category === 'All') return TEMPLATES
  return TEMPLATES.filter((t) => t.category === category)
}

export const TEMPLATE_CATEGORIES: Array<TemplateCategory | 'All'> = [
  'All', 'AI', 'Multi-Agent', 'Integration', 'Automation', 'Data',
]
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/lib/templates.ts
git commit -m "feat(templates): add static template data — 12 curated templates"
```

---

## Task 3: Create `TemplateCanvasNode.tsx`

**Files:**
- Create: `/Users/mbakgun/Projects/heym/heymweb/src/components/templates/TemplateCanvasNode.tsx`

This is the React Flow custom node component, equivalent to heymrun's `BaseNode.vue`.

- [ ] **Step 1: Create the file**

```tsx
'use client'

import {
  AlertTriangle, Ban, Bot, Brain, Braces, Bug, CalendarClock, Clock,
  Database, FileJson, GitBranch, GitMerge, Globe, HardDrive, Mail,
  MessageSquare, MonitorPlay, Play, Rabbit, Repeat, Search, Settings2,
  Sheet, Shuffle, StickyNote, Table2, Terminal, type LucideIcon, Type,
  Variable, XCircle,
} from 'lucide-react'
import { Handle, Position, type NodeProps } from '@xyflow/react'

const NODE_ICONS: Record<string, LucideIcon> = {
  textInput: Type,
  cron: CalendarClock,
  llm: Brain,
  agent: Bot,
  condition: GitBranch,
  switch: Shuffle,
  execute: Play,
  output: FileJson,
  wait: Clock,
  http: Globe,
  sticky: StickyNote,
  merge: GitMerge,
  set: Settings2,
  jsonOutputMapper: Braces,
  slack: MessageSquare,
  slackTrigger: MessageSquare,
  sendEmail: Mail,
  errorHandler: AlertTriangle,
  variable: Variable,
  loop: Repeat,
  disableNode: Ban,
  redis: Database,
  rag: Search,
  grist: Table2,
  googleSheets: Sheet,
  bigquery: Database,
  dataTable: Table2,
  throwError: XCircle,
  rabbitmq: Rabbit,
  crawler: Bug,
  consoleLog: Terminal,
  playwright: MonitorPlay,
  drive: HardDrive,
}

const NODE_COLORS: Record<string, string> = {
  textInput: '#6366f1',
  cron: '#f97316',
  llm: '#a855f7',
  agent: '#3b82f6',
  condition: '#eab308',
  switch: '#ec4899',
  execute: '#10b981',
  output: '#22c55e',
  wait: '#6b7280',
  http: '#06b6d4',
  sticky: '#f59e0b',
  merge: '#8b5cf6',
  set: '#64748b',
  jsonOutputMapper: '#22c55e',
  slack: '#36c37e',
  slackTrigger: '#36c37e',
  sendEmail: '#f472b6',
  errorHandler: '#ef4444',
  variable: '#84cc16',
  loop: '#14b8a6',
  disableNode: '#9ca3af',
  redis: '#ef4444',
  rag: '#8b5cf6',
  grist: '#3b82f6',
  googleSheets: '#22c55e',
  bigquery: '#4285f4',
  dataTable: '#0ea5e9',
  throwError: '#dc2626',
  rabbitmq: '#f97316',
  crawler: '#78716c',
  consoleLog: '#64748b',
  playwright: '#14b8a6',
  drive: '#4285f4',
}

type CanvasNodeData = {
  label: string
  nodeType: string
  [key: string]: unknown
}

export function TemplateCanvasNode({ data, selected }: NodeProps) {
  const nodeData = data as CanvasNodeData
  const color = NODE_COLORS[nodeData.nodeType] ?? '#6b7280'
  const Icon = NODE_ICONS[nodeData.nodeType] ?? Brain

  return (
    <div
      style={{
        background: 'hsl(222 47% 14%)',
        border: `1px solid ${selected ? color : 'hsl(222 47% 22%)'}`,
        borderLeft: `3px solid ${color}`,
        borderRadius: 10,
        minWidth: 140,
        maxWidth: 180,
        boxShadow: selected ? `0 0 0 2px ${color}33` : undefined,
        cursor: 'pointer',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: color, width: 8, height: 8 }} />
      <div style={{ padding: '8px 10px', display: 'flex', alignItems: 'center', gap: 7 }}>
        <div style={{ width: 24, height: 24, borderRadius: 6, background: `${color}22`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
          <Icon size={13} style={{ color }} />
        </div>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'hsl(0 0% 90%)', lineHeight: 1.3, wordBreak: 'break-word' }}>
          {nodeData.label}
        </span>
      </div>
      <Handle type="source" position={Position.Right} style={{ background: color, width: 8, height: 8 }} />
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/components/templates/TemplateCanvasNode.tsx
git commit -m "feat(templates): add TemplateCanvasNode React Flow custom node"
```

---

## Task 4: Create `TemplatePreviewContent.tsx`

**Files:**
- Create: `/Users/mbakgun/Projects/heym/heymweb/src/components/templates/TemplatePreviewContent.tsx`

This is the canvas + right sidebar + import actions — reused inside both the modal and the detail page.

- [ ] **Step 1: Create the file**

```tsx
'use client'

import { useCallback, useState } from 'react'
import ReactFlow, { Background, Controls, type Node, type Edge, useNodesState, useEdgesState, fitView } from '@xyflow/react'
import { Check, ChevronDown, Copy, Download, X } from 'lucide-react'
import '@xyflow/react/dist/style.css'

import { TemplateCanvasNode } from './TemplateCanvasNode'
import type { StaticTemplate } from '@/lib/templates'

const nodeTypes = { templateNode: TemplateCanvasNode }

function toFlowNodes(template: StaticTemplate): Node[] {
  return template.nodes.map((n) => ({
    id: n.id,
    type: 'templateNode',
    position: n.position,
    data: { ...n.data, nodeType: n.type, label: n.data.label },
  }))
}

function toFlowEdges(template: StaticTemplate): Edge[] {
  return template.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: e.sourceHandle,
    targetHandle: e.targetHandle,
    animated: true,
    style: { stroke: '#4b5563' },
  }))
}

interface SelectedNodeInfo {
  id: string
  label: string
  nodeType: string
  fields: Array<{ key: string; value: string }>
}

const SKIP_KEYS = new Set(['label', 'nodeType', 'nodeId', 'active', 'status', 'tools', 'mcpConnections', 'skills'])

function extractFields(data: Record<string, unknown>): Array<{ key: string; value: string }> {
  return Object.entries(data)
    .filter(([k, v]) => !SKIP_KEYS.has(k) && v !== null && v !== undefined && v !== '' && typeof v !== 'object')
    .map(([k, v]) => ({ key: k, value: String(v) }))
    .slice(0, 8)
}

interface Props {
  template: StaticTemplate
}

export function TemplatePreviewContent({ template }: Props) {
  const [nodes, , onNodesChange] = useNodesState(toFlowNodes(template))
  const [edges, , onEdgesChange] = useEdgesState(toFlowEdges(template))
  const [selectedNode, setSelectedNode] = useState<SelectedNodeInfo | null>(null)
  const [copied, setCopied] = useState(false)
  const [importOpen, setImportOpen] = useState(false)

  const handleNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    const data = node.data as Record<string, unknown>
    setSelectedNode({
      id: node.id,
      label: String(data.label ?? node.id),
      nodeType: String(data.nodeType ?? ''),
      fields: extractFields(data),
    })
  }, [])

  const handlePaneClick = useCallback(() => setSelectedNode(null), [])

  async function handleCopy() {
    await navigator.clipboard.writeText(
      JSON.stringify({ nodes: template.nodes, edges: template.edges })
    )
    setCopied(true)
    setImportOpen(false)
    setTimeout(() => setCopied(false), 2000)
  }

  function handleDownload() {
    const blob = new Blob(
      [JSON.stringify({ nodes: template.nodes, edges: template.edges }, null, 2)],
      { type: 'application/json' }
    )
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${template.slug}.json`
    a.click()
    URL.revokeObjectURL(url)
    setImportOpen(false)
  }

  return (
    <div className="flex flex-col h-full gap-3">
      {/* Tags */}
      {template.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 shrink-0">
          {template.tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-xs text-primary"
            >
              #{tag}
            </span>
          ))}
        </div>
      )}

      <p className="text-xs text-muted-foreground shrink-0">
        Click a node to inspect its configuration.
      </p>

      {/* Canvas + optional right panel */}
      <div className="flex min-h-0 flex-1 gap-3">
        <div className="min-h-0 flex-1 rounded-xl border border-border/40 overflow-hidden" style={{ background: 'hsl(224 34% 10%)' }}>
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onNodeClick={handleNodeClick}
            onPaneClick={handlePaneClick}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            fitView
            fitViewOptions={{ padding: template.nodes.length <= 1 ? 0.9 : 0.22 }}
            minZoom={0.1}
            maxZoom={1.5}
          >
            <Background color="hsl(0 0% 50% / 0.1)" gap={20} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>

        {selectedNode && (
          <div className="flex h-full w-64 shrink-0 flex-col overflow-hidden rounded-xl border border-border/50 bg-card shadow-sm">
            <div className="shrink-0 border-b border-border/40 px-4 py-3 flex items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-foreground">{selectedNode.label}</p>
                <p className="text-xs text-muted-foreground mt-0.5">{selectedNode.nodeType}</p>
              </div>
              <button
                onClick={() => setSelectedNode(null)}
                className="shrink-0 text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3">
              {selectedNode.fields.length > 0 ? (
                selectedNode.fields.map((f) => (
                  <div key={f.key} className="space-y-1">
                    <p className="text-xs font-medium text-muted-foreground capitalize">{f.key.replace(/([A-Z])/g, ' $1').trim()}</p>
                    <div className="w-full rounded-lg border border-input bg-background/60 px-3 py-2 text-xs text-foreground truncate">
                      {f.value}
                    </div>
                  </div>
                ))
              ) : (
                <p className="text-xs text-muted-foreground py-4 text-center">No displayable fields</p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Import actions */}
      <div className="flex items-center justify-end gap-3 shrink-0 pt-1">
        <div className="relative">
          <button
            onClick={() => setImportOpen((v) => !v)}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Import
            <ChevronDown className="h-3.5 w-3.5" />
          </button>
          {importOpen && (
            <>
              <div className="fixed inset-0 z-10" onClick={() => setImportOpen(false)} />
              <div className="absolute right-0 bottom-full mb-1 z-20 w-44 rounded-lg border border-border bg-popover shadow-lg overflow-hidden">
                <button
                  onClick={handleDownload}
                  className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm hover:bg-muted/60 transition-colors"
                >
                  <Download className="h-4 w-4 text-muted-foreground" />
                  Download .json
                </button>
                <button
                  onClick={handleCopy}
                  className="flex w-full items-center gap-2.5 px-3 py-2.5 text-sm hover:bg-muted/60 transition-colors"
                >
                  {copied ? (
                    <Check className="h-4 w-4 text-green-500" />
                  ) : (
                    <Copy className="h-4 w-4 text-muted-foreground" />
                  )}
                  {copied ? 'Copied!' : 'Copy JSON'}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/components/templates/TemplatePreviewContent.tsx
git commit -m "feat(templates): add TemplatePreviewContent with React Flow canvas and import actions"
```

---

## Task 5: Create `TemplatePreviewModal.tsx`

**Files:**
- Create: `/Users/mbakgun/Projects/heym/heymweb/src/components/templates/TemplatePreviewModal.tsx`

Wraps `TemplatePreviewContent` in the same full-screen modal style as heymrun's CanvasPreviewModal.

- [ ] **Step 1: Create the file**

```tsx
'use client'

import { useEffect } from 'react'
import { X } from 'lucide-react'
import type { StaticTemplate } from '@/lib/templates'
import { TemplatePreviewContent } from './TemplatePreviewContent'

interface Props {
  template: StaticTemplate
  onClose: () => void
}

export function TemplatePreviewModal({ template, onClose }: Props) {
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative flex h-[82vh] max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-border/50 bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-4 border-b border-border/40 p-6 shrink-0">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-lg font-semibold text-foreground">{template.name}</h2>
            {template.description && (
              <p className="mt-1 text-sm text-muted-foreground">{template.description}</p>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
              <span>{template.nodes.length} nodes</span>
              <span className="capitalize">{template.category}</span>
            </div>
          </div>
          <button
            className="shrink-0 text-muted-foreground transition-colors hover:text-foreground"
            onClick={onClose}
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex min-h-0 flex-1 flex-col gap-4 px-6 py-4">
          <TemplatePreviewContent template={template} />
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/components/templates/TemplatePreviewModal.tsx
git commit -m "feat(templates): add TemplatePreviewModal"
```

---

## Task 6: Create `TemplateCard.tsx`

**Files:**
- Create: `/Users/mbakgun/Projects/heym/heymweb/src/components/templates/TemplateCard.tsx`

Grid card matching heymrun TemplateCard visual style (mini canvas thumbnail + name + tags + action buttons).

- [ ] **Step 1: Create the file**

```tsx
'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ChevronDown, Copy, Download, Eye } from 'lucide-react'
import type { StaticTemplate } from '@/lib/templates'
import { TemplatePreviewModal } from './TemplatePreviewModal'

const CATEGORY_COLORS: Record<string, string> = {
  AI: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  'Multi-Agent': 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  Integration: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
  Automation: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  Data: 'bg-green-500/10 text-green-400 border-green-500/20',
}

interface Props {
  template: StaticTemplate
}

export function TemplateCard({ template }: Props) {
  const [showModal, setShowModal] = useState(false)
  const [importOpen, setImportOpen] = useState(false)
  const [copied, setCopied] = useState(false)

  async function handleCopy(e: React.MouseEvent) {
    e.preventDefault()
    await navigator.clipboard.writeText(
      JSON.stringify({ nodes: template.nodes, edges: template.edges })
    )
    setCopied(true)
    setImportOpen(false)
    setTimeout(() => setCopied(false), 2000)
  }

  function handleDownload(e: React.MouseEvent) {
    e.preventDefault()
    const blob = new Blob(
      [JSON.stringify({ nodes: template.nodes, edges: template.edges }, null, 2)],
      { type: 'application/json' }
    )
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${template.slug}.json`
    a.click()
    URL.revokeObjectURL(url)
    setImportOpen(false)
  }

  const categoryClass = CATEGORY_COLORS[template.category] ?? 'bg-muted text-muted-foreground border-border'

  return (
    <>
      <div className="group relative flex flex-col rounded-2xl border border-border/40 bg-card/80 shadow-sm hover:shadow-md hover:border-primary/30 transition-all duration-200 overflow-hidden">
        {/* Mini canvas area — static dark bg with node type badges */}
        <div className="h-28 border-b border-border/30 bg-[hsl(224_34%_10%)] flex items-center justify-center p-3 gap-1.5 flex-wrap">
          {template.nodes.slice(0, 6).map((n) => (
            <span
              key={n.id}
              className="px-2 py-0.5 rounded-md text-[10px] font-medium border"
              style={{
                background: 'hsl(222 47% 18%)',
                borderColor: 'hsl(222 47% 28%)',
                color: 'hsl(0 0% 75%)',
              }}
            >
              {n.type}
            </span>
          ))}
          {template.nodes.length > 6 && (
            <span className="text-[10px] text-muted-foreground">+{template.nodes.length - 6}</span>
          )}
        </div>

        {/* Card body */}
        <div className="flex flex-col gap-2 p-4 flex-1">
          <div className="flex items-start justify-between gap-2">
            <Link href={`/templates/${template.slug}`} className="hover:underline">
              <h3 className="text-sm font-semibold text-foreground leading-snug">{template.name}</h3>
            </Link>
            <span className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded border font-medium ${categoryClass}`}>
              {template.category}
            </span>
          </div>

          {template.description && (
            <p className="text-xs text-muted-foreground line-clamp-2">{template.description}</p>
          )}

          <div className="flex flex-wrap gap-1 mt-auto pt-1">
            {template.tags.slice(0, 3).map((tag) => (
              <span key={tag} className="px-1.5 py-0.5 rounded text-[10px] bg-primary/8 text-primary/80 border border-primary/15">
                #{tag}
              </span>
            ))}
          </div>

          <div className="flex items-center gap-2 pt-1">
            <button
              onClick={() => setShowModal(true)}
              className="flex items-center gap-1.5 flex-1 justify-center rounded-lg border border-border/50 px-3 py-1.5 text-xs hover:bg-muted/60 transition-colors"
            >
              <Eye className="h-3 w-3" />
              Preview
            </button>

            <div className="relative">
              <button
                onClick={() => setImportOpen((v) => !v)}
                className="flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90 transition-colors"
              >
                Import
                <ChevronDown className="h-3 w-3" />
              </button>
              {importOpen && (
                <>
                  <div className="fixed inset-0 z-10" onClick={() => setImportOpen(false)} />
                  <div className="absolute right-0 bottom-full mb-1 z-20 w-40 rounded-lg border border-border bg-popover shadow-lg overflow-hidden">
                    <button
                      onClick={handleDownload}
                      className="flex w-full items-center gap-2 px-3 py-2.5 text-xs hover:bg-muted/60 transition-colors"
                    >
                      <Download className="h-3.5 w-3.5 text-muted-foreground" />
                      Download .json
                    </button>
                    <button
                      onClick={handleCopy}
                      className="flex w-full items-center gap-2 px-3 py-2.5 text-xs hover:bg-muted/60 transition-colors"
                    >
                      <Copy className="h-3.5 w-3.5 text-muted-foreground" />
                      {copied ? 'Copied!' : 'Copy JSON'}
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {showModal && <TemplatePreviewModal template={template} onClose={() => setShowModal(false)} />}
    </>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/components/templates/TemplateCard.tsx
git commit -m "feat(templates): add TemplateCard component"
```

---

## Task 7: Create `TemplatesPageClient.tsx`

**Files:**
- Create: `/Users/mbakgun/Projects/heym/heymweb/src/components/templates/TemplatesPageClient.tsx`

Category tab filter + template grid. The server page passes all templates; this client component handles filtering.

- [ ] **Step 1: Create the file**

```tsx
'use client'

import { useState } from 'react'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TemplateCard } from './TemplateCard'
import type { StaticTemplate, TemplateCategory } from '@/lib/templates'
import { TEMPLATE_CATEGORIES } from '@/lib/templates'

interface Props {
  templates: StaticTemplate[]
}

export function TemplatesPageClient({ templates }: Props) {
  const [active, setActive] = useState<TemplateCategory | 'All'>('All')

  const filtered = active === 'All'
    ? templates
    : templates.filter((t) => t.category === active)

  return (
    <div className="flex flex-col gap-8">
      <Tabs value={active} onValueChange={(v) => setActive(v as TemplateCategory | 'All')}>
        <TabsList className="h-auto flex-wrap gap-1 bg-muted/40 p-1">
          {TEMPLATE_CATEGORIES.map((cat) => (
            <TabsTrigger key={cat} value={cat} className="text-sm">
              {cat}
              <span className="ml-1.5 text-xs text-muted-foreground">
                ({cat === 'All' ? templates.length : templates.filter((t) => t.category === cat).length})
              </span>
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {filtered.length === 0 ? (
        <div className="py-20 text-center text-muted-foreground text-sm">
          No templates in this category yet.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {filtered.map((t) => (
            <TemplateCard key={t.slug} template={t} />
          ))}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/components/templates/TemplatesPageClient.tsx
git commit -m "feat(templates): add TemplatesPageClient with category filter"
```

---

## Task 8: Create `/templates` listing page

**Files:**
- Create: `/Users/mbakgun/Projects/heym/heymweb/src/app/templates/page.tsx`

- [ ] **Step 1: Create the file**

```tsx
import type { Metadata } from 'next'
import Link from 'next/link'
import { ArrowLeft, LayoutTemplate } from 'lucide-react'
import { getAllTemplates } from '@/lib/templates'
import { TemplatesPageClient } from '@/components/templates/TemplatesPageClient'
import { SITE_NAME, SITE_URL } from '@/lib/site'

const title = `Workflow Templates — ${SITE_NAME}`
const description =
  'Browse ready-made AI workflow templates for email triage, RAG Q&A, multi-agent research, Slack integration, and more. Download or copy and paste directly into Heym.'

const itemListJsonLd = {
  '@context': 'https://schema.org',
  '@type': 'ItemList',
  name: 'Heym Workflow Templates',
  description,
  url: `${SITE_URL}/templates`,
  itemListElement: getAllTemplates().map((t, i) => ({
    '@type': 'ListItem',
    position: i + 1,
    name: t.name,
    url: `${SITE_URL}/templates/${t.slug}`,
    description: t.description,
  })),
}

const breadcrumbJsonLd = {
  '@context': 'https://schema.org',
  '@type': 'BreadcrumbList',
  itemListElement: [
    { '@type': 'ListItem', position: 1, name: 'Home', item: SITE_URL },
    { '@type': 'ListItem', position: 2, name: 'Templates', item: `${SITE_URL}/templates` },
  ],
}

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: '/templates' },
  openGraph: {
    type: 'website',
    locale: 'en_US',
    url: `${SITE_URL}/templates`,
    title,
    description,
    siteName: SITE_NAME,
  },
  twitter: { card: 'summary_large_image', title, description },
}

export default function TemplatesPage(): React.JSX.Element {
  const templates = getAllTemplates()

  return (
    <div className="min-h-screen pt-24 pb-16">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(itemListJsonLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbJsonLd) }} />

      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="mb-10">
          <Link
            href="/"
            className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors mb-6"
          >
            <ArrowLeft className="h-4 w-4" />
            Back to home
          </Link>

          <div className="inline-flex items-center px-4 py-2 rounded-full bg-primary/10 border border-primary/20 mb-4">
            <LayoutTemplate className="w-4 h-4 text-primary mr-2" />
            <span className="text-sm font-medium text-primary">Workflow Templates</span>
          </div>

          <h1 className="text-4xl md:text-5xl font-bold text-foreground tracking-tight">
            Ready-made <span className="text-gradient">Workflows</span>
          </h1>
          <p className="mt-4 text-lg text-muted-foreground max-w-2xl">
            {description}
          </p>
        </div>

        <TemplatesPageClient templates={templates} />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Build check**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npm run build 2>&1 | tail -20
```

Expected: build succeeds, `/templates` page generated.

- [ ] **Step 4: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/app/templates/page.tsx
git commit -m "feat(templates): add /templates listing page with SEO"
```

---

## Task 9: Create `/templates/[slug]` detail page

**Files:**
- Create: `/Users/mbakgun/Projects/heym/heymweb/src/app/templates/[slug]/page.tsx`

- [ ] **Step 1: Create the file**

```tsx
import type { Metadata } from 'next'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import { compileMDX } from 'next-mdx-remote/rsc'
import remarkGfm from 'remark-gfm'

import { getAllTemplates, getTemplateBySlug } from '@/lib/templates'
import { TemplatePreviewContent } from '@/components/templates/TemplatePreviewContent'
import { SITE_NAME, SITE_URL } from '@/lib/site'

interface Props {
  params: Promise<{ slug: string }>
}

export async function generateStaticParams(): Promise<{ slug: string }[]> {
  return getAllTemplates().map((t) => ({ slug: t.slug }))
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params
  const template = getTemplateBySlug(slug)
  if (!template) return {}

  const title = `${template.name} — Heym Template`
  const description = template.description

  return {
    title,
    description,
    alternates: { canonical: `/templates/${slug}` },
    openGraph: {
      type: 'website',
      locale: 'en_US',
      url: `${SITE_URL}/templates/${slug}`,
      title,
      description,
      siteName: SITE_NAME,
    },
    twitter: { card: 'summary_large_image', title, description },
  }
}

export default async function TemplateDetailPage({ params }: Props): Promise<React.JSX.Element> {
  const { slug } = await params
  const template = getTemplateBySlug(slug)
  if (!template) notFound()

  const { content } = await compileMDX({
    source: template.longDescription,
    options: { mdxOptions: { remarkPlugins: [remarkGfm] } },
  })

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'SoftwareApplication',
    name: template.name,
    description: template.description,
    url: `${SITE_URL}/templates/${template.slug}`,
    applicationCategory: 'BusinessApplication',
    operatingSystem: 'Web',
    offers: { '@type': 'Offer', price: '0', priceCurrency: 'USD' },
    keywords: template.tags.join(', '),
  }

  const breadcrumbJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: SITE_URL },
      { '@type': 'ListItem', position: 2, name: 'Templates', item: `${SITE_URL}/templates` },
      { '@type': 'ListItem', position: 3, name: template.name, item: `${SITE_URL}/templates/${template.slug}` },
    ],
  }

  return (
    <div className="min-h-screen pt-24 pb-16">
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumbJsonLd) }} />

      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        {/* Breadcrumb */}
        <div className="flex items-center gap-2 text-sm text-muted-foreground mb-8">
          <Link href="/" className="hover:text-foreground transition-colors">Home</Link>
          <span>/</span>
          <Link href="/templates" className="hover:text-foreground transition-colors">Templates</Link>
          <span>/</span>
          <span className="text-foreground">{template.name}</span>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_400px] gap-10">
          {/* Left: description */}
          <div>
            <div className="flex flex-wrap gap-1.5 mb-4">
              <span className="text-xs px-2 py-0.5 rounded border bg-primary/10 text-primary border-primary/20">
                {template.category}
              </span>
              {template.tags.map((tag) => (
                <span key={tag} className="text-xs px-2 py-0.5 rounded border bg-muted text-muted-foreground border-border/50">
                  #{tag}
                </span>
              ))}
            </div>

            <h1 className="text-3xl md:text-4xl font-bold text-foreground mb-3">{template.name}</h1>
            <p className="text-lg text-muted-foreground mb-8">{template.description}</p>

            <div className="prose prose-invert prose-sm max-w-none">
              {content}
            </div>

            <div className="mt-8 pt-8 border-t border-border/50">
              <p className="text-sm text-muted-foreground mb-1">
                <strong className="text-foreground">{template.nodes.length}</strong> nodes
              </p>
              <Link
                href="/templates"
                className="inline-flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors mt-4"
              >
                <ArrowLeft className="h-4 w-4" />
                All templates
              </Link>
            </div>
          </div>

          {/* Right: interactive canvas */}
          <div className="flex flex-col gap-4">
            <div className="h-[520px] rounded-2xl border border-border/40 overflow-hidden">
              <TemplatePreviewContent template={template} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npx tsc --noEmit 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Build check**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npm run build 2>&1 | tail -20
```

Expected: all 12 template slug pages generated statically.

- [ ] **Step 4: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/app/templates/[slug]/page.tsx
git commit -m "feat(templates): add /templates/[slug] detail page with SEO and canvas"
```

---

## Task 10: Create `TemplatesSection.tsx` (homepage)

**Files:**
- Create: `/Users/mbakgun/Projects/heym/heymweb/src/components/sections/TemplatesSection.tsx`

- [ ] **Step 1: Create the file**

```tsx
import Link from 'next/link'
import { ArrowRight, LayoutTemplate } from 'lucide-react'
import { getFeaturedTemplates } from '@/lib/templates'

const CATEGORY_COLORS: Record<string, string> = {
  AI: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  'Multi-Agent': 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  Integration: 'bg-cyan-500/10 text-cyan-400 border-cyan-500/20',
  Automation: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  Data: 'bg-green-500/10 text-green-400 border-green-500/20',
}

export function TemplatesSection(): React.JSX.Element {
  const featured = getFeaturedTemplates()

  return (
    <section className="py-20 border-t border-border/50" id="templates">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex items-end justify-between mb-10">
          <div>
            <div className="inline-flex items-center px-4 py-2 rounded-full bg-primary/10 border border-primary/20 mb-4">
              <LayoutTemplate className="w-4 h-4 text-primary mr-2" />
              <span className="text-sm font-medium text-primary">Templates</span>
            </div>
            <h2 className="text-3xl md:text-4xl font-bold tracking-tight">
              Start with a <span className="text-gradient">template</span>
            </h2>
            <p className="text-muted-foreground mt-3 max-w-xl">
              Ready-made workflows for common AI automation patterns. Download, paste onto the canvas, and run in minutes.
            </p>
          </div>
          <Link
            href="/templates"
            className="hidden md:inline-flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors shrink-0"
          >
            Browse all templates
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>

        <div className="grid gap-6 md:grid-cols-3">
          {featured.map((t) => {
            const catClass = CATEGORY_COLORS[t.category] ?? 'bg-muted text-muted-foreground border-border'
            return (
              <Link
                key={t.slug}
                href={`/templates/${t.slug}`}
                className="group block rounded-xl border border-border/50 bg-card p-6 hover:border-primary/30 hover:shadow-md hover:shadow-primary/5 transition-all"
              >
                <div className="flex items-start justify-between gap-2 mb-3">
                  <span className={`text-xs px-2 py-0.5 rounded border font-medium ${catClass}`}>
                    {t.category}
                  </span>
                  <span className="text-xs text-muted-foreground">{t.nodes.length} nodes</span>
                </div>
                <h3 className="text-base font-semibold text-foreground group-hover:text-foreground/80 transition-colors mb-2">
                  {t.name}
                </h3>
                <p className="text-sm text-muted-foreground line-clamp-2 mb-4">{t.description}</p>
                <div className="flex flex-wrap gap-1.5">
                  {t.tags.slice(0, 3).map((tag) => (
                    <span key={tag} className="text-xs px-2 py-0.5 rounded-full bg-primary/10 text-primary/80 font-medium">
                      #{tag}
                    </span>
                  ))}
                </div>
              </Link>
            )
          })}
        </div>

        <div className="mt-8 text-center md:hidden">
          <Link
            href="/templates"
            className="inline-flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
          >
            Browse all templates <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </div>
    </section>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/components/sections/TemplatesSection.tsx
git commit -m "feat(templates): add TemplatesSection homepage component"
```

---

## Task 11: Update Navbar, Footer, homepage, and sitemap (heymweb)

**Files:**
- Modify: `src/components/sections/Navbar.tsx`
- Modify: `src/components/sections/Footer.tsx`
- Modify: `src/app/page.tsx`
- Modify: `src/lib/site.ts`
- Modify: `src/app/sitemap.ts`

- [ ] **Step 1: Update Navbar — add Templates to navigation array**

In `/Users/mbakgun/Projects/heym/heymweb/src/components/sections/Navbar.tsx`, change:

```typescript
  const navigation = [
    { name: 'Features', href: '/#features' },
    { name: 'Nodes', href: '/#nodes' },
    { name: 'Use Cases', href: '/#use-cases' },
    { name: 'Enterprise', href: '/#enterprise' },
    { name: 'Community', href: '/#community' },
  ]
```

To:

```typescript
  const navigation = [
    { name: 'Features', href: '/#features' },
    { name: 'Templates', href: '/templates' },
    { name: 'Nodes', href: '/#nodes' },
    { name: 'Use Cases', href: '/#use-cases' },
    { name: 'Enterprise', href: '/#enterprise' },
    { name: 'Community', href: '/#community' },
  ]
```

- [ ] **Step 2: Update Footer — add Templates to product links**

In `/Users/mbakgun/Projects/heym/heymweb/src/components/sections/Footer.tsx`, change:

```typescript
  product: [
    { name: 'Home', href: '/' },
    { name: 'Features', href: '/#features' },
    { name: 'Nodes', href: '/#nodes' },
    { name: 'Use Cases', href: '/#use-cases' },
    { name: 'Screenshots', href: '/#screenshots' },
  ],
```

To:

```typescript
  product: [
    { name: 'Home', href: '/' },
    { name: 'Features', href: '/#features' },
    { name: 'Templates', href: '/templates' },
    { name: 'Nodes', href: '/#nodes' },
    { name: 'Use Cases', href: '/#use-cases' },
    { name: 'Screenshots', href: '/#screenshots' },
  ],
```

- [ ] **Step 3: Update homepage — add TemplatesSection before LatestBlogSection**

In `/Users/mbakgun/Projects/heym/heymweb/src/app/page.tsx`, add the import and component:

```typescript
import { TemplatesSection } from '@/components/sections/TemplatesSection'
```

Insert `<TemplatesSection />` and a `<WaveSeparator>` immediately before `<LatestBlogSection />`:

```tsx
      <WaveSeparator variant={1} flip />
      <TemplatesSection />
      <LatestBlogSection />
```

(Replace the existing line `<LatestBlogSection />` with those three lines.)

- [ ] **Step 4: Update site.ts — add /templates to STATIC_ROUTES**

In `/Users/mbakgun/Projects/heym/heymweb/src/lib/site.ts`, add to the `STATIC_ROUTES` array:

```typescript
  {
    path: '/templates',
    lastModified: '2026-04-18',
    changeFrequency: 'weekly',
    priority: 0.85,
  },
```

- [ ] **Step 5: Update sitemap.ts — add template slug routes**

In `/Users/mbakgun/Projects/heym/heymweb/src/app/sitemap.ts`, add template routes:

```typescript
import type { MetadataRoute } from 'next'

import { SITE_URL, STATIC_ROUTES } from '@/lib/site'
import { getAllPosts } from '@/lib/blog'
import { getAllTemplates } from '@/lib/templates'

export default function sitemap(): MetadataRoute.Sitemap {
  const staticRoutes = STATIC_ROUTES.map((route) => ({
    url: `${SITE_URL}${route.path}`,
    lastModified: new Date(route.lastModified),
    changeFrequency: route.changeFrequency,
    priority: route.priority,
  }))

  const blogRoutes = getAllPosts().map((post) => ({
    url: `${SITE_URL}/blog/${post.slug}`,
    lastModified: new Date(post.date),
    changeFrequency: 'weekly' as const,
    priority: 0.8,
  }))

  const templateRoutes = getAllTemplates().map((t) => ({
    url: `${SITE_URL}/templates/${t.slug}`,
    lastModified: new Date('2026-04-18'),
    changeFrequency: 'monthly' as const,
    priority: 0.75,
  }))

  return [...staticRoutes, ...blogRoutes, ...templateRoutes]
}
```

- [ ] **Step 6: Type-check and build**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npx tsc --noEmit 2>&1 | head -20 && npm run build 2>&1 | tail -20
```

Expected: no type errors, build succeeds.

- [ ] **Step 7: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/components/sections/Navbar.tsx src/components/sections/Footer.tsx \
  src/app/page.tsx src/lib/site.ts src/app/sitemap.ts
git commit -m "feat(templates): add Templates to nav, footer, homepage, and sitemap"
```

---

## Task 12: Create `TemplatesBrowseDialog.vue` (heymrun)

**Files:**
- Create: `/Users/mbakgun/Projects/heym/heymrun/frontend/src/features/templates/components/TemplatesBrowseDialog.vue`

- [ ] **Step 1: Create the file**

```vue
<script setup lang="ts">
import { ref } from "vue";
import { Globe, X } from "lucide-vue-next";

interface Props {
  open: boolean;
}

defineProps<Props>();
const emit = defineEmits<{ close: [] }>();

const iframeLoaded = ref(false);

function handleLoad(): void {
  iframeLoaded.value = true;
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex flex-col bg-background"
    >
      <!-- Header -->
      <div class="flex items-center justify-between gap-4 border-b border-border/40 px-6 py-4 shrink-0">
        <div class="flex items-center gap-2.5">
          <Globe class="h-5 w-5 text-primary" />
          <h2 class="text-base font-semibold text-foreground">Browse Public Templates</h2>
        </div>
        <button
          class="text-muted-foreground transition-colors hover:text-foreground"
          type="button"
          @click="emit('close')"
        >
          <X class="h-5 w-5" />
        </button>
      </div>

      <!-- Loading spinner -->
      <div
        v-if="!iframeLoaded"
        class="flex flex-1 items-center justify-center"
      >
        <div class="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>

      <!-- Iframe -->
      <iframe
        src="https://heym.run/templates"
        class="flex-1 border-0"
        :class="iframeLoaded ? 'opacity-100' : 'opacity-0 absolute'"
        title="Heym Public Templates"
        @load="handleLoad"
      />
    </div>
  </Teleport>
</template>
```

- [ ] **Step 2: Type-check**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && bun run typecheck 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
git add frontend/src/features/templates/components/TemplatesBrowseDialog.vue
git commit -m "feat(templates): add TemplatesBrowseDialog iframe component"
```

---

## Task 13: Update `TemplatesPage.vue` — add Browse button (heymrun)

**Files:**
- Modify: `/Users/mbakgun/Projects/heym/heymrun/frontend/src/features/templates/components/TemplatesPage.vue`

- [ ] **Step 1: Add import and dialog ref**

In the `<script setup>` block, add the import and state:

```typescript
import { ref } from "vue";  // already imported, ensure ref is included
import TemplatesBrowseDialog from "./TemplatesBrowseDialog.vue";
```

And add inside the script setup (after existing imports):

```typescript
const showBrowseDialog = ref(false);
```

The existing `ref` import from Vue is already there for `activeKind`, `previewTemplate`, etc. — just add `showBrowseDialog` and the component import.

- [ ] **Step 2: Add Globe import to lucide imports**

The existing line `import { LayoutTemplate } from "lucide-vue-next";` should become:

```typescript
import { Globe, LayoutTemplate } from "lucide-vue-next";
```

- [ ] **Step 3: Add "Browse Public Templates" button to the top bar**

In the `<template>`, find the top bar `<div class="flex flex-col sm:flex-row sm:items-center gap-4">`. After the `<TemplateSearchBar .../>` component, add:

```html
      <button
        class="flex items-center gap-2 rounded-xl border border-border/40 bg-card/60 px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground hover:bg-card shrink-0"
        type="button"
        @click="showBrowseDialog = true"
      >
        <Globe class="h-4 w-4" />
        Browse Public Templates
      </button>
```

- [ ] **Step 4: Add dialog at bottom of template**

Inside `<template>`, after the last closing tag of `<EditTemplateModal .../>`, add:

```html
    <!-- Browse public templates dialog -->
    <TemplatesBrowseDialog
      :open="showBrowseDialog"
      @close="showBrowseDialog = false"
    />
```

- [ ] **Step 5: Type-check**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && bun run typecheck 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 6: Lint check**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && bun run lint 2>&1 | head -20
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
git add frontend/src/features/templates/components/TemplatesPage.vue
git commit -m "feat(templates): add Browse Public Templates button to TemplatesPage"
```

---

## Task 14: Final validation

- [ ] **Step 1: Full heymweb build**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && npm run build 2>&1 | tail -30
```

Expected: build succeeds with 12 template slugs pre-rendered.

- [ ] **Step 2: heymrun lint + typecheck**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && bun run lint && bun run typecheck
```

Expected: both pass with no errors.

- [ ] **Step 3: Verify sitemap includes templates**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && node -e "
const { default: s } = require('./.next/server/app/sitemap.js');
s().then(r => r.filter(x => x.url.includes('/templates')).forEach(x => console.log(x.url)));
" 2>/dev/null || echo "Check .next/server/app/sitemap after build"
```

- [ ] **Step 4: Final commit**

```bash
cd /Users/mbakgun/Projects/heym/heymrun
git add .
git status
```

Confirm only intended files are staged, then commit any remaining uncommitted changes.

---

## Self-Review Checklist

### Spec coverage

| Spec requirement | Task |
|---|---|
| Static curated templates (heymweb) | Task 2 |
| React Flow canvas preview (same UX) | Tasks 3, 4, 5 |
| Import: Download .json + Copy JSON | Tasks 4, 6 |
| /templates listing page + category tabs | Tasks 7, 8 |
| /templates/[slug] detail pages | Task 9 |
| TemplatesSection on homepage | Task 10 |
| Navbar + Footer + sitemap | Task 11 |
| TemplatesBrowseDialog (iframe) | Task 12 |
| Browse button in TemplatesPage.vue | Task 13 |
| JSON-LD ItemList on listing page | Task 8 |
| JSON-LD SoftwareApplication on detail | Task 9 |

All spec requirements covered. ✅
