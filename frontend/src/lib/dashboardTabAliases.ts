/**
 * Other names that open an existing dashboard tab. `?tab=a2a` and `/a2a` land on the
 * MCP / A2A tab, whose canonical URL stays `?tab=mcp`.
 */
export const DASHBOARD_TAB_ALIASES: Readonly<Record<string, string>> = {
  a2a: "mcp",
};

/** The tab an alias stands for, or null when `raw` is not an alias. */
export function dashboardTabAlias(raw: string | null | undefined): string | null {
  if (!raw) return null;
  return DASHBOARD_TAB_ALIASES[raw] ?? null;
}
