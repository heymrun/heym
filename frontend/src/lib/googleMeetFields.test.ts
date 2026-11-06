import { describe, expect, it } from "vitest";

import { GOOGLE_MEET_BUSY_TITLES_OPTION, GOOGLE_MEET_OPERATIONS, getGoogleMeetFields } from "@/lib/googleMeetFields";
import { NODE_DEFINITIONS } from "@/types/node";

describe("Google Meet operation metadata", () => {
  it("keeps busy titles disabled by default and available to agent autofill", () => {
    expect(NODE_DEFINITIONS.googleMeet.defaultData.gmIncludeBusyTitles).toBe(false);
    expect(GOOGLE_MEET_BUSY_TITLES_OPTION.defaultValue).toBe(false);
    expect(GOOGLE_MEET_BUSY_TITLES_OPTION.key).toBe("gmIncludeBusyTitles");
    expect(GOOGLE_MEET_BUSY_TITLES_OPTION.agentAutofill).toBe(true);
    expect(GOOGLE_MEET_BUSY_TITLES_OPTION.expressionCapable).toBe(false);
  });
  it("exposes availability dates instead of event fields for read", () => {
    expect(getGoogleMeetFields("read").map((field) => field.key)).toEqual([
      "gmCalendarId", "gmTimeZone", "gmStartDate", "gmEndDate",
    ]);
  });

  it("makes booking email, title, description and both times available to expression/agent inputs", () => {
    for (const operation of ["create", "update"] as const) {
      const fields = getGoogleMeetFields(operation);
      expect(fields.map((field) => field.key)).toEqual(expect.arrayContaining([
        "gmTitle", "gmDescription", "gmAttendees", "gmStartTime", "gmEndTime", "gmTimeZone",
      ]));
      expect(fields.every((field) => field.label && field.placeholder)).toBe(true);
    }
  });

  it("offers only event and calendar identifiers for deletion", () => {
    expect(getGoogleMeetFields("delete").map((field) => field.key)).toEqual(["gmCalendarId", "gmEventId"]);
  });

  it("defines defaults for every expression field and defaults to primary availability", () => {
    const defaults = NODE_DEFINITIONS.googleMeet.defaultData;
    expect(defaults.gmOperation).toBe("read");
    expect(defaults.gmCalendarId).toBe("primary");
    for (const operation of GOOGLE_MEET_OPERATIONS) {
      for (const field of getGoogleMeetFields(operation.value)) {
        expect(Object.hasOwn(defaults, field.key)).toBe(true);
      }
    }
  });
});
