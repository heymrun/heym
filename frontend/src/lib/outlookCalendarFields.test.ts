import { describe, expect, it } from "vitest";

import {
  OUTLOOK_CALENDAR_BUSY_DETAILS_OPTION,
  OUTLOOK_CALENDAR_OPERATIONS,
  OUTLOOK_CALENDAR_TEAMS_OPTION,
  getOutlookCalendarFields,
  getOutlookCalendarOption,
} from "@/lib/outlookCalendarFields";
import { NODE_DEFINITIONS } from "@/types/node";

describe("Outlook Calendar operation metadata", () => {
  it("defaults to reading the primary calendar without busy details and with Teams on create", () => {
    const defaults = NODE_DEFINITIONS.outlookCalendar.defaultData;
    expect(defaults.ocOperation).toBe("read");
    expect(defaults.ocCalendarId).toBe("primary");
    expect(defaults.ocIncludeBusyDetails).toBe(OUTLOOK_CALENDAR_BUSY_DETAILS_OPTION.defaultValue);
    expect(defaults.ocTeamsMeeting).toBe(OUTLOOK_CALENDAR_TEAMS_OPTION.defaultValue);
    expect(OUTLOOK_CALENDAR_BUSY_DETAILS_OPTION.defaultValue).toBe(false);
    expect(OUTLOOK_CALENDAR_TEAMS_OPTION.defaultValue).toBe(true);
  });

  it("offers the checkboxes to agent autofill but not to expressions", () => {
    for (const option of [OUTLOOK_CALENDAR_BUSY_DETAILS_OPTION, OUTLOOK_CALENDAR_TEAMS_OPTION]) {
      expect(option.agentAutofill).toBe(true);
      expect(option.expressionCapable).toBe(false);
    }
    expect(getOutlookCalendarOption("read")?.key).toBe("ocIncludeBusyDetails");
    expect(getOutlookCalendarOption("create")?.key).toBe("ocTeamsMeeting");
    expect(getOutlookCalendarOption("update")).toBeNull();
    expect(getOutlookCalendarOption("delete")).toBeNull();
  });

  it("exposes availability dates for read and booking fields for create and update", () => {
    expect(getOutlookCalendarFields("read").map((field) => field.key)).toEqual([
      "ocCalendarId", "ocTimeZone", "ocStartDate", "ocEndDate",
    ]);
    for (const operation of ["create", "update"] as const) {
      expect(getOutlookCalendarFields(operation).map((field) => field.key)).toEqual(expect.arrayContaining([
        "ocTitle", "ocDescription", "ocAttendees", "ocStartTime", "ocEndTime", "ocTimeZone", "ocLocation",
      ]));
    }
  });

  it("finds update and delete targets by event id alone", () => {
    expect(getOutlookCalendarFields("update").map((field) => field.key)).not.toContain("ocCalendarId");
    expect(getOutlookCalendarFields("delete").map((field) => field.key)).toEqual(["ocEventId"]);
  });

  it("defines a default and a label for every field of every operation", () => {
    const defaults = NODE_DEFINITIONS.outlookCalendar.defaultData;
    for (const operation of OUTLOOK_CALENDAR_OPERATIONS) {
      for (const field of getOutlookCalendarFields(operation.value)) {
        expect(Object.hasOwn(defaults, field.key)).toBe(true);
        expect(field.label && field.placeholder).toBeTruthy();
      }
    }
  });
});
