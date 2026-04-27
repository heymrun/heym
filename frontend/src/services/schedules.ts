import api from "@/services/api";

import type { ScheduleListResponse } from "@/types/schedule";

export async function getScheduleEvents(
  start: Date,
  end: Date,
  includeShared: boolean = true,
): Promise<ScheduleListResponse> {
  const response = await api.get<ScheduleListResponse>("/schedules", {
    params: {
      start: start.toISOString(),
      end: end.toISOString(),
      include_shared: includeShared,
    },
  });
  return response.data;
}
