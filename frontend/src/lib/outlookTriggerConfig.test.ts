import { describe, expect, it } from "vitest";

import { outlookAfterAction, outlookMailbox, outlookTriggerProblems } from "@/lib/outlookTriggerConfig";

describe("outlookTriggerConfig", () => {
  it("falls back to the inbox and no action for unknown values", () => {
    expect(outlookMailbox("junk")).toBe("inbox");
    expect(outlookMailbox("focused")).toBe("focused");
    expect(outlookAfterAction("purge")).toBe("none");
    expect(outlookAfterAction("delete")).toBe("delete");
  });

  it("asks for a folder and a valid poll interval", () => {
    expect(outlookTriggerProblems({ label: "o", pollIntervalMinutes: 1 })).toEqual([]);
    expect(outlookTriggerProblems({ label: "o", pollIntervalMinutes: 0, outlookMailbox: "folder" })).toEqual([
      "Poll interval must be at least 1 minute",
      "Choose the folder to watch",
    ]);
    expect(
      outlookTriggerProblems({ label: "o", pollIntervalMinutes: 5, outlookMailbox: "folder", outlookFolderId: "AAMk" }),
    ).toEqual([]);
  });
});
