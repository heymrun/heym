# Outlook Calendar

Find available time in an Outlook.com or Microsoft 365 calendar and create, update or delete meeting invitations with Microsoft Teams links, attendee emails and selected times. The connected Microsoft account owns the event; attendees receive Outlook invitations by email. It works for personal Outlook.com, Hotmail and Live accounts and for work or school calendars in Microsoft 365 (Exchange Online).

## Connect your account

1. In the [Microsoft Entra admin center](https://entra.microsoft.com), open **App registrations** and select the app you use for [Outlook Mail](outlook-trigger-node.md), or create a new registration. Pick the supported account types that match who will connect.
2. Add a **Web** redirect URI `https://your-heym-domain/api/credentials/outlook-calendar/oauth/callback`. For local development, use your browser's Heym origin with the same path.
3. Under **API permissions**, add the Microsoft Graph delegated permissions `Calendars.ReadWrite`, `User.Read` and `offline_access`. Grant admin consent when your organization requires it.
4. Under **Certificates & secrets**, create a client secret and copy its **Value**.
5. Open **Dashboard → Credentials → New → Outlook Calendar (OAuth2)**, enter a name, the Application (client) ID, the client secret and the tenant, then click **Connect** and sign in with the calendar's account. Select this credential on the node.

**Tenant** is `common` by default, which accepts work, school and personal accounts. Enter `organizations`, `consumers`, or your organization's tenant ID or domain (for example `contoso.com`) to narrow who can connect. Tokens are encrypted in storage and refreshed automatically. This is a separate credential from Outlook Mail, so a calendar workflow never gets access to the mailbox.

## Operations

| Operation | Behavior | Required fields |
| --- | --- | --- |
| `read` | Return available and busy intervals for a calendar | Credential |
| `create` | Create a timed event, add a Teams meeting and email invitations | Title, start time, end time |
| `update` | Patch supplied event fields and notify guests | Event ID and at least one changed field |
| `delete` | Delete the event and notify guests of cancellation | Event ID |

## Configuration

The text fields below accept expressions. All fields, including the two checkboxes, can be supplied by an Agent when this node is attached as a tool.

| Field | Default | Purpose |
| --- | --- | --- |
| `ocCalendarId` | `primary` | `primary`, the connected address, one of your calendar names (such as `Work`) or a calendar ID. For `read`, also another person's email address |
| `ocTimeZone` | `UTC` | IANA zone, such as `Europe/Berlin`, used for local dates and response times |
| `ocStartDate` | Current time | Read range start, as an ISO date or datetime |
| `ocEndDate` | First day of the following month at midnight | Exclusive read range end; maximum range is 60 calendar days |
| `ocIncludeBusyDetails` | `false` | Read only: opt in to event titles and attendees in `busy_slots`; boolean, not an expression field |
| `ocEventId` | Empty | Event ID for update/delete; use the returned `event_id`, not the Teams link |
| `ocTitle` | Empty | Invitation title; required on create |
| `ocDescription` | Empty | Invitation text |
| `ocStartTime` | Empty | Meeting start, for example `2026-11-10T14:00:00+01:00` |
| `ocEndTime` | Empty | Meeting end; must follow start |
| `ocAttendees` | Empty | Comma/semicolon/newline-separated emails or a JSON array of email strings |
| `ocLocation` | Empty | Optional room or address alongside the Teams meeting |
| `ocTeamsMeeting` | `true` | Create only: add a Teams meeting when the calendar allows it; boolean, not an expression field |

### Which calendar

- `primary` (or your own address) is the account's default calendar.
- A calendar name such as `Work` or `Family` selects one of your other calendars; names are matched without case. When two calendars share a name, use the calendar ID instead.
- Another person's email address works for `read` only. Heym reads their free/busy through Microsoft's schedule API, the same view as Outlook's Scheduling Assistant. In Microsoft 365 that covers colleagues in your organization; outside it, the person must share their calendar with you. Events are created only in the connected account's own calendars.
- `update` and `delete` find the event by its ID in any of your calendars, so they do not use this field.

### Available time slots

On November 6, the default read covers the current time on November 6 through **December 1, 00:00**, in the selected time zone. Pass `ocEndDate` to request seven days, extend into the next month, or shorten the window. A range over 60 days, an inverted range or an invalid date is rejected before calling Microsoft.

Events shown as **Busy**, **Tentative**, **Away** (out of office) or with an unknown status block time. **Free** and **Working elsewhere** events do not, and cancelled meetings never do. Recurring meetings are expanded into their occurrences, and an all-day event blocks its whole days in the selected time zone. Busy intervals are merged and subtracted from the requested window. `available_slots` contains continuous gaps with `start` and `end` timestamps; it does not split them into meeting-sized slots or apply working hours.

A calendar or colleague whose availability cannot be read returns an error, never an empty busy list. Reading availability does not reserve a slot.

```json
{
  "type": "outlookCalendar",
  "data": {
    "label": "Availability",
    "credentialId": "YOUR_OUTLOOK_CALENDAR_CREDENTIAL_ID",
    "ocOperation": "read",
    "ocCalendarId": "primary",
    "ocTimeZone": "Europe/Berlin",
    "ocStartDate": "2026-11-06",
    "ocEndDate": "2026-11-13"
  }
}
```

### Include Busy Event Details

Under **Read Available Time Slots**, enable **Include Busy Event Details** (`ocIncludeBusyDetails: true`) to add each event's `title` and `attendees` to the busy slots. It is **off by default**: event titles are then not requested at all and busy slots keep the `{start, end}` shape.

When enabled, each blocking event becomes its own busy slot with `{start, end, title, attendees}`; overlapping events stay separate so each keeps its details. `attendees` lists the guests' email addresses without rooms and other resources, and is an empty list for an event without guests. For another person's calendar, `title` appears only when their organization shares event subjects and is `null` for private events, and `attendees` is always `null`. `available_slots` and `count` are the same either way.

```json
{
  "start": "2026-11-06T09:00:00+01:00",
  "end": "2026-11-06T09:30:00+01:00",
  "title": "Daily check-in",
  "attendees": ["colleague@contoso.com"]
}
```

For a public booking workflow, keep the option off unless you intend to include event details in the workflow's output and history.

### Book time with me

1. Run a `read` node using the workflow owner's credential and `ocCalendarId: "primary"`.
2. Display `available_slots` in your booking interface. The visitor chooses start/end times and enters an email address.
3. Pass `email`, `startTime` and `endTime` as workflow inputs. Recheck that selected range before creating the event, because availability may have changed.
4. Run `create` with the **same owner's credential**. The visitor does not need a Microsoft account; their email is an attendee and receives a Teams invitation.

```json
{
  "type": "outlookCalendar",
  "data": {
    "label": "Booking",
    "credentialId": "YOUR_OUTLOOK_CALENDAR_CREDENTIAL_ID",
    "ocOperation": "create",
    "ocCalendarId": "primary",
    "ocTimeZone": "Europe/Berlin",
    "ocTitle": "Intro call",
    "ocDescription": "A meeting booked through Heym",
    "ocAttendees": "$input.email",
    "ocStartTime": "$input.startTime",
    "ocEndTime": "$input.endTime",
    "ocTeamsMeeting": true
  }
}
```

Outlook emails the invitations when the event is created, the changes when it is updated, and cancellations when it is deleted, as long as the connected account organized the meeting. Deleting a meeting someone else organized only removes it from this calendar. A free/busy check and event creation are separate requests, so simultaneous bookings require coordination in the booking application.

### Teams meetings

**Add Teams meeting** is on by default. Work and school accounts get a Teams meeting with the join link in the invitation. Personal Outlook.com accounts cannot create Teams meetings through Microsoft Graph, so the event is created without one and `teams_status` is `unavailable`. Turn the option off for in-person meetings.

### Updates

Empty fields keep their existing values. Supply both start/end times to reschedule. A supplied attendee list replaces the current guests; use the JSON string `[]` to remove them all. The Teams meeting is kept. Replacing the description of a Teams meeting replaces the invitation text, including the join details Teams added to it; `teams_url` keeps working.

## Output

| Operation | Output fields |
| --- | --- |
| `read` | `available_slots`, `busy_slots`, `count`, `calendar_id`, `time_zone`, `start`, `end` |
| `create` | `event_id`, `teams_url`, `teams_status`, `web_link`, `event`, `calendar_id` |
| `update` | `event_id`, `teams_url`, `teams_status`, `web_link`, `event` |
| `delete` | `event_id`, `deleted: true` |

`teams_status` is `ready` when the join link is available, `pending` when Teams has not returned it yet, `unavailable` when the account cannot create Teams meetings, and `off` when the event has none. `web_link` opens the event in Outlook on the web. Event IDs stay the same when the event moves to another calendar.

Use `$Availability.available_slots` or `$Booking.teams_url` in downstream nodes. Every operation also returns `status: "success"` and its `operation`.

## Related

- [Google Meet](google-meet-node.md) for Google Calendar
- [Outlook Trigger](outlook-trigger-node.md)
- [Credentials](../reference/credentials.md)
- [Integrations](../reference/integrations.md)
- [Credentials Sharing](../reference/credentials-sharing.md)
- [Agent](agent-node.md)
