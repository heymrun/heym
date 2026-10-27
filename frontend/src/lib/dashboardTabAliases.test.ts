import { describe, expect, it } from "vitest";

import { DASHBOARD_TAB_ALIASES, dashboardTabAlias } from "@/lib/dashboardTabAliases";

describe("dashboardTabAlias", () => {
  it("sends a2a to the MCP / A2A tab", () => {
    expect(dashboardTabAlias("a2a")).toBe("mcp");
  });

  it("leaves real tabs and unknown values alone", () => {
    expect(dashboardTabAlias("mcp")).toBeNull();
    expect(dashboardTabAlias("traces")).toBeNull();
    expect(dashboardTabAlias(undefined)).toBeNull();
  });

  it("only aliases onto tabs that exist", () => {
    expect(Object.values(DASHBOARD_TAB_ALIASES)).toEqual(["mcp"]);
  });
});
