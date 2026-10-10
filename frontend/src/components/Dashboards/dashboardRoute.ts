import type { LocationQuery, LocationQueryRaw } from "vue-router";

/** A detail page: the record its widgets run for, and the name the page shows for it. */
export interface DashboardPage {
  record: string;
  label: string;
}

function single(value: LocationQuery[string] | undefined): string | null {
  const first = Array.isArray(value) ? value[0] : value;
  return typeof first === "string" && first.trim() ? first : null;
}

/** The detail page the URL names, or null on a dashboard opened without ?record=. */
export function pageFromQuery(query: LocationQuery): DashboardPage | null {
  const record = single(query.record);
  if (record === null) return null;
  return { record, label: single(query.label) ?? record };
}

/**
 * The query for a dashboard, on a detail page or not. Other keys (the tab) are kept;
 * a record never carries over to another dashboard.
 */
export function dashboardQuery(
  query: LocationQuery,
  dashboardId: string,
  page: DashboardPage | null,
): LocationQueryRaw {
  const next: LocationQueryRaw = { ...query, tab: "dashboard", dashboard: dashboardId };
  delete next.record;
  delete next.label;
  if (page) {
    next.record = page.record;
    next.label = page.label;
  }
  return next;
}

/** Whether two queries name the same dashboard and detail page. */
export function samePage(query: LocationQuery, next: LocationQueryRaw): boolean {
  return (
    single(query.dashboard) === next.dashboard &&
    single(query.record) === (next.record ?? null) &&
    single(query.label) === (next.label ?? null)
  );
}
