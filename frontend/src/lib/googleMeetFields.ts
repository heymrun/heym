import type { NodeData } from "@/types/workflow";

export type GoogleMeetOperation = NonNullable<NodeData["gmOperation"]>;
export type GoogleMeetFieldKey =
  | "gmCalendarId" | "gmTimeZone" | "gmStartDate" | "gmEndDate" | "gmEventId"
  | "gmTitle" | "gmDescription" | "gmStartTime" | "gmEndTime" | "gmAttendees" | "gmLocation";

export interface GoogleMeetField {
  key: GoogleMeetFieldKey;
  label: string;
  placeholder: string;
  help?: string;
}

export const GOOGLE_MEET_OPERATIONS: { value: GoogleMeetOperation; label: string }[] = [
  { value: "read", label: "Read Available Time Slots" },
  { value: "create", label: "Create Meeting & Send Invitations" },
  { value: "update", label: "Update Meeting & Notify Guests" },
  { value: "delete", label: "Delete Meeting & Notify Guests" },
];

export const GOOGLE_MEET_BUSY_TITLES_OPTION = {
  key: "gmIncludeBusyTitles",
  label: "Include Busy Event Titles",
  defaultValue: false,
  expressionCapable: false,
  agentAutofill: true,
  help: "Off by default. Adds event titles to busy_slots when Google allows reading event details. Overlapping events appear separately; hidden titles are null.",
} as const;

const fields: Record<GoogleMeetFieldKey, GoogleMeetField> = {
  gmCalendarId: { key: "gmCalendarId", label: "Calendar ID or Email", placeholder: "primary", help: "Use primary for your calendar, or a calendar email you have permission to access." },
  gmTimeZone: { key: "gmTimeZone", label: "Time Zone", placeholder: "UTC", help: "IANA time zone, such as Europe/Berlin. Dates without an offset use this zone." },
  gmStartDate: { key: "gmStartDate", label: "Availability Start (optional)", placeholder: "Now, or $input.startDate" },
  gmEndDate: { key: "gmEndDate", label: "Availability End (optional)", placeholder: "Next month's first day, or $input.endDate", help: "Exclusive end. ISO date or datetime; the range must be no longer than 60 days." },
  gmEventId: { key: "gmEventId", label: "Event ID", placeholder: "$booking.event_id" },
  gmTitle: { key: "gmTitle", label: "Title", placeholder: "$input.title" },
  gmDescription: { key: "gmDescription", label: "Description (optional)", placeholder: "$input.description" },
  gmStartTime: { key: "gmStartTime", label: "Start Time", placeholder: "$input.startTime", help: "ISO datetime, such as 2026-11-10T14:00:00+01:00. Supply both start and end." },
  gmEndTime: { key: "gmEndTime", label: "End Time", placeholder: "$input.endTime" },
  gmAttendees: { key: "gmAttendees", label: "Attendee Emails", placeholder: "$input.email", help: "Comma-separated emails or a JSON array. Guests receive calendar invitations. Use [] to remove all guests on update." },
  gmLocation: { key: "gmLocation", label: "Location (optional)", placeholder: "Meeting location" },
};

const operationFields: Record<GoogleMeetOperation, GoogleMeetFieldKey[]> = {
  read: ["gmCalendarId", "gmTimeZone", "gmStartDate", "gmEndDate"],
  create: ["gmCalendarId", "gmTimeZone", "gmTitle", "gmDescription", "gmStartTime", "gmEndTime", "gmAttendees", "gmLocation"],
  update: ["gmCalendarId", "gmTimeZone", "gmEventId", "gmTitle", "gmDescription", "gmStartTime", "gmEndTime", "gmAttendees", "gmLocation"],
  delete: ["gmCalendarId", "gmEventId"],
};

/** One ordered field list for the form, expression navigation and agent autofill. */
export function getGoogleMeetFields(operation: GoogleMeetOperation = "read"): GoogleMeetField[] {
  return (operationFields[operation] ?? []).map((key) => fields[key]);
}
