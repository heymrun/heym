import type { HighlightPayload } from "@/types/workflow";

export interface ChartSeries {
  name: string;
  // number[] for pie/bar/line; [x, y] tuples for scatter
  data: number[] | (number | null)[][];
}

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
    | "text";
  orientation?: "horizontal" | "vertical";
  labels?: string[];
  series?: ChartSeries[];
  columns?: string[];
  rows?: unknown[][];
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
  chart_type: ChartPayload["type"];
  layout: WidgetLayout;
  cache_ttl_seconds: number;
  position: number;
  updated_at: string;
}

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
  payload: ChartPayload | null;
  cached: boolean;
  computed_at: string | null;
  error?: string | null;
  highlight?: HighlightPayload | null;
}

export interface WidgetCreateRequest {
  title: string;
  description?: string | null;
  chart_type: ChartPayload["type"];
  layout: WidgetLayout;
  cache_ttl_seconds: number;
}

export interface WidgetUpdateRequest {
  title?: string;
  description?: string | null;
  chart_type?: ChartPayload["type"];
  layout?: WidgetLayout;
  cache_ttl_seconds?: number;
}
