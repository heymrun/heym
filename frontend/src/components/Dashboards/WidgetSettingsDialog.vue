<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { X } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import type { DashboardSummary, DashboardWidget, WidgetUpdateRequest } from "@/types/dashboard";

const props = defineProps<{
  widget: DashboardWidget;
  /** Dashboards a table widget's rows can link to. */
  dashboards: DashboardSummary[];
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "save", payload: WidgetUpdateRequest): void;
}>();

function onKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.stopPropagation();
    emit("close");
  }
}

// Capture phase so Escape reaches us before any ancestor keydown handler can
// stopPropagation (several exist in the dashboard view) and swallow the event.
onMounted(() => window.addEventListener("keydown", onKeydown, true));
onUnmounted(() => window.removeEventListener("keydown", onKeydown, true));

const title = ref(props.widget.title);
const description = ref(props.widget.description ?? "");
const cacheTtlSeconds = ref(props.widget.cache_ttl_seconds);

const isTable = computed<boolean>(() => props.widget.chart_type === "table");
const linkDashboardId = ref<string | undefined>(props.widget.link_dashboard_id ?? undefined);
const linkRecordField = ref(props.widget.link_record_field ?? "");
const linkLabelField = ref(props.widget.link_label_field ?? "");
const linkOptions = computed(() => {
  const options = props.dashboards.map((dashboard) => ({ value: dashboard.id, label: dashboard.name }));
  const current = props.widget.link_dashboard_id;
  // Keep a link to a dashboard the editor can no longer open visible, so it can be removed.
  if (current && !options.some((option) => option.value === current)) {
    options.push({ value: current, label: "A dashboard you cannot open" });
  }
  return options;
});
const canSave = computed<boolean>(
  () => !isTable.value || !linkDashboardId.value || Boolean(linkRecordField.value.trim()),
);

function linkUpdate(): WidgetUpdateRequest {
  if (!isTable.value) return {};
  if (!linkDashboardId.value) {
    return props.widget.link_dashboard_id ? { link_dashboard_id: null } : {};
  }
  return {
    link_dashboard_id: linkDashboardId.value,
    link_record_field: linkRecordField.value.trim(),
    link_label_field: linkLabelField.value.trim() || null,
  };
}

function save(): void {
  if (!canSave.value) return;
  emit("save", {
    title: title.value.trim() || "Untitled",
    description: description.value.trim() ? description.value.trim() : null,
    cache_ttl_seconds: Number(cacheTtlSeconds.value) || 0,
    ...linkUpdate(),
  });
}
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      @click.self="emit('close')"
    >
      <div class="w-full max-w-md rounded-lg border bg-card p-5 shadow-lg">
        <div class="mb-4 flex items-center justify-between">
          <h2 class="text-base font-semibold">
            Widget settings
          </h2>
          <button
            class="rounded p-1 text-muted-foreground hover:bg-accent"
            @click="emit('close')"
          >
            <X class="h-4 w-4" />
          </button>
        </div>

        <div class="space-y-3">
          <div class="space-y-1">
            <label class="text-sm font-medium">Title</label>
            <Input v-model="title" />
          </div>
          <div class="space-y-1">
            <label class="text-sm font-medium">Description</label>
            <textarea
              v-model="description"
              rows="2"
              class="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-1 focus:ring-ring"
              placeholder="Shown on the canvas; not displayed on the dashboard grid."
            />
          </div>
          <div class="space-y-1">
            <label class="text-sm font-medium">Cache duration (seconds)</label>
            <Input
              v-model.number="cacheTtlSeconds"
              type="number"
              min="0"
            />
            <p class="text-xs text-muted-foreground">
              How long a computed result is reused before the workflow runs again. Use the widget's
              Refresh button to bypass the cache.
            </p>
          </div>
          <div
            v-if="isTable"
            class="space-y-2 border-t pt-3"
            data-testid="widget-row-link"
          >
            <label class="text-sm font-medium">Row link</label>
            <Select
              v-model="linkDashboardId"
              :options="linkOptions"
              placeholder="No link"
              clearable
              clear-aria-label="Remove row link"
            />
            <template v-if="linkDashboardId">
              <Input
                v-model="linkRecordField"
                aria-label="Record column"
                placeholder="Column that holds the record, e.g. id"
              />
              <Input
                v-model="linkLabelField"
                aria-label="Label column"
                placeholder="Column that names it (optional)"
              />
            </template>
            <p class="text-xs text-muted-foreground">
              Clicking a row opens that dashboard for the row's record. Its widgets read the record
              as $page.record.
            </p>
          </div>
        </div>

        <div class="mt-5 flex justify-end gap-2">
          <Button
            variant="ghost"
            @click="emit('close')"
          >
            Cancel
          </Button>
          <Button
            :disabled="!canSave"
            @click="save"
          >
            Save
          </Button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
