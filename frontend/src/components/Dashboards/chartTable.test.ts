import { describe, expect, it } from "vitest";

import {
  cellText,
  sortTableRows,
  statusTone,
  tableLinkHref,
  tableRowRecord,
} from "@/components/Dashboards/chartTable";

describe("tableLinkHref", () => {
  it("opens http(s) URLs and paths inside the app", () => {
    expect(tableLinkHref("https://jira.example.com/browse/T-1?x=1")).toBe(
      "https://jira.example.com/browse/T-1?x=1",
    );
    expect(tableLinkHref(" http://example.com ")).toBe("http://example.com/");
    expect(tableLinkHref("/dashboards")).toBe("/dashboards");
    expect(tableLinkHref("/dashboards/abc?record=V-1")).toBe("/dashboards/abc?record=V-1");
  });

  it("is not a link for empty cells or schemes that could run code", () => {
    expect(tableLinkHref("")).toBeNull();
    expect(tableLinkHref(null)).toBeNull();
    expect(tableLinkHref("javascript:alert(1)")).toBeNull();
    expect(tableLinkHref("data:text/html,<b>x</b>")).toBeNull();
    expect(tableLinkHref("ftp://example.com/file")).toBeNull();
    expect(tableLinkHref("//evil.example.com")).toBeNull();
    expect(tableLinkHref("/\\evil.example.com")).toBeNull();
    expect(tableLinkHref("dashboards")).toBeNull();
    expect(tableLinkHref({ url: "https://example.com" })).toBeNull();
  });
});

describe("statusTone", () => {
  it("reads the tone the server resolved for the cell's text", () => {
    const tones = { Paid: "success", "true": "waiting", "3": "failure" } as const;

    expect(statusTone("Paid", tones)).toBe("success");
    expect(statusTone(true, tones)).toBe("waiting");
    expect(statusTone(3, tones)).toBe("failure");
    expect(statusTone("Unknown", tones)).toBe("neutral");
    expect(statusTone("Paid", undefined)).toBe("neutral");
  });
});

describe("tableRowRecord", () => {
  const columns = ["id", "name", "state"];

  it("takes the record from the link column and the label from the label column", () => {
    expect(
      tableRowRecord(columns, ["ACME-1", "Acme Ltd", "Paid"], {
        recordField: "id",
        labelField: "name",
      }),
    ).toEqual({ record: "ACME-1", label: "Acme Ltd" });
  });

  it("labels the record with itself when there is no label column", () => {
    expect(tableRowRecord(columns, [42, "", "Paid"], { recordField: "id", labelField: "name" }))
      .toEqual({ record: "42", label: "42" });
  });

  it("has no record without a link, a known column or a value", () => {
    expect(tableRowRecord(columns, ["ACME-1"], null)).toBeNull();
    expect(tableRowRecord(columns, ["ACME-1"], { recordField: "missing" })).toBeNull();
    expect(tableRowRecord(columns, [null, "Acme"], { recordField: "id" })).toBeNull();
  });

  it("shows objects as JSON", () => {
    expect(cellText({ a: 1 })).toBe('{"a":1}');
  });
});

describe("sortTableRows", () => {
  const rows = [
    ["LV-812", "Ravi N.", ""],
    ["LV-802", "Omar S.", "2"],
    ["LV-810", "omar s.", "10"],
  ];

  it("sorts text ascending, then descending, without losing the original order of ties", () => {
    expect(sortTableRows(rows, 1, "asc").map((row) => row[0])).toEqual(["LV-802", "LV-810", "LV-812"]);
    expect(sortTableRows(rows, 1, "desc").map((row) => row[0])).toEqual(["LV-812", "LV-802", "LV-810"]);
  });

  it("sorts numbers numerically and keeps empty cells last", () => {
    expect(sortTableRows(rows, 2, "asc").map((row) => row[0])).toEqual(["LV-802", "LV-810", "LV-812"]);
    expect(sortTableRows(rows, 2, "desc").map((row) => row[0])).toEqual(["LV-810", "LV-802", "LV-812"]);
  });
});
