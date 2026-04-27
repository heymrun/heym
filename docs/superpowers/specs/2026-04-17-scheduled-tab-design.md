# Scheduled Tab — Design Spec
**Date:** 2026-04-17  
**Status:** Approved

## Overview

A new "Scheduled" tab in the Heym dashboard that displays active cron workflows on an interactive calendar. Users can switch between day, week, and month views, see when each workflow will next run, and navigate directly to the canvas by clicking an event block.

---

## Decisions

| Question | Decision |
|---|---|
| Layout style | Calendar Grid (Google Calendar-style) |
| Past executions | Hidden — future occurrences only |
| Inactive cron workflows | Hidden — active cron nodes only |
| Event block content | Workflow name only; cron expression on hover tooltip |
| Occurrence density | Auto visual density — collapse to `+N more` when too many |
| Occurrence computation | Backend (Approach 1): `GET /api/schedules?start=&end=` returns flat event list |

---

## Architecture & Data Flow

### Backend
1. `GET /api/schedules?start=<ISO8601>&end=<ISO8601>` — authenticated via `get_current_user`.
2. Fetch all of the user's workflows; scan each `nodes` JSON array for nodes where `type == "cron"` and `data.active != false`.
3. For each qualifying cron node, use `croniter(expr, start_dt)` and iterate `get_next()` to collect all occurrences within `[start, end]`.
4. Timezone: reuse `get_configured_timezone()` from `cron_scheduler.py`.
5. Return `List[ScheduleEvent]`.

### Frontend
1. `schedules` added to `validTabs` in `DashboardView.vue`; sidebar gets a calendar icon entry.
2. `ScheduledView.vue` owns `activeView: 'day' | 'week' | 'month'` and `currentDate`.
3. On view change or date navigation, the view calls `GET /api/schedules` with the new `start`/`end` window.
4. Events are rendered in `CalendarGrid.vue`. Overflow collapses to `+N more`.
5. Clicking any event block navigates to `/workflows/{workflow_id}`.

---

## Backend API

### Endpoint
```
GET /api/schedules
Auth: Bearer JWT (get_current_user)

Query params:
  start  string  ISO8601 datetime, required
  end    string  ISO8601 datetime, required
         Constraint: end > start, max range 62 days

Response 200:
{
  "events": [
    {
      "workflow_id": "uuid",
      "workflow_name": "Daily Sync",
      "scheduled_at": "2026-04-18T06:00:00+00:00"
    }
  ],
  "total": 42
}

Response 422: start >= end, or range > 62 days
```

### New Pydantic Schemas (schemas.py)
```python
class ScheduleEvent(BaseModel):
    workflow_id: UUID
    workflow_name: str
    scheduled_at: datetime

class ScheduleListResponse(BaseModel):
    events: List[ScheduleEvent]
    total: int
```

### New Router File
`backend/app/api/schedules.py` — registered in `app/main.py` under prefix `/api`.

---

## Backend Unit Tests (`tests/test_schedules_api.py`)

| Test case | Expected |
|---|---|
| Active cron node → occurrence list | Returns occurrences within range |
| `active=false` node → filtered out | Returns empty |
| No cron node → filtered out | Returns empty |
| `start >= end` | 422 validation error |
| Range > 62 days | 422 validation error |
| Hourly cron (`0 * * * *`), day range | Returns 24 occurrences |
| Multiple workflows, each with cron | All occurrences merged and returned |

---

## Frontend Components

```
frontend/src/
  views/
    ScheduledView.vue          # Main view; owns activeView + currentDate state
  components/
    Calendar/
      CalendarGrid.vue         # Day/week/month grid container
      CalendarEventBlock.vue   # Single event block (name + hover tooltip with cron expr)
      CalendarDayColumn.vue    # Hour-row column for day/week view
      CalendarMonthCell.vue    # Day cell for month view
  services/
    schedules.ts               # API client: getScheduleEvents(start, end)
  types/
    schedule.ts                # ScheduleEvent, CalendarView types
```

### View Behaviours

| View | Grid | Overflow rule |
|---|---|---|
| Day | 24 hour rows × 1 column | >3 events/slot → `+N more` |
| Week | 24 hour rows × 7 columns | >2 events/slot → collapse |
| Month | 6×7 day cells | badge list per cell, excess `+N` |

### Navigation Controls
`< Prev` · `Today` · `Next >` buttons shift the date window and re-fetch.

### Event Block
- Shows workflow name only.
- Hover: shadcn `Tooltip` with cron expression string.
- Click: `router.push({ name: 'workflow', params: { id } })`.
- Color: single accent color (no per-workflow color coding — kept simple).

### DashboardView.vue Changes
- Add `'schedules'` to `validTabs` array.
- Add sidebar item: `CalendarClock` icon + label "Scheduled".
- Route: `?tab=schedules` renders `<ScheduledView />`.

---

## heymweb Landing Page

Add a new feature highlight to the capabilities/features section:

- **Heading:** "Visual Schedule View"
- **Body:** See all your active cron workflows on a calendar. Switch between day, week, and month views. Know exactly when each workflow runs next — click to jump straight to the canvas.
- **Visual:** Calendar icon or screenshot of the Scheduled tab.

---

## Documentation (heym-documentation skill)

- New section in workflow docs: "Scheduled Tab" — how to activate a cron node, what the calendar shows, how to navigate views, how to jump to canvas.
- API reference entry for `GET /api/schedules`.

---

## Out of Scope

- Editing cron expressions from the Scheduled tab (done in canvas Properties Panel).
- Pausing/resuming workflows from the calendar.
- Past execution history in the calendar.
- Per-workflow color coding.
