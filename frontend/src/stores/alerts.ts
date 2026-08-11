import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { alertsApi } from "@/services/api";
import type {
  Alert,
  AlertDraftRequest,
  AlertDraftResponse,
  AlertEvent,
  AlertEventTimeRange,
  AlertListFilters,
  AlertPayload,
  AlertPreview,
  AlertPreviewRequest,
  AlertUpdatePayload,
} from "@/types/alerts";

function errorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object" && "response" in error) {
    const response = (error as { response?: { data?: { detail?: unknown } } }).response;
    const detail = response?.data?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string };
      if (typeof first?.msg === "string") return first.msg;
    }
  }
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export const useAlertsStore = defineStore("alerts", () => {
  const alerts = ref<Alert[]>([]);
  const total = ref(0);
  const events = ref<AlertEvent[]>([]);
  const unacknowledgedCount = ref(0);
  const loading = ref(false);
  const eventsLoading = ref(false);
  const error = ref<string | null>(null);

  const triggeredAlerts = computed((): Alert[] =>
    alerts.value.filter((alert) => alert.state === "triggered" && alert.enabled),
  );

  async function fetchAlerts(filters: AlertListFilters = {}): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const response = await alertsApi.list(filters);
      alerts.value = response.items;
      total.value = response.total;
    } catch (err: unknown) {
      error.value = errorMessage(err, "Could not load alerts");
    } finally {
      loading.value = false;
    }
  }

  async function fetchEvents(
    params: { unacknowledged?: boolean; time_range?: AlertEventTimeRange; limit?: number } = {},
  ): Promise<void> {
    eventsLoading.value = true;
    try {
      const response = await alertsApi.listAllEvents(params);
      events.value = response.items;
      unacknowledgedCount.value = response.unacknowledged;
    } catch (err: unknown) {
      error.value = errorMessage(err, "Could not load alert history");
    } finally {
      eventsLoading.value = false;
    }
  }

  async function createAlert(payload: AlertPayload): Promise<Alert> {
    const created = await alertsApi.create(payload);
    alerts.value = [created, ...alerts.value];
    total.value += 1;
    return created;
  }

  async function updateAlert(alertId: string, payload: AlertUpdatePayload): Promise<Alert> {
    const updated = await alertsApi.update(alertId, payload);
    alerts.value = alerts.value.map((alert) => (alert.id === alertId ? updated : alert));
    return updated;
  }

  async function deleteAlert(alertId: string): Promise<void> {
    await alertsApi.remove(alertId);
    alerts.value = alerts.value.filter((alert) => alert.id !== alertId);
    total.value = Math.max(0, total.value - 1);

    // The alert_events rows go with the alert via ON DELETE CASCADE, so the local
    // firing history has to follow or the deleted alert keeps showing rows until
    // the page is reloaded.
    const orphaned = events.value.filter((event) => event.alert_id === alertId);
    if (orphaned.length > 0) {
      events.value = events.value.filter((event) => event.alert_id !== alertId);
      const stillUnacknowledged = orphaned.filter((event) => !event.acknowledged_at).length;
      unacknowledgedCount.value = Math.max(0, unacknowledgedCount.value - stillUnacknowledged);
    }
  }

  async function toggleEnabled(alert: Alert): Promise<Alert> {
    return updateAlert(alert.id, { enabled: !alert.enabled });
  }

  async function acknowledgeEvent(eventId: string): Promise<void> {
    const updated = await alertsApi.acknowledgeEvent(eventId);
    events.value = events.value.map((event) => (event.id === eventId ? updated : event));
    unacknowledgedCount.value = Math.max(0, unacknowledgedCount.value - 1);
  }

  async function previewCondition(payload: AlertPreviewRequest): Promise<AlertPreview> {
    return alertsApi.preview(payload);
  }

  async function testAlert(alertId: string): Promise<AlertPreview> {
    return alertsApi.test(alertId);
  }

  async function draftFromPrompt(payload: AlertDraftRequest): Promise<AlertDraftResponse> {
    return alertsApi.draft(payload);
  }

  return {
    alerts,
    total,
    events,
    unacknowledgedCount,
    loading,
    eventsLoading,
    error,
    triggeredAlerts,
    fetchAlerts,
    fetchEvents,
    createAlert,
    updateAlert,
    deleteAlert,
    toggleEnabled,
    acknowledgeEvent,
    previewCondition,
    testAlert,
    draftFromPrompt,
  };
});
