export type CalendarView = "day" | "week" | "month";

export interface ScheduleEvent {
  workflow_id: string;
  workflow_name: string;
  description?: string | null;
  scheduled_at: string; // ISO8601
}

export interface ScheduleListResponse {
  events: ScheduleEvent[];
  total: number;
}
