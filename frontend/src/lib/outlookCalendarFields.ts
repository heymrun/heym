import type { NodeData } from "@/types/workflow";

export type OutlookCalendarOperation = NonNullable<NodeData["ocOperation"]>;
export type OutlookCalendarFieldKey =
  | "ocCalendarId" | "ocTimeZone" | "ocStartDate" | "ocEndDate" | "ocEventId"
  | "ocTitle" | "ocDescription" | "ocStartTime" | "ocEndTime" | "ocAttendees" | "ocLocation";

export interface OutlookCalendarField {
  key: OutlookCalendarFieldKey;
  label: string;
  placeholder: string;
  help?: string;
}

export interface OutlookCalendarOption {
  key: "ocIncludeBusyDetails" | "ocTeamsMeeting";
  label: string;
  defaultValue: boolean;
  expressionCapable: false;
  agentAutofill: true;
  help: string;
}

export const OUTLOOK_CALENDAR_OPERATIONS: { value: OutlookCalendarOperation; label: string }[] = [
  { value: "read", label: "Read Available Time Slots" },
  { value: "create", label: "Create Meeting & Send Invitations" },
  { value: "update", label: "Update Meeting & Notify Guests" },
  { value: "delete", label: "Delete Meeting & Notify Guests" },
];

export const OUTLOOK_CALENDAR_BUSY_DETAILS_OPTION: OutlookCalendarOption = {
  key: "ocIncludeBusyDetails",
  label: "Include Busy Event Details",
  defaultValue: false,
  expressionCapable: false,
  agentAutofill: true,
  help: "Adds each busy event's title and attendees.",
};

export const OUTLOOK_CALENDAR_TEAMS_OPTION: OutlookCalendarOption = {
  key: "ocTeamsMeeting",
  label: "Add Teams meeting",
  defaultValue: true,
  expressionCapable: false,
  agentAutofill: true,
  help: "Work or school accounts only.",
};

const fields: Record<OutlookCalendarFieldKey, OutlookCalendarField> = {
  ocCalendarId: { key: "ocCalendarId", label: "Calendar", placeholder: "primary", help: "primary, one of your calendar names such as Work, or a calendar ID. To read a colleague's free time, enter their email address." },
  ocTimeZone: { key: "ocTimeZone", label: "Time Zone", placeholder: "UTC", help: "IANA time zone, such as Europe/Berlin. Dates without an offset use this zone." },
  ocStartDate: { key: "ocStartDate", label: "Availability Start (optional)", placeholder: "2026-11-18T09:00:00Z", help: "ISO date or datetime, such as $now.toISO(). Empty starts now." },
  ocEndDate: { key: "ocEndDate", label: "Availability End (optional)", placeholder: "2026-12-01T00:00:00Z", help: "Exclusive ISO end, such as $now.addDays(14).toISO(), at most 60 days after start. Empty ends on the first day of next month." },
  ocEventId: { key: "ocEventId", label: "Event ID", placeholder: "$booking.event_id", help: "The event_id returned when the meeting was created, not the Teams link." },
  ocTitle: { key: "ocTitle", label: "Title", placeholder: "$input.title" },
  ocDescription: { key: "ocDescription", label: "Description (optional)", placeholder: "$input.description" },
  ocStartTime: { key: "ocStartTime", label: "Start Time", placeholder: "$input.startTime", help: "ISO datetime, such as 2026-11-10T14:00:00+01:00. Supply both start and end." },
  ocEndTime: { key: "ocEndTime", label: "End Time", placeholder: "$input.endTime" },
  ocAttendees: { key: "ocAttendees", label: "Attendee Emails", placeholder: "$input.email", help: "Comma-separated emails or a JSON array. Guests receive Outlook invitations. Use [] to remove all guests on update." },
  ocLocation: { key: "ocLocation", label: "Location (optional)", placeholder: "Meeting room or address" },
};

const operationFields: Record<OutlookCalendarOperation, OutlookCalendarFieldKey[]> = {
  read: ["ocCalendarId", "ocTimeZone", "ocStartDate", "ocEndDate"],
  create: ["ocCalendarId", "ocTimeZone", "ocTitle", "ocDescription", "ocStartTime", "ocEndTime", "ocAttendees", "ocLocation"],
  update: ["ocTimeZone", "ocEventId", "ocTitle", "ocDescription", "ocStartTime", "ocEndTime", "ocAttendees", "ocLocation"],
  delete: ["ocEventId"],
};

/** One ordered field list for the form, expression navigation and agent autofill. */
export function getOutlookCalendarFields(
  operation: OutlookCalendarOperation = "read",
): OutlookCalendarField[] {
  return (operationFields[operation] ?? []).map((key) => fields[key]);
}

/** The checkbox shown for an operation: busy details on read, Teams on create. */
export function getOutlookCalendarOption(
  operation: OutlookCalendarOperation = "read",
): OutlookCalendarOption | null {
  if (operation === "read") return OUTLOOK_CALENDAR_BUSY_DETAILS_OPTION;
  if (operation === "create") return OUTLOOK_CALENDAR_TEAMS_OPTION;
  return null;
}
