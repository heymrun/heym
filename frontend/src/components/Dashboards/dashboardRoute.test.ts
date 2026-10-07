import { describe, expect, it } from "vitest";

import { dashboardQuery, pageFromQuery, samePage } from "@/components/Dashboards/dashboardRoute";

describe("pageFromQuery", () => {
  it("reads the record and its label", () => {
    expect(pageFromQuery({ record: "ACME-1", label: "Acme Ltd" })).toEqual({
      record: "ACME-1",
      label: "Acme Ltd",
    });
  });

  it("labels a record with itself and ignores an empty one", () => {
    expect(pageFromQuery({ record: "ACME-1" })).toEqual({ record: "ACME-1", label: "ACME-1" });
    expect(pageFromQuery({ record: " " })).toBeNull();
    expect(pageFromQuery({})).toBeNull();
  });
});

describe("dashboardQuery", () => {
  const onDetailPage = { tab: "dashboard", dashboard: "d-1", record: "ACME-1", label: "Acme" };

  it("opens a detail page on another dashboard", () => {
    expect(
      dashboardQuery({ tab: "dashboard", dashboard: "d-1" }, "d-2", {
        record: "ACME-1",
        label: "Acme",
      }),
    ).toEqual({ tab: "dashboard", dashboard: "d-2", record: "ACME-1", label: "Acme" });
  });

  it("drops the record when another dashboard opens without one", () => {
    expect(dashboardQuery(onDetailPage, "d-3", null)).toEqual({
      tab: "dashboard",
      dashboard: "d-3",
    });
  });

  it("knows when the URL already shows that page", () => {
    expect(samePage(onDetailPage, dashboardQuery(onDetailPage, "d-1", pageFromQuery(onDetailPage))))
      .toBe(true);
    expect(samePage(onDetailPage, dashboardQuery(onDetailPage, "d-1", null))).toBe(false);
  });
});
