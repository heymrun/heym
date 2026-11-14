import { describe, expect, it } from "vitest";

import type { NodeTemplate } from "@/features/templates/types/template.types";
import {
  GOOGLE_MEET_BUSY_DETAILS_OPTION,
  GOOGLE_MEET_BUSY_TITLES_OPTION,
  GOOGLE_MEET_OPERATIONS,
  getGoogleMeetFields,
} from "@/lib/googleMeetFields";
import { buildWorkflowNodeFromNodeTemplate } from "@/lib/nodeFromTemplate";
import { NODE_DEFINITIONS } from "@/types/node";

describe("Google Meet operation metadata", () => {
  it("keeps busy details disabled by default and available to agent autofill", () => {
    expect(NODE_DEFINITIONS.googleMeet.defaultData.gmIncludeBusyDetails).toBe(false);
    expect(GOOGLE_MEET_BUSY_DETAILS_OPTION.defaultValue).toBe(false);
    expect(GOOGLE_MEET_BUSY_DETAILS_OPTION.key).toBe("gmIncludeBusyDetails");
    expect(GOOGLE_MEET_BUSY_DETAILS_OPTION.label).toBe("Include Busy Event Details");
    expect(GOOGLE_MEET_BUSY_DETAILS_OPTION.help).toBe(
      "Adds each busy event's title and attendees when Google shares event details.",
    );
    expect(GOOGLE_MEET_BUSY_DETAILS_OPTION.agentAutofill).toBe(true);
    expect(GOOGLE_MEET_BUSY_DETAILS_OPTION.expressionCapable).toBe(false);
    // Legacy alias also references the new option
    expect(GOOGLE_MEET_BUSY_TITLES_OPTION.key).toBe("gmIncludeBusyDetails");
  });

  it("hydrates legacy saved nodes and ensures new key takes precedence", () => {
    // Template hydration: legacy node_data with gmIncludeBusyTitles: true must not be masked by default false
    const nodeFromLegacyTemplate = buildWorkflowNodeFromNodeTemplate(
      {
        id: "template-1",
        name: "Old Meet Template",
        node_type: "googleMeet",
        node_data: { gmOperation: "read", gmIncludeBusyTitles: true },
      } as unknown as NodeTemplate,
      { x: 0, y: 0 },
      null,
    );
    expect(nodeFromLegacyTemplate.data.gmIncludeBusyDetails).toBe(true);

    // Precedence: explicit false on new key overrides legacy true
    const nodeWithExplicitFalse = buildWorkflowNodeFromNodeTemplate(
      {
        id: "template-2",
        name: "Explicit False Template",
        node_type: "googleMeet",
        node_data: { gmOperation: "read", gmIncludeBusyDetails: false, gmIncludeBusyTitles: true },
      } as unknown as NodeTemplate,
      { x: 0, y: 0 },
      null,
    );
    expect(nodeWithExplicitFalse.data.gmIncludeBusyDetails).toBe(false);

    // Precedence: explicit null on new key overrides legacy true (treated as false, not as fallback)
    const nodeWithExplicitNull = buildWorkflowNodeFromNodeTemplate(
      {
        id: "template-3",
        name: "Explicit Null Template",
        node_type: "googleMeet",
        node_data: { gmOperation: "read", gmIncludeBusyDetails: null, gmIncludeBusyTitles: true },
      } as unknown as NodeTemplate,
      { x: 0, y: 0 },
      null,
    );
    expect(nodeWithExplicitNull.data.gmIncludeBusyDetails).toBe(false);

    // Precedence: explicit undefined on new key overrides legacy true (takes precedence over fallback)
    const nodeWithExplicitUndefined = buildWorkflowNodeFromNodeTemplate(
      {
        id: "template-4",
        name: "Explicit Undefined Template",
        node_type: "googleMeet",
        node_data: { gmOperation: "read", gmIncludeBusyDetails: undefined, gmIncludeBusyTitles: true },
      } as unknown as NodeTemplate,
      { x: 0, y: 0 },
      null,
    );
    expect(nodeWithExplicitUndefined.data.gmIncludeBusyDetails).toBe(false);
  });

  it("explicitly normalizes legacy gmIncludeBusyTitles values during template hydration", () => {
    const hydrateWithTitles = (value: unknown) =>
      buildWorkflowNodeFromNodeTemplate(
        {
          id: "legacy-template",
          name: "Legacy Template",
          node_type: "googleMeet",
          node_data: { gmOperation: "read", gmIncludeBusyTitles: value },
        } as unknown as NodeTemplate,
        { x: 0, y: 0 },
        null,
      );

    // boolean true remains true
    expect(hydrateWithTitles(true).data.gmIncludeBusyDetails).toBe(true);
    // boolean false remains false
    expect(hydrateWithTitles(false).data.gmIncludeBusyDetails).toBe(false);
    // string "true" becomes true
    expect(hydrateWithTitles("true").data.gmIncludeBusyDetails).toBe(true);
    expect(hydrateWithTitles("TRUE").data.gmIncludeBusyDetails).toBe(true);
    expect(hydrateWithTitles("  true  ").data.gmIncludeBusyDetails).toBe(true);
    // string "false" becomes false
    expect(hydrateWithTitles("false").data.gmIncludeBusyDetails).toBe(false);
    expect(hydrateWithTitles("FALSE").data.gmIncludeBusyDetails).toBe(false);
    // invalid values are not silently converted to true
    expect(hydrateWithTitles("invalid").data.gmIncludeBusyDetails).toBe(false);
    expect(hydrateWithTitles("1").data.gmIncludeBusyDetails).toBe(false);
    expect(hydrateWithTitles(1).data.gmIncludeBusyDetails).toBe(false);
    expect(hydrateWithTitles([]).data.gmIncludeBusyDetails).toBe(false);
    expect(hydrateWithTitles({}).data.gmIncludeBusyDetails).toBe(false);
    expect(hydrateWithTitles(null).data.gmIncludeBusyDetails).toBe(false);
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
