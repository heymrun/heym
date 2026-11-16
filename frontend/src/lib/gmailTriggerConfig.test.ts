import { describe, expect, it } from "vitest";

import {
  gmailAfterAction,
  gmailMailbox,
  gmailTriggerProblems,
  parseGmailAliases,
  toggleGmailAlias,
} from "@/lib/gmailTriggerConfig";

describe("gmailTriggerConfig", () => {
  it("falls back to the inbox and no action for unknown values", () => {
    expect(gmailMailbox("spam")).toBe("inbox");
    expect(gmailMailbox("primary")).toBe("primary");
    expect(gmailAfterAction("deleteForever")).toBe("none");
    expect(gmailAfterAction("trash")).toBe("trash");
  });

  it("parses aliases from text or a list", () => {
    expect(parseGmailAliases("Sales@Example.com, me+inv@gmail.com;sales@example.com x")).toEqual([
      "sales@example.com",
      "me+inv@gmail.com",
    ]);
    expect(parseGmailAliases(["A@x.com", "", "a@x.com"])).toEqual(["a@x.com"]);
    expect(parseGmailAliases(undefined)).toEqual([]);
  });

  it("toggles an alias on and off", () => {
    expect(toggleGmailAlias([], "Me@x.com")).toEqual(["me@x.com"]);
    expect(toggleGmailAlias(["me@x.com"], "ME@x.com")).toEqual([]);
  });

  it("asks for a label and a valid poll interval", () => {
    expect(gmailTriggerProblems({ label: "g", pollIntervalMinutes: 1 })).toEqual([]);
    expect(gmailTriggerProblems({ label: "g", pollIntervalMinutes: 0, gmailMailbox: "label" })).toEqual([
      "Poll interval must be at least 1 minute",
      "Choose the label to watch",
    ]);
    expect(
      gmailTriggerProblems({ label: "g", pollIntervalMinutes: 5, gmailMailbox: "label", gmailLabelId: "Label_1" }),
    ).toEqual([]);
  });
});
