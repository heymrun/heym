import type { HighlightPayload } from "@/types/workflow";

export interface ChartSeries {
  name: string;
  // number[] for pie/bar/line; [x, y] tuples for scatter
  data: number[] | (number | null)[][];
}

/** One pending human review shown in a HITL widget carousel. */
export interface HitlWidgetItem {
  id: string;
  workflow_id?: string;
  execution_history_id?: string;
  workflow_name: string;
  agent_label: string;
  summary: string;
  text: string;
  created_at?: string;
}

/** Tone of a status chip in a table widget's status column. */
export type StatusTone = "success" | "attention" | "failure" | "waiting" | "neutral";

export interface ChartPayload {
  type:
    | "pie"
    | "bar"
    | "line"
    | "area"
    | "table"
    | "numeric"
    | "gauge"
    | "scatter"
    | "proportion"
    | "barGauge"
    | "text"
    | "hitl";
  orientation?: "horizontal" | "vertical";
  labels?: string[];
  series?: ChartSeries[];
  columns?: string[];
  rows?: unknown[][];
  // Table column rendered as status chips, and the tone of each value in it.
  statusColumn?: string;
  statusTones?: Record<string, StatusTone>;
  value?: number | string | null;
  // Markdown content for the `text` chart type.
  text?: string;
  // When true, GFM task list checkboxes can be toggled from the dashboard.
  text_interactive?: boolean;
  unit?: string;
  decimals?: number;
  min?: number;
  max?: number;
  title?: string;
  // Optional external link set on the chartOutput node; rendered as an icon in the widget title.
  url?: string;
  // HITL carousel. Live widgets omit items and load the signed-in user's inbox.
  // The add-widget preview passes sample items so the carousel renders offline.
  pending_total?: number;
  items?: HitlWidgetItem[];
}

/** A file-run widget before any drop: the file its workflow's File Upload trigger takes. */
export interface FileRunPayload {
  type: "fileRun";
  file_label: string;
  max_size_mb: number;
  allowed_types: string[];
}

/** Every widget is a chart, except the file-run widget that runs a workflow on a file. */
export type WidgetType = ChartPayload["type"] | "fileRun";

/** A single-use upload link for one drop on a file-run widget. */
export interface FileRunSlot {
  upload_url: string;
  expires_at: string;
  max_size_mb: number;
  allowed_types: string[];
  slot_id: string;
}

export interface WidgetLayout {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface DashboardWidget {
  id: string;
  workflow_id: string;
  title: string;
  description: string | null;
  chart_type: WidgetType;
  layout: WidgetLayout;
  cache_ttl_seconds: number;
  position: number;
  /** Row link of a table widget: rows open this dashboard with ?record=<record field>. */
  link_dashboard_id: string | null;
  link_record_field: string | null;
  link_label_field: string | null;
  /** Whether the viewer can open the linked dashboard; rows are clickable only then. */
  link_accessible: boolean;
  updated_at: string;
}

/** Which `?record=` values a dashboard accepts as a detail page. */
export type RecordFormat = "id" | "number" | "uuid" | "email";

/** The caller's access to a dashboard. */
export type DashboardPermission = "owner" | "write" | "read";
export type DashboardSharePermission = "read" | "write";

export interface DashboardSummary {
  id: string;
  name: string;
  permission: DashboardPermission;
  /** Set only on dashboards shared with the caller. */
  owner_name: string | null;
  shared_by: string | null;
  record_format: RecordFormat;
  updated_at: string;
}

export interface DashboardData extends DashboardSummary {
  widgets: DashboardWidget[];
}

export interface DashboardShare {
  id: string;
  user_id: string;
  email: string;
  name: string | null;
  permission: DashboardSharePermission;
  shared_at: string;
}

export interface DashboardTeamShare {
  id: string;
  team_id: string;
  team_name: string;
  permission: DashboardSharePermission;
  shared_at: string;
}

export interface WidgetDataResponse {
  widget_id: string;
  payload: ChartPayload | FileRunPayload | null;
  cached: boolean;
  computed_at: string | null;
  error?: string | null;
  highlight?: HighlightPayload | null;
}

export interface WidgetCreateRequest {
  title: string;
  description?: string | null;
  chart_type: WidgetType;
  layout: WidgetLayout;
  cache_ttl_seconds: number;
  /** For a file-run widget: the workflow with a File Upload trigger it runs. */
  workflow_id?: string;
}

export interface WidgetUpdateRequest {
  title?: string;
  description?: string | null;
  chart_type?: ChartPayload["type"];
  layout?: WidgetLayout;
  cache_ttl_seconds?: number;
  /** Send with link_record_field to set the row link, or as null to remove it. */
  link_dashboard_id?: string | null;
  link_record_field?: string | null;
  link_label_field?: string | null;
}
