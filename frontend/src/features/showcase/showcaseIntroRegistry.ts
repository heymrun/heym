import type { ShowcaseContext } from "@/features/showcase/showcase.types";

export interface ShowcaseIntroContent {
  title: string;
  description: string;
}

export const SHOWCASE_INTRO_VIDEO_BY_CONTEXT: Record<ShowcaseContext, string> = {
  "dashboard:workflows": "/features/showcase/workflows.webm",
  "dashboard:templates": "/features/showcase/templates.webm",
  "dashboard:globalvariables": "/features/showcase/globalvariables.webm",
  "dashboard:chat": "/features/showcase/chat.webm",
  "dashboard:drive": "/features/showcase/drive.webm",
  "dashboard:datatable": "/features/showcase/datatable.webm",
  "dashboard:schedules": "/features/showcase/scheduled.webm",
  "dashboard:credentials": "/features/showcase/credentials.webm",
  "dashboard:vectorstores": "/features/showcase/vectorstores.webm",
  "dashboard:mcp": "/features/showcase/mcp.webm",
  "dashboard:traces": "/features/showcase/traces.webm",
  "dashboard:analytics": "/features/showcase/analytics.webm",
  evals: "/features/showcase/evals.webm",
  "dashboard:teams": "/features/showcase/teams.webm",
  "dashboard:logs": "/features/showcase/logs.mp4",
  docs: "/features/showcase/docs.webm",
  editor: "/features/showcase/editor.webm",
};

export const SHOWCASE_INTRO_CONTENT_BY_CONTEXT: Record<ShowcaseContext, ShowcaseIntroContent> = {
  "dashboard:workflows": {
    title: "Build faster in Workflows",
    description: "Create, organize, and reopen workflows from one place. Use folders and quick actions to keep production automations clean.",
  },
  "dashboard:templates": {
    title: "Start from proven templates",
    description: "Use ready-made workflow patterns to reduce setup time and keep team implementations consistent.",
  },
  "dashboard:globalvariables": {
    title: "Centralize shared values",
    description: "Store reusable values once and reference them across workflows to avoid duplicated configuration drift.",
  },
  "dashboard:chat": {
    title: "Use chat for rapid iteration",
    description: "Ask quick questions, test ideas, and move to the editor once your workflow shape is clear.",
  },
  "dashboard:credentials": {
    title: "Manage secrets safely",
    description: "Keep provider keys and tokens centralized so workflows can reuse secure connections without exposing raw secrets.",
  },
  "dashboard:vectorstores": {
    title: "Power retrieval-based workflows",
    description: "Prepare vector stores for grounded AI responses, semantic search, and scalable RAG pipelines.",
  },
  "dashboard:mcp": {
    title: "Connect external tool ecosystems",
    description: "Configure MCP connections so agents can use structured tools and perform actions beyond static prompting.",
  },
  "dashboard:traces": {
    title: "Understand execution behavior",
    description: "Inspect trace-level details to debug outcomes, compare runs, and improve workflow reliability.",
  },
  "dashboard:analytics": {
    title: "Track platform performance",
    description: "Monitor adoption and execution trends to decide what to optimize next with real usage signals.",
  },
  "dashboard:teams": {
    title: "Scale collaboration cleanly",
    description: "Share workflows and resources by team to reduce manual access work and keep ownership clear.",
  },
  "dashboard:logs": {
    title: "Diagnose system-level issues",
    description: "Use logs when failures are environmental or infrastructure-related and need deeper runtime visibility.",
  },
  "dashboard:drive": {
    title: "Manage generated files",
    description: "Review, download, and share workflow outputs with secure links and controlled access options.",
  },
  "dashboard:datatable": {
    title: "Work with structured data natively",
    description: "Create typed tables and drive them directly from workflows for repeatable read/write operations.",
  },
  "dashboard:schedules": {
    title: "See your automation schedule",
    description: "View all active cron workflows on a day, week, or month calendar. Click any block to jump straight to the canvas.",
  },
  evals: {
    title: "Benchmark quality with confidence",
    description: "Run repeatable suites to compare prompt and model changes before shipping critical workflow updates.",
  },
  docs: {
    title: "Get in-app guidance quickly",
    description: "Browse concise references and jump deeper only when needed, without leaving your current product flow.",
  },
  editor: {
    title: "Design and debug on canvas",
    description: "Compose nodes visually, execute quickly, and refine behavior with immediate feedback in one workspace.",
  },
};

export function getShowcaseIntroVideo(context: ShowcaseContext | null): string | null {
  if (!context) return null;
  return SHOWCASE_INTRO_VIDEO_BY_CONTEXT[context] ?? null;
}

export function getShowcaseIntroContent(context: ShowcaseContext | null): ShowcaseIntroContent | null {
  if (!context) return null;
  return SHOWCASE_INTRO_CONTENT_BY_CONTEXT[context] ?? null;
}

export function getShowcaseIntroScreenKey(context: ShowcaseContext | null): string | null {
  if (!context) return null;
  return context.replace(/[:/]/g, "_");
}
