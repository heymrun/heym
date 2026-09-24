<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { X } from "lucide-vue-next";

import ChartRenderer from "@/components/Dashboards/ChartRenderer.vue";
import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import { CHART_TYPE_EXAMPLES, chartTypeExample } from "@/lib/chartTypeExamples";
import type { ChartPayload, WidgetCreateRequest } from "@/types/dashboard";

const emit = defineEmits<{
  (e: "close"): void;
  (e: "create", body: WidgetCreateRequest): void;
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

const title = ref("New widget");
const description = ref("");
const chartType = ref<ChartPayload["type"]>("bar");

const chartTypeOptions = CHART_TYPE_EXAMPLES.map(({ value, label }) => ({ value, label }));
const example = computed(() => chartTypeExample(chartType.value));

function submit(): void {
  emit("create", {
    title: title.value.trim() || "Untitled",
    description: description.value.trim() ? description.value.trim() : null,
    chart_type: chartType.value,
    layout: { x: 0, y: 0, w: 4, h: 4 },
    cache_ttl_seconds: 300,
  });
}
</script>

<template>
  <Teleport to="body">
    <div
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      @click.self="emit('close')"
    >
      <div class="mx-4 max-h-[calc(100vh-2rem)] w-full max-w-md overflow-y-auto rounded-lg border bg-card p-5 shadow-lg">
        <div class="mb-4 flex items-center justify-between">
          <h2 class="text-base font-semibold">
            Add widget
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
              placeholder="Optional. Shown on the canvas, not on the grid."
            />
          </div>
          <div class="space-y-1">
            <label class="text-sm font-medium">Chart type</label>
            <Select
              v-model="chartType"
              :options="chartTypeOptions"
            />
            <p
              class="pt-1 text-xs text-muted-foreground"
              data-testid="add-widget-chart-hint"
            >
              {{ example.hint }}
            </p>
            <div
              class="relative mt-1 rounded-md border border-dashed bg-background/60 p-2"
              data-testid="add-widget-chart-example"
            >
              <span
                class="absolute right-2 top-1.5 z-10 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-muted-foreground"
              >
                Example
              </span>
              <!-- Keyed on the type: ApexCharts does not redraw cleanly across chart types. -->
              <div class="h-40">
                <ChartRenderer
                  :key="chartType"
                  :payload="example.payload"
                />
              </div>
            </div>
          </div>
        </div>

        <div class="mt-5 flex justify-end gap-2">
          <Button
            variant="ghost"
            @click="emit('close')"
          >
            Cancel
          </Button>
          <Button @click="submit">
            Create &amp; edit
          </Button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
