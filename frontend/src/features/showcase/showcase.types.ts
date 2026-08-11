export type ShowcaseContext =
  | "dashboard:workflows"
  | "dashboard:board"
  | "dashboard:templates"
  | "dashboard:globalvariables"
  | "dashboard:chat"
  | "dashboard:credentials"
  | "dashboard:vectorstores"
  | "dashboard:mcp"
  | "dashboard:traces"
  | "dashboard:alerts"
  | "dashboard:analytics"
  | "dashboard:dashboard"
  | "dashboard:teams"
  | "dashboard:logs"
  | "dashboard:drive"
  | "dashboard:datatable"
  | "dashboard:schedules"
  | "evals"
  | "docs"
  | "editor";

export type DashboardShowcaseTab =
  | "workflows"
  | "board"
  | "templates"
  | "globalvariables"
  | "credentials"
  | "vectorstores"
  | "mcp"
  | "traces"
  | "alerts"
  | "analytics"
  | "dashboard"
  | "teams"
  | "logs"
  | "drive"
  | "datatable"
  | "schedules";

export interface ShowcaseDocTarget {
  categoryId: string;
  slug: string;
  title?: string;
}

export interface ShowcaseAction {
  id: string;
  label: string;
  description: string;
  kind: "route" | "docs" | "external";
  to?: string;
  href?: string;
  docTarget?: ShowcaseDocTarget;
}

export interface ShowcaseHighlight {
  title: string;
  description: string;
  eyebrow?: string;
  tone?: "primary" | "blue" | "green" | "amber";
}

export interface ShowcaseDetailSection {
  id: string;
  title: string;
  content: string;
}

export interface ShowcaseDefinition {
  id: ShowcaseContext;
  title: string;
  summary: string;
  bullets: string[];
  highlights: ShowcaseHighlight[];
  actions: ShowcaseAction[];
  details: ShowcaseDetailSection[];
  docsTarget: ShowcaseDocTarget | null;
}

export interface ResolveShowcaseContextOptions {
  routePath: string;
  dashboardTab?: DashboardShowcaseTab | null;
}

export interface ResolveShowcaseDefinitionOptions {
  context: ShowcaseContext | null;
  currentDocPath?: string | null;
}
