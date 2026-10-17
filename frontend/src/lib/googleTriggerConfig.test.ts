import { describe, expect, it } from "vitest";

import {
  SHEETS_EVENT_OPTIONS,
  driveEventOptions,
  googleTriggerProblems,
  selectedEvents,
  toggleEvent,
} from "./googleTriggerConfig";

describe("googleTriggerConfig", () => {
  it("offers created only for folder scope", () => {
    expect(driveEventOptions("folder").map((o) => o.value)).toEqual(["created", "updated", "deleted"]);
    expect(driveEventOptions("file").map((o) => o.value)).toEqual(["updated", "deleted"]);
    expect(SHEETS_EVENT_OPTIONS.map((o) => o.label)).toEqual(["Row added", "Row updated", "Row deleted"]);
  });

  it("treats a missing event list as every event", () => {
    expect(selectedEvents(undefined)).toEqual(["created", "updated", "deleted"]);
    expect(selectedEvents(["deleted", "bogus"])).toEqual(["deleted"]);
  });

  it("toggles events in a stable order", () => {
    expect(toggleEvent(["deleted"], "created", true)).toEqual(["created", "deleted"]);
    expect(toggleEvent(["created", "deleted"], "created", false)).toEqual(["deleted"]);
  });

  it("flags a Drive file scope without a file", () => {
    expect(googleTriggerProblems("googleDriveTrigger", { label: "t", gdtScope: "file" })).toContain(
      "File is not specified",
    );
  });

  it("flags a file scope whose only event is created", () => {
    expect(
      googleTriggerProblems("googleDriveTrigger", {
        label: "t",
        gdtScope: "file",
        gdtFileId: "abc",
        gdtEvents: ["created"],
      }),
    ).toContain("Select at least one event");
  });

  it("flags a Sheets trigger without a spreadsheet or sheet name", () => {
    const problems = googleTriggerProblems("googleSheetsTrigger", { label: "t", gstSheetName: "" });
    expect(problems).toContain("Spreadsheet is not specified");
    expect(problems).toContain("Sheet name is not specified");
  });

  it("flags a poll interval below one minute", () => {
    expect(
      googleTriggerProblems("googleSheetsTrigger", {
        label: "t",
        gstSpreadsheetId: "S1",
        pollIntervalMinutes: 0,
      }),
    ).toContain("Poll interval must be at least 1 minute");
  });

  it("accepts a complete Sheets trigger", () => {
    expect(
      googleTriggerProblems("googleSheetsTrigger", {
        label: "t",
        gstSpreadsheetId: "S1",
        gstSheetName: "Leads",
        pollIntervalMinutes: 1,
      }),
    ).toEqual([]);
  });
});
