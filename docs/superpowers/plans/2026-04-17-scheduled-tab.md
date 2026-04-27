# Scheduled Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Scheduled" dashboard tab that shows active cron workflows on a Google Calendar-style grid with day/week/month views, computing future occurrences server-side and navigating to the canvas on click.

**Architecture:** Backend exposes `GET /api/schedules?start=&end=` which scans user workflows for active cron nodes, generates future occurrences via `croniter`, and returns a flat list of `ScheduleEvent` objects. The frontend `ScheduledView.vue` manages date navigation state and fetches events on each view/date change, rendering them in `CalendarGrid.vue` which delegates to per-view sub-components.

**Tech Stack:** Python 3.11+ / FastAPI / croniter / Pydantic (backend); Vue 3 Composition API / TypeScript strict / shadcn-vue Tooltip / lucide-vue-next CalendarClock icon (frontend); Next.js / lucide-react (heymweb).

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| CREATE | `backend/app/api/schedules.py` | `GET /schedules` route, occurrence generation |
| MODIFY | `backend/app/models/schemas.py` | `ScheduleEvent`, `ScheduleListResponse` schemas |
| MODIFY | `backend/app/main.py` | Import + register schedules router |
| CREATE | `backend/tests/test_schedules_api.py` | All backend unit tests |
| CREATE | `frontend/src/types/schedule.ts` | `ScheduleEvent`, `CalendarView` TS types |
| CREATE | `frontend/src/services/schedules.ts` | `getScheduleEvents(start, end)` API client |
| CREATE | `frontend/src/views/ScheduledView.vue` | View state: activeView, currentDate, fetch |
| CREATE | `frontend/src/components/Calendar/CalendarGrid.vue` | Day/week/month switcher + grid container |
| CREATE | `frontend/src/components/Calendar/CalendarEventBlock.vue` | Single event block + tooltip + click handler |
| CREATE | `frontend/src/components/Calendar/CalendarDayColumn.vue` | Hour-row column for day/week views |
| CREATE | `frontend/src/components/Calendar/CalendarMonthCell.vue` | Day cell for month view |
| MODIFY | `frontend/src/components/Layout/DashboardNav.vue` | Add `schedules` tab entry + `activeTab` recognition |
| MODIFY | `frontend/src/views/DashboardView.vue` | Add `schedules` to validTabs + render `ScheduledView` |
| MODIFY | `heymweb/src/components/sections/FeaturesSection.tsx` | Add "Visual Schedule View" to `secondaryFeatures` |

---

## Task 1: Add Pydantic schemas

**Files:**
- Modify: `backend/app/models/schemas.py` (append at end of file)

- [ ] **Step 1: Append the two new schemas at the end of `backend/app/models/schemas.py`**

```python
class ScheduleEvent(BaseModel):
    workflow_id: uuid.UUID
    workflow_name: str
    scheduled_at: datetime


class ScheduleListResponse(BaseModel):
    events: list[ScheduleEvent]
    total: int
```

- [ ] **Step 2: Verify no import errors**

```bash
cd backend && uv run python -c "from app.models.schemas import ScheduleEvent, ScheduleListResponse; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/schemas.py
git commit -m "feat: add ScheduleEvent and ScheduleListResponse schemas"
```

---

## Task 2: Write failing backend tests

**Files:**
- Create: `backend/tests/test_schedules_api.py`

- [ ] **Step 1: Create the test file**

```python
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.api.schedules import _get_schedule_events
from app.models.schemas import ScheduleEvent


def _make_workflow(nodes: list[dict], name: str = "Test WF") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), name=name, nodes=nodes)


def _cron_node(expr: str, active: bool = True) -> dict:
    return {"type": "cron", "id": str(uuid.uuid4()), "data": {"cronExpression": expr, "active": active}}


class TestGetScheduleEvents(unittest.IsolatedAsyncioTestCase):

    async def test_active_cron_returns_occurrences(self) -> None:
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 17, 23, 59, 59, tzinfo=timezone.utc)
        workflows = [_make_workflow([_cron_node("0 * * * *")])]
        events = await _get_schedule_events(workflows, start, end)
        self.assertEqual(len(events), 24)  # hours 00:00..23:00 inclusive (start boundary included)
        self.assertIsInstance(events[0], ScheduleEvent)

    async def test_inactive_cron_filtered_out(self) -> None:
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 17, 23, 59, 59, tzinfo=timezone.utc)
        workflows = [_make_workflow([_cron_node("0 * * * *", active=False)])]
        events = await _get_schedule_events(workflows, start, end)
        self.assertEqual(len(events), 0)

    async def test_no_cron_node_filtered_out(self) -> None:
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 17, 23, 59, 59, tzinfo=timezone.utc)
        workflows = [_make_workflow([{"type": "llm", "id": "n1", "data": {}}])]
        events = await _get_schedule_events(workflows, start, end)
        self.assertEqual(len(events), 0)

    async def test_multiple_workflows_merged(self) -> None:
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 17, 23, 59, 59, tzinfo=timezone.utc)
        workflows = [
            _make_workflow([_cron_node("0 6 * * *")], name="Morning"),
            _make_workflow([_cron_node("0 18 * * *")], name="Evening"),
        ]
        events = await _get_schedule_events(workflows, start, end)
        names = {e.workflow_name for e in events}
        self.assertEqual(names, {"Morning", "Evening"})
        self.assertEqual(len(events), 2)

    async def test_hourly_cron_day_range_returns_correct_count(self) -> None:
        # start=00:00, end=23:59:59 → hits at 00:00 .. 23:00 = 24 hits (start boundary included)
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 4, 17, 23, 59, 59, tzinfo=timezone.utc)
        workflows = [_make_workflow([_cron_node("0 * * * *")])]
        events = await _get_schedule_events(workflows, start, end)
        self.assertEqual(len(events), 24)

    async def test_weekly_cron_week_range(self) -> None:
        # "0 9 * * 1" = every Monday at 09:00
        # 2026-04-20 is a Monday
        start = datetime(2026, 4, 17, 0, 0, 0, tzinfo=timezone.utc)  # Friday
        end = datetime(2026, 4, 24, 0, 0, 0, tzinfo=timezone.utc)    # next Friday
        workflows = [_make_workflow([_cron_node("0 9 * * 1")])]
        events = await _get_schedule_events(workflows, start, end)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].scheduled_at.weekday(), 0)  # Monday


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests — expect ImportError (module doesn't exist yet)**

```bash
cd backend && uv run pytest tests/test_schedules_api.py -v 2>&1 | head -20
```

Expected: `ImportError` or `ModuleNotFoundError` for `app.api.schedules`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add backend/tests/test_schedules_api.py
git commit -m "test: add failing tests for schedules API"
```

---

## Task 3: Implement the schedules router

**Files:**
- Create: `backend/app/api/schedules.py`

- [ ] **Step 1: Create `backend/app/api/schedules.py`**

```python
from datetime import datetime, timedelta, timezone
from typing import Annotated

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import User, Workflow
from app.db.session import get_db
from app.models.schemas import ScheduleEvent, ScheduleListResponse
from app.services.timezone_utils import get_configured_timezone

router = APIRouter()

_MAX_RANGE_DAYS = 62


async def _get_schedule_events(
    workflows: list,
    start: datetime,
    end: datetime,
) -> list[ScheduleEvent]:
    """Generate future ScheduleEvent occurrences for all active cron nodes."""
    tz = get_configured_timezone()
    start_tz = start.astimezone(tz)
    end_tz = end.astimezone(tz)
    events: list[ScheduleEvent] = []

    for workflow in workflows:
        for node in workflow.nodes:
            if node.get("type") != "cron":
                continue
            data = node.get("data", {})
            if data.get("active", True) is False:
                continue
            expr = data.get("cronExpression", "")
            if not expr:
                continue
            try:
                cron = croniter(expr, start_tz - timedelta(seconds=1))
                while True:
                    next_dt = cron.get_next(datetime)
                    if next_dt > end_tz:
                        break
                    events.append(
                        ScheduleEvent(
                            workflow_id=workflow.id,
                            workflow_name=workflow.name,
                            scheduled_at=next_dt.astimezone(timezone.utc),
                        )
                    )
            except Exception:
                continue

    events.sort(key=lambda e: e.scheduled_at)
    return events


@router.get("", response_model=ScheduleListResponse)
async def list_schedules(
    start: Annotated[datetime, Query()],
    end: Annotated[datetime, Query()],
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScheduleListResponse:
    """Return future cron occurrences for the current user within [start, end]."""
    if end <= start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end must be after start",
        )
    if (end - start).days > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Date range must not exceed {_MAX_RANGE_DAYS} days",
        )
    result = await db.execute(
        select(Workflow).where(Workflow.owner_id == current_user.id)
    )
    workflows = result.scalars().all()
    events = await _get_schedule_events(workflows, start, end)
    return ScheduleListResponse(events=events, total=len(events))
```

- [ ] **Step 2: Run the tests — expect them to pass**

```bash
cd backend && uv run pytest tests/test_schedules_api.py -v
```

Expected: All 6 tests `PASSED`.

- [ ] **Step 3: Register the router in `backend/app/main.py`**

Add to the imports block (with the other `app.api` imports, alphabetically after `slack`):
```python
    schedules,
```

Add after the `slack` router registration line (line ~214):
```python
app.include_router(schedules.router, prefix="/api/schedules", tags=["Schedules"])
```

- [ ] **Step 4: Verify server starts without errors**

```bash
cd backend && uv run python -c "from app.main import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: Run full backend check**

```bash
cd backend && uv run ruff check . && uv run ruff format --check .
```

Fix any ruff issues with `uv run ruff check --fix . && uv run ruff format .` if needed.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/schedules.py backend/app/main.py
git commit -m "feat: add GET /api/schedules endpoint with croniter occurrence generation"
```

---

## Task 4: Frontend types and API client

**Files:**
- Create: `frontend/src/types/schedule.ts`
- Create: `frontend/src/services/schedules.ts`

- [ ] **Step 1: Create `frontend/src/types/schedule.ts`**

```typescript
export type CalendarView = 'day' | 'week' | 'month'

export interface ScheduleEvent {
  workflow_id: string
  workflow_name: string
  scheduled_at: string // ISO8601
}

export interface ScheduleListResponse {
  events: ScheduleEvent[]
  total: number
}
```

- [ ] **Step 2: Create `frontend/src/services/schedules.ts`**

```typescript
import api from '@/services/api'
import type { ScheduleListResponse } from '@/types/schedule'

export async function getScheduleEvents(
  start: Date,
  end: Date,
): Promise<ScheduleListResponse> {
  const response = await api.get<ScheduleListResponse>('/schedules', {
    params: {
      start: start.toISOString(),
      end: end.toISOString(),
    },
  })
  return response.data
}
```

> **Note:** `api` is the pre-configured axios instance exported from `frontend/src/services/api.ts` — import it as the default export: `import api from '@/services/api'`. Check that `api.ts` has a default export; if it exports a named `api` constant, adjust to `import { api } from '@/services/api'`.

- [ ] **Step 3: Typecheck**

```bash
cd frontend && bun run typecheck 2>&1 | grep -E "error|schedule"
```

Expected: no errors for `schedule.ts` or `schedules.ts`.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/schedule.ts frontend/src/services/schedules.ts
git commit -m "feat: add schedule types and API client"
```

---

## Task 5: CalendarEventBlock component

**Files:**
- Create: `frontend/src/components/Calendar/CalendarEventBlock.vue`

- [ ] **Step 1: Create the directory and component**

```bash
mkdir -p frontend/src/components/Calendar
```

```vue
<!-- frontend/src/components/Calendar/CalendarEventBlock.vue -->
<script setup lang="ts">
import { useRouter } from 'vue-router'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { ScheduleEvent } from '@/types/schedule'

const props = defineProps<{
  event: ScheduleEvent
  compact?: boolean
}>()

const router = useRouter()

function goToCanvas(): void {
  router.push({ name: 'workflow', params: { id: props.event.workflow_id } })
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
</script>

<template>
  <TooltipProvider>
    <Tooltip>
      <TooltipTrigger as-child>
        <button
          class="w-full text-left rounded px-1.5 py-0.5 bg-violet-900/60 border-l-2 border-violet-400 hover:bg-violet-800/80 transition-colors truncate"
          :class="compact ? 'text-[10px]' : 'text-xs'"
          @click="goToCanvas"
        >
          <span class="font-medium text-violet-100 truncate block">{{ event.workflow_name }}</span>
        </button>
      </TooltipTrigger>
      <TooltipContent side="top" class="text-xs">
        <p class="font-semibold">{{ event.workflow_name }}</p>
        <p class="text-muted-foreground">{{ formatTime(event.scheduled_at) }}</p>
      </TooltipContent>
    </Tooltip>
  </TooltipProvider>
</template>
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && bun run typecheck 2>&1 | grep -i "calendar\|schedule"
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Calendar/CalendarEventBlock.vue
git commit -m "feat: add CalendarEventBlock with tooltip and canvas navigation"
```

---

## Task 6: CalendarDayColumn component

**Files:**
- Create: `frontend/src/components/Calendar/CalendarDayColumn.vue`

- [ ] **Step 1: Create `frontend/src/components/Calendar/CalendarDayColumn.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import CalendarEventBlock from './CalendarEventBlock.vue'
import type { ScheduleEvent } from '@/types/schedule'

const props = defineProps<{
  date: Date
  events: ScheduleEvent[]
  showHourLabels?: boolean
}>()

const HOURS = Array.from({ length: 24 }, (_, i) => i)
const OVERFLOW_THRESHOLD = 3

function eventsForHour(hour: number): ScheduleEvent[] {
  return props.events.filter((e) => new Date(e.scheduled_at).getHours() === hour)
}

function formatHour(h: number): string {
  return `${String(h).padStart(2, '0')}:00`
}

const isToday = computed(() => {
  const now = new Date()
  return (
    props.date.getFullYear() === now.getFullYear() &&
    props.date.getMonth() === now.getMonth() &&
    props.date.getDate() === now.getDate()
  )
})
</script>

<template>
  <div class="flex flex-col min-w-0">
    <!-- Column header -->
    <div
      class="sticky top-0 z-10 text-center py-1 text-xs font-medium border-b border-border bg-background"
      :class="isToday ? 'text-violet-400' : 'text-muted-foreground'"
    >
      <slot name="header">
        {{ date.toLocaleDateString([], { weekday: 'short', day: 'numeric' }) }}
      </slot>
    </div>
    <!-- Hour rows -->
    <div
      v-for="hour in HOURS"
      :key="hour"
      class="relative flex gap-0.5 border-b border-border/40 min-h-[40px] px-0.5 py-0.5"
    >
      <span
        v-if="showHourLabels"
        class="absolute -left-9 top-0.5 w-8 text-right text-[10px] text-muted-foreground select-none"
      >
        {{ formatHour(hour) }}
      </span>
      <template v-if="eventsForHour(hour).length <= OVERFLOW_THRESHOLD">
        <CalendarEventBlock
          v-for="event in eventsForHour(hour)"
          :key="event.workflow_id + event.scheduled_at"
          :event="event"
        />
      </template>
      <template v-else>
        <CalendarEventBlock
          v-for="event in eventsForHour(hour).slice(0, OVERFLOW_THRESHOLD)"
          :key="event.workflow_id + event.scheduled_at"
          :event="event"
          compact
        />
        <span class="text-[10px] text-muted-foreground self-center whitespace-nowrap">
          +{{ eventsForHour(hour).length - OVERFLOW_THRESHOLD }} more
        </span>
      </template>
    </div>
  </div>
</template>
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && bun run typecheck 2>&1 | grep -i "calendar\|schedule"
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Calendar/CalendarDayColumn.vue
git commit -m "feat: add CalendarDayColumn with hour rows and overflow collapse"
```

---

## Task 7: CalendarMonthCell component

**Files:**
- Create: `frontend/src/components/Calendar/CalendarMonthCell.vue`

- [ ] **Step 1: Create `frontend/src/components/Calendar/CalendarMonthCell.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import CalendarEventBlock from './CalendarEventBlock.vue'
import type { ScheduleEvent } from '@/types/schedule'

const props = defineProps<{
  date: Date
  events: ScheduleEvent[]
  isCurrentMonth: boolean
}>()

const OVERFLOW_THRESHOLD = 3

const visible = computed(() => props.events.slice(0, OVERFLOW_THRESHOLD))
const overflowCount = computed(() => Math.max(0, props.events.length - OVERFLOW_THRESHOLD))

const isToday = computed(() => {
  const now = new Date()
  return (
    props.date.getFullYear() === now.getFullYear() &&
    props.date.getMonth() === now.getMonth() &&
    props.date.getDate() === now.getDate()
  )
})
</script>

<template>
  <div
    class="flex flex-col gap-0.5 p-1 border border-border/40 min-h-[80px]"
    :class="!isCurrentMonth && 'opacity-40'"
  >
    <span
      class="text-xs font-medium w-5 h-5 flex items-center justify-center rounded-full mb-0.5"
      :class="isToday ? 'bg-violet-500 text-white' : 'text-muted-foreground'"
    >
      {{ date.getDate() }}
    </span>
    <CalendarEventBlock
      v-for="event in visible"
      :key="event.workflow_id + event.scheduled_at"
      :event="event"
      compact
    />
    <span
      v-if="overflowCount > 0"
      class="text-[10px] text-muted-foreground pl-1"
    >
      +{{ overflowCount }} more
    </span>
  </div>
</template>
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && bun run typecheck 2>&1 | grep -i "calendar\|schedule"
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Calendar/CalendarMonthCell.vue
git commit -m "feat: add CalendarMonthCell with overflow badge"
```

---

## Task 8: CalendarGrid component

**Files:**
- Create: `frontend/src/components/Calendar/CalendarGrid.vue`

- [ ] **Step 1: Create `frontend/src/components/Calendar/CalendarGrid.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue'
import CalendarDayColumn from './CalendarDayColumn.vue'
import CalendarMonthCell from './CalendarMonthCell.vue'
import type { CalendarView, ScheduleEvent } from '@/types/schedule'

const props = defineProps<{
  view: CalendarView
  currentDate: Date
  events: ScheduleEvent[]
}>()

function eventsForDate(date: Date): ScheduleEvent[] {
  return props.events.filter((e) => {
    const d = new Date(e.scheduled_at)
    return (
      d.getFullYear() === date.getFullYear() &&
      d.getMonth() === date.getMonth() &&
      d.getDate() === date.getDate()
    )
  })
}

// ── Day view ──────────────────────────────────────────────
const dayDates = computed<Date[]>(() => [new Date(props.currentDate)])

// ── Week view ─────────────────────────────────────────────
const weekDates = computed<Date[]>(() => {
  const d = new Date(props.currentDate)
  const day = d.getDay() // 0=Sun
  const monday = new Date(d)
  monday.setDate(d.getDate() - ((day + 6) % 7)) // shift to Monday
  return Array.from({ length: 7 }, (_, i) => {
    const date = new Date(monday)
    date.setDate(monday.getDate() + i)
    return date
  })
})

// ── Month view ────────────────────────────────────────────
const monthCells = computed<{ date: Date; isCurrentMonth: boolean }[]>(() => {
  const year = props.currentDate.getFullYear()
  const month = props.currentDate.getMonth()
  const firstDay = new Date(year, month, 1)
  const startOffset = (firstDay.getDay() + 6) % 7 // Monday-first
  const cells: { date: Date; isCurrentMonth: boolean }[] = []
  for (let i = -startOffset; i < 42 - startOffset; i++) {
    const date = new Date(year, month, 1 + i)
    cells.push({ date, isCurrentMonth: date.getMonth() === month })
  }
  return cells
})

const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
</script>

<template>
  <!-- Day view -->
  <div v-if="view === 'day'" class="relative pl-10 overflow-y-auto">
    <CalendarDayColumn
      :date="dayDates[0]"
      :events="eventsForDate(dayDates[0])"
      :show-hour-labels="true"
    />
  </div>

  <!-- Week view -->
  <div v-else-if="view === 'week'" class="flex gap-0 overflow-x-auto overflow-y-auto">
    <div class="w-10 shrink-0">
      <!-- spacer for hour labels -->
      <div class="sticky top-0 z-10 h-8 border-b border-border bg-background" />
      <div
        v-for="h in 24"
        :key="h"
        class="h-[40px] flex items-start justify-end pr-1 text-[10px] text-muted-foreground border-b border-border/40"
      >
        {{ String(h - 1).padStart(2, '0') }}:00
      </div>
    </div>
    <CalendarDayColumn
      v-for="date in weekDates"
      :key="date.toISOString()"
      :date="date"
      :events="eventsForDate(date)"
      class="flex-1 min-w-[100px]"
    />
  </div>

  <!-- Month view -->
  <div v-else>
    <!-- Weekday header -->
    <div class="grid grid-cols-7 border-b border-border">
      <div
        v-for="name in DAY_NAMES"
        :key="name"
        class="text-center text-xs font-medium text-muted-foreground py-1"
      >
        {{ name }}
      </div>
    </div>
    <div class="grid grid-cols-7">
      <CalendarMonthCell
        v-for="cell in monthCells"
        :key="cell.date.toISOString()"
        :date="cell.date"
        :events="eventsForDate(cell.date)"
        :is-current-month="cell.isCurrentMonth"
      />
    </div>
  </div>
</template>
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && bun run typecheck 2>&1 | grep -i "calendar\|schedule"
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Calendar/CalendarGrid.vue
git commit -m "feat: add CalendarGrid day/week/month container"
```

---

## Task 9: ScheduledView main view

**Files:**
- Create: `frontend/src/views/ScheduledView.vue`

- [ ] **Step 1: Create `frontend/src/views/ScheduledView.vue`**

```vue
<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import CalendarGrid from '@/components/Calendar/CalendarGrid.vue'
import { getScheduleEvents } from '@/services/schedules'
import type { CalendarView, ScheduleEvent } from '@/types/schedule'

const view = ref<CalendarView>('week')
const currentDate = ref<Date>(new Date())
const events = ref<ScheduleEvent[]>([])
const loading = ref(false)

const viewLabel = computed(() => {
  const d = currentDate.value
  if (view.value === 'day') {
    return d.toLocaleDateString([], { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })
  }
  if (view.value === 'week') {
    const monday = new Date(d)
    monday.setDate(d.getDate() - ((d.getDay() + 6) % 7))
    const sunday = new Date(monday)
    sunday.setDate(monday.getDate() + 6)
    return `${monday.toLocaleDateString([], { month: 'short', day: 'numeric' })} – ${sunday.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}`
  }
  return d.toLocaleDateString([], { month: 'long', year: 'numeric' })
})

function getRange(): { start: Date; end: Date } {
  const d = new Date(currentDate.value)
  if (view.value === 'day') {
    const start = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0)
    const end = new Date(d.getFullYear(), d.getMonth(), d.getDate(), 23, 59, 59)
    return { start, end }
  }
  if (view.value === 'week') {
    const monday = new Date(d)
    monday.setDate(d.getDate() - ((d.getDay() + 6) % 7))
    monday.setHours(0, 0, 0, 0)
    const sunday = new Date(monday)
    sunday.setDate(monday.getDate() + 6)
    sunday.setHours(23, 59, 59, 999)
    return { start: monday, end: sunday }
  }
  // month
  const start = new Date(d.getFullYear(), d.getMonth(), 1, 0, 0, 0)
  const end = new Date(d.getFullYear(), d.getMonth() + 1, 0, 23, 59, 59)
  return { start, end }
}

async function fetchEvents(): Promise<void> {
  loading.value = true
  try {
    const { start, end } = getRange()
    const res = await getScheduleEvents(start, end)
    events.value = res.events
  } catch {
    events.value = []
  } finally {
    loading.value = false
  }
}

function navigate(direction: -1 | 1): void {
  const d = new Date(currentDate.value)
  if (view.value === 'day') d.setDate(d.getDate() + direction)
  else if (view.value === 'week') d.setDate(d.getDate() + direction * 7)
  else d.setMonth(d.getMonth() + direction)
  currentDate.value = d
}

function goToday(): void {
  currentDate.value = new Date()
}

watch([view, currentDate], fetchEvents, { immediate: false })
onMounted(fetchEvents)
</script>

<template>
  <div class="flex flex-col h-full gap-3 p-4">
    <!-- Toolbar -->
    <div class="flex items-center justify-between flex-wrap gap-2">
      <div class="flex items-center gap-2">
        <button
          class="rounded px-2 py-1 text-sm border border-border hover:bg-accent"
          @click="navigate(-1)"
        >
          <ChevronLeft class="w-4 h-4" />
        </button>
        <button
          class="rounded px-3 py-1 text-sm border border-border hover:bg-accent"
          @click="goToday"
        >
          Today
        </button>
        <button
          class="rounded px-2 py-1 text-sm border border-border hover:bg-accent"
          @click="navigate(1)"
        >
          <ChevronRight class="w-4 h-4" />
        </button>
        <span class="text-sm font-medium ml-2">{{ viewLabel }}</span>
      </div>

      <!-- View switcher -->
      <div class="flex items-center gap-1 border border-border rounded-md p-0.5 text-sm">
        <button
          v-for="v in (['day', 'week', 'month'] as CalendarView[])"
          :key="v"
          class="px-3 py-1 rounded capitalize transition-colors"
          :class="view === v ? 'bg-violet-600 text-white' : 'hover:bg-accent text-muted-foreground'"
          @click="view = v"
        >
          {{ v }}
        </button>
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="flex-1 flex items-center justify-center text-muted-foreground text-sm">
      Loading schedule...
    </div>

    <!-- Calendar grid -->
    <div v-else class="flex-1 overflow-auto border border-border rounded-md">
      <CalendarGrid
        :view="view"
        :current-date="currentDate"
        :events="events"
      />
    </div>
  </div>
</template>
```

- [ ] **Step 2: Typecheck**

```bash
cd frontend && bun run typecheck 2>&1 | grep -i "calendar\|schedule\|Scheduled"
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/views/ScheduledView.vue
git commit -m "feat: add ScheduledView with day/week/month navigation"
```

---

## Task 10: Wire into DashboardNav and DashboardView

**Files:**
- Modify: `frontend/src/components/Layout/DashboardNav.vue`
- Modify: `frontend/src/views/DashboardView.vue`

- [ ] **Step 1: Add `CalendarClock` import and `schedules` tab entry in `DashboardNav.vue`**

In the lucide import line, add `CalendarClock`:
```typescript
import {
  Activity,
  BarChart3,
  CalendarClock,
  Database,
  FlaskConical,
  HardDrive,
  Key,
  LayoutTemplate,
  MessageCircle,
  Server,
  Table2,
  Terminal,
  Users,
  Variable,
  Workflow,
} from "lucide-vue-next";
```

Add `schedules` entry to the `tabs` array (after `workflows`, before `templates`):
```typescript
const tabs = [
  { id: "workflows", label: "Workflows", icon: Workflow },
  { id: "schedules", label: "Scheduled", icon: CalendarClock },
  { id: "templates", label: "Templates", icon: LayoutTemplate },
  // ... rest unchanged
] as const;
```

Add `"schedules"` to the `activeTab` computed `tabParam` checks:
```typescript
    tabParam === "schedules" ||
    tabParam === "credentials" ||
    // ... rest unchanged
```

- [ ] **Step 2: Add `schedules` to `validTabs` and `TabKey` in `DashboardView.vue`**

Locate the `validTabs` set (line ~89) and update:
```typescript
const validTabs = new Set([
  "workflows", "schedules", "credentials", "globalvariables", "vectorstores", "mcp",
  "traces", "analytics", "templates", "teams", "logs", "chat", "drive", "datatable",
]);
```

Update `TabKey` union type:
```typescript
type TabKey = "workflows" | "schedules" | "credentials" | "globalvariables" | "vectorstores" | "mcp" | "traces" | "analytics" | "templates" | "teams" | "logs" | "chat" | "drive" | "datatable";
```

- [ ] **Step 3: Import and render `ScheduledView` in `DashboardView.vue`**

Add import near other view imports at the top of `<script setup>`:
```typescript
import ScheduledView from '@/views/ScheduledView.vue'
```

In the template where other panels are rendered (after `<TracesPanel v-else-if="activeTab === 'traces'" />`), add:
```html
<ScheduledView v-else-if="activeTab === 'schedules'" />
```

- [ ] **Step 4: Typecheck and lint**

```bash
cd frontend && bun run typecheck && bun run lint
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/Layout/DashboardNav.vue frontend/src/views/DashboardView.vue
git commit -m "feat: add Scheduled tab to dashboard nav and view"
```

---

## Task 11: heymweb landing page update

**Files:**
- Modify: `heymweb/src/components/sections/FeaturesSection.tsx`

- [ ] **Step 1: Add `CalendarDays` to the lucide import and add the feature entry**

In `FeaturesSection.tsx`, add `CalendarDays` to the lucide import:
```typescript
import { Brain, CalendarDays, Puzzle, GitBranch, Shield, Zap, Database, FileCode, Globe, MessageSquare, Cpu, Lock, Users, Network } from 'lucide-react'
```

Add to the `secondaryFeatures` array (after `Auto Heal`):
```typescript
  { icon: CalendarDays, title: 'Visual Schedule View', description: 'See all active cron workflows on a day, week, or month calendar. Each block shows the workflow name and cron expression on hover — click to jump straight to the canvas.' },
```

- [ ] **Step 2: Verify TypeScript builds**

```bash
cd /Users/mbakgun/Projects/heym/heymweb && bun run build 2>&1 | tail -5
```

Expected: build succeeds with no errors.

- [ ] **Step 3: Commit**

```bash
cd /Users/mbakgun/Projects/heym/heymweb
git add src/components/sections/FeaturesSection.tsx
git commit -m "feat: add Visual Schedule View to features section"
```

---

## Task 12: Documentation via heym-documentation skill

- [ ] **Step 1: Invoke heym-documentation skill**

Run the `heym-documentation` skill to update docs with:
- A new "Scheduled Tab" section covering: how to activate a cron node, what the calendar shows, day/week/month navigation, and how clicking navigates to the canvas.
- API reference entry for `GET /api/schedules` (query params, response shape, 422 cases).

---

## Task 13: Final check

- [ ] **Step 1: Run full backend test suite**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && ./run_tests.sh
```

Expected: all tests pass.

- [ ] **Step 2: Run full check**

```bash
cd /Users/mbakgun/Projects/heym/heymrun && ./check.sh
```

Expected: lint + typecheck + tests all pass.

- [ ] **Step 3: Start services and manually verify**

```bash
./run.sh
```

Open http://localhost:4017 → Dashboard → click "Scheduled" tab.
- Day/Week/Month buttons switch views.
- `< Prev` / `Today` / `Next >` navigate dates.
- Workflows with active cron nodes appear as event blocks.
- Clicking an event block navigates to the workflow canvas.
- Hover shows cron expression tooltip.

- [ ] **Step 4: Commit if any final tweaks needed**

```bash
git add -p && git commit -m "chore: final polish for scheduled tab"
```
