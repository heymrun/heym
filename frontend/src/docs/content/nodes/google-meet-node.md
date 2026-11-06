# Google Meet

Find available Google Calendar time slots and create, update or delete meeting invitations with Google Meet links, attendee emails and selected times. The connected Google account owns the event; attendees receive invitations by email.

## Connect your account

1. In [Google Cloud Console](https://console.cloud.google.com), enable the **Google Calendar API**.
2. Configure the OAuth consent screen and create a **Web application** OAuth client. Add your Google account as a test user if the app is in testing mode.
3. Register `https://your-heym-domain/api/credentials/google-meet/oauth/callback` as an authorized redirect URI. For local development, use your browser's Heym origin with the same path.
4. Open **Dashboard → Credentials → New → Google Meet (OAuth2)**, enter a name, Client ID and Client Secret, then click **Connect** and sign in with Google.
5. Grant both permissions: Calendar events (`calendar.events`) and calendar availability (`calendar.events.freebusy`). Select this credential on the node.

Tokens are encrypted in storage and refreshed automatically. This is a separate credential from Google AI, Sheets or Drive. A calendar must support Google Meet conferencing for creation to succeed.

## Operations

| Operation | Behavior | Required fields |
| --- | --- | --- |
| `read` | Return available and busy intervals for a calendar | Credential |
| `create` | Create a timed event with a new Meet conference and email invitations | Title, start time, end time |
| `update` | Patch supplied event fields and notify guests | Event ID and at least one changed field |
| `delete` | Delete the event and notify guests of cancellation | Event ID |

## Configuration

The text fields below accept expressions. All fields, including the boolean title option, can be supplied by an Agent when this node is attached as a tool.

| Field | Default | Purpose |
| --- | --- | --- |
| `gmCalendarId` | `primary` | Connected account's primary calendar, or an accessible calendar ID/email |
| `gmTimeZone` | `UTC` | IANA zone, such as `Europe/Berlin`, used for local dates and response times |
| `gmStartDate` | Current time | Read range start, as an ISO date or datetime |
| `gmEndDate` | First day of the following month at midnight | Exclusive read range end; maximum range is 60 calendar days |
| `gmIncludeBusyTitles` | `false` | Read only: opt in to event titles in `busy_slots`; boolean, not an expression field |
| `gmEventId` | Empty | Calendar event ID for update/delete; use the returned `event_id`, not a Meet URL |
| `gmTitle` | Empty | Invitation title; required on create |
| `gmDescription` | Empty | Invitation description |
| `gmStartTime` | Empty | Meeting start, for example `2026-11-10T14:00:00+01:00` |
| `gmEndTime` | Empty | Meeting end; must follow start |
| `gmAttendees` | Empty | Comma/semicolon/newline-separated emails or a JSON array of email strings |
| `gmLocation` | Empty | Optional meeting location alongside the Meet conference |

### Available time slots

On November 6, the default read covers the current time on November 6 through **December 1, 00:00**, in the selected time zone. Pass `gmEndDate` to request seven days, extend into the next month, or shorten the window. A range over 60 days, an inverted range or an invalid date is rejected before calling Google. An explicit `gmStartDate` also controls the month used for the default end.

The result is based on Google's **free/busy** API. Busy intervals, including all-day and recurring events reported by Google, are merged and subtracted from the requested window. `available_slots` contains continuous gaps with `start` and `end` timestamps; it does not split them into meeting-sized slots or apply business hours. A booking interface can split those gaps into its own durations and working hours.

Use a person's calendar email as `gmCalendarId` only when the connected account has permission to view that calendar's availability. An inaccessible calendar returns an error, never an empty busy list. Reading availability does not reserve a slot.

```json
{
  "type": "googleMeet",
  "data": {
    "label": "Availability",
    "credentialId": "YOUR_GOOGLE_MEET_CREDENTIAL_ID",
    "gmOperation": "read",
    "gmCalendarId": "primary",
    "gmTimeZone": "Europe/Berlin",
    "gmStartDate": "2026-11-06",
    "gmEndDate": "2026-11-13"
  }
}
```

### Include busy event titles

Under **Read Available Time Slots**, enable **Include Busy Event Titles** (`gmIncludeBusyTitles: true`) to add the Calendar item's `title` to each busy slot. This option is **off by default**, including for existing workflows: no event-details request is made and busy slots keep their original `{start, end}` shape.

When enabled, the node also reads the Calendar events list in the same time window, including recurring occurrences and all result pages. Each visible blocking event becomes a busy slot with `{start, end, title}`. Overlapping or adjacent events stay separate so each keeps its own title. Busy time without visible event details remains present with `title: null`; cancelled events and events marked as available do not supply busy titles. `available_slots`, its `count`, and the 60-day limit remain based on the same free/busy data.

```json
{
  "start": "2026-11-06T21:15:00+01:00",
  "end": "2026-11-06T21:30:00+01:00",
  "title": "Daily check-in"
}
```

Google's calendar sharing rules still apply. Private event titles may be hidden, and a failed events-list request fails the opted-in read instead of returning incomplete data. The existing Google Meet credential's `calendar.events` scope supports the events-list call; no new credential type or scope is required. See [Google's Events list reference](https://developers.google.com/workspace/calendar/api/v3/reference/events/list). Descriptions and guest lists are not requested.

For a public booking workflow, keep the option off unless you intend to include event titles in the workflow's output and history. Downstream nodes can access a title with `$Availability.busy_slots[0].title`.

### Book a calendar with me

1. Run a `read` node using the workflow owner's credential and `gmCalendarId: "primary"`.
2. Display `available_slots` in your booking interface. The visitor chooses start/end times and enters an email address.
3. Pass `email`, `startTime` and `endTime` as workflow inputs. Recheck that selected range before creating the event, because availability may have changed.
4. Run `create` with the **same owner's credential**. The visitor does not need a Google credential; their email is an attendee.

```json
{
  "type": "googleMeet",
  "data": {
    "label": "Booking",
    "credentialId": "YOUR_GOOGLE_MEET_CREDENTIAL_ID",
    "gmOperation": "create",
    "gmCalendarId": "primary",
    "gmTimeZone": "Europe/Berlin",
    "gmTitle": "Meet with me",
    "gmDescription": "A meeting booked through Heym",
    "gmAttendees": "$input.email",
    "gmStartTime": "$input.startTime",
    "gmEndTime": "$input.endTime"
  }
}
```

Create, update and delete use Google's `sendUpdates=all`: invites, changes and cancellations are sent to guests. Their calendar's invitation settings determine when an invitation appears on their calendar. A free/busy check and event creation are separate Google requests, so simultaneous bookings require coordination in the booking application.

### Updates

Empty fields keep their existing values. Supply both start/end times to reschedule. A supplied attendee list replaces the current guests; use the JSON string `[]` to remove them all. Existing Meet conference data is preserved. Description and location can be replaced with nonempty text.

## Output

| Operation | Output fields |
| --- | --- |
| `read` | `available_slots`, `busy_slots`, `count`, `calendar_id`, `time_zone`, `start`, `end` |
| `create`, `update` | `event_id`, `meet_url`, `conference_status`, `event`, `calendar_id` |
| `delete` | `event_id`, `calendar_id`, `deleted: true` |

Meet conference creation can be asynchronous: `conference_status` may be `pending` and `meet_url` may initially be empty. The Calendar event remains the source of truth while Google finishes creating the link.

Use `$Availability.available_slots` or `$Booking.meet_url` in downstream nodes. Every operation also returns `status: "success"` and its `operation`.

## Related

- [Credentials](../reference/credentials.md)
- [Integrations](../reference/integrations.md)
- [Credentials Sharing](../reference/credentials-sharing.md)
- [Input](input-node.md)
- [Output](output-node.md)
