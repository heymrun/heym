<script setup lang="ts">
import { computed, inject, onBeforeUnmount, onMounted, ref, watch } from "vue";
import axios from "axios";
import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-vue-next";
import { useRouter } from "vue-router";

import type { HitlWidgetItem } from "@/types/dashboard";
import { setHitlHistoryTargetKey } from "@/components/Dashboards/hitlHistory";
import HitlReviewActions from "@/components/Dashboards/HitlReviewActions.vue";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { renderChartMarkdown } from "@/lib/markdown";
import { hitlApi } from "@/services/api";

const props = defineProps<{
  seedItems?: HitlWidgetItem[];
  seedTotal?: number;
}>();

const router = useRouter();
const reportHistoryTarget = inject(setHitlHistoryTargetKey, null);
const preview = computed(() => props.seedItems !== undefined);
const items = ref<HitlWidgetItem[]>(props.seedItems ?? []);
const pendingTotal = ref(props.seedTotal ?? props.seedItems?.length ?? 0);
const index = ref(0);
const loading = ref(false);
const loadError = ref("");
const actionError = ref("");
const submitting = ref(false);
const editing = ref(false);
const editText = ref("");
const dragStartX = ref<number | null>(null);
const current = computed(() => items.value[index.value] ?? null);
const atStart = computed(() => index.value <= 0);
const atEnd = computed(() => items.value.length === 0 || index.value >= items.value.length - 1);
const positionLabel = computed(() => {
  if (items.value.length === 0) return `${pendingTotal.value} pending`;
  return `${index.value + 1}/${items.value.length} pending`;
});
const currentHtml = computed(() => renderChartMarkdown(current.value?.text ?? ""));
watch(
  () => props.seedItems,
  (next) => {
    if (next === undefined) return;
    items.value = next;
    pendingTotal.value = props.seedTotal ?? next.length;
    index.value = 0;
  },
);

function step(delta: number): void {
  const next = index.value + delta;
  if (next < 0 || next >= items.value.length) return;
  index.value = next;
  editing.value = false;
  actionError.value = "";
}

function onKeydown(event: KeyboardEvent): void {
  const tag = (event.target as HTMLElement | null)?.tagName;
  if (tag === "TEXTAREA" || tag === "INPUT") return;
  if (event.key === "ArrowLeft") {
    event.preventDefault();
    step(-1);
  } else if (event.key === "ArrowRight") {
    event.preventDefault();
    step(1);
  }
}

function onPointerDown(event: PointerEvent): void {
  const target = event.target as HTMLElement | null;
  if (target?.closest("button, textarea, input")) {
    dragStartX.value = null;
    return;
  }
  dragStartX.value = event.clientX;
}

function onPointerUp(event: PointerEvent): void {
  if (dragStartX.value === null) return;
  const delta = event.clientX - dragStartX.value;
  dragStartX.value = null;
  if (delta > 48) step(-1);
  else if (delta < -48) step(1);
}

function inboxError(error: unknown, fallback: string): string {
  if (axios.isAxiosError<{ detail?: string }>(error)) {
    return error.response?.data?.detail || fallback;
  }
  return fallback;
}

async function loadInbox(): Promise<void> {
  if (preview.value) return;
  loading.value = true;
  loadError.value = "";
  try {
    const inbox = await hitlApi.inbox();
    items.value = inbox.items;
    pendingTotal.value = inbox.pending_total;
    if (index.value >= items.value.length) index.value = 0;
  } catch (error: unknown) {
    loadError.value = inboxError(error, "Failed to load pending reviews.");
  } finally {
    loading.value = false;
  }
}

function openEdit(): void {
  if (!current.value || preview.value) return;
  editText.value = current.value.text;
  editing.value = true;
  actionError.value = "";
}

function cancelEdit(): void {
  editing.value = false;
  actionError.value = "";
}
function dropCurrent(): void {
  const itemIndex = index.value;
  items.value = items.value.filter((_, i) => i !== itemIndex);
  pendingTotal.value = Math.max(0, pendingTotal.value - 1);
  editing.value = false;
  if (index.value >= items.value.length) index.value = Math.max(0, items.value.length - 1);
}
function openRun(): void {
  const item = current.value;
  if (!item?.workflow_id || preview.value) return;
  const params: { id: string; executionId?: string } = { id: item.workflow_id };
  if (item.execution_history_id) params.executionId = item.execution_history_id;
  void router.push({ name: "editor", params });
}
function publishHistoryTarget(): void {
  if (!reportHistoryTarget) return;
  const item = current.value;
  if (!item?.workflow_id || !item.execution_history_id || preview.value) {
    reportHistoryTarget(null);
    return;
  }
  reportHistoryTarget({ workflowId: item.workflow_id, executionId: item.execution_history_id });
}
watch(current, publishHistoryTarget);
onBeforeUnmount(() => reportHistoryTarget?.(null));
async function decide(action: "accept" | "edit" | "refuse"): Promise<void> {
  if (!current.value || preview.value || submitting.value) return;
  const text = editText.value.trim();
  if (action === "edit" && !text) {
    actionError.value = "Edited text is required.";
    return;
  }
  submitting.value = true;
  actionError.value = "";
  try {
    await hitlApi.inboxDecide(current.value.id, {
      action,
      edited_text: action === "edit" ? text : undefined,
    });
    dropCurrent();
  } catch (error: unknown) {
    actionError.value = inboxError(error, "Failed to submit the review.");
  } finally {
    submitting.value = false;
  }
}
onMounted(() => {
  void loadInbox();
});
</script>

<template>
  <div
    class="flex h-full min-h-[140px] flex-col overflow-hidden"
    tabindex="0"
    @dblclick.stop
    @keydown="onKeydown"
    @pointerdown="onPointerDown"
    @pointerup="onPointerUp"
  >
    <div class="mb-2 flex items-center justify-between gap-2">
      <Button
        variant="ghost"
        size="icon"
        class="disabled:!opacity-25"
        aria-label="Previous review"
        :disabled="atStart"
        @click="step(-1)"
      >
        <ChevronLeft class="h-4 w-4" />
      </Button>
      <span class="text-xs font-medium tabular-nums text-muted-foreground">
        {{ positionLabel }}
      </span>
      <Button
        variant="ghost"
        size="icon"
        class="disabled:!opacity-25"
        aria-label="Next review"
        :disabled="atEnd"
        @click="step(1)"
      >
        <ChevronRight class="h-4 w-4" />
      </Button>
    </div>

    <div
      v-if="loading"
      class="flex flex-1 items-center justify-center text-sm text-muted-foreground"
    >
      Loading reviews…
    </div>
    <div
      v-else-if="loadError"
      class="flex flex-1 flex-col items-center justify-center gap-2 text-center text-sm text-destructive"
    >
      {{ loadError }}
      <Button
        variant="outline"
        size="sm"
        @click="loadInbox"
      >
        Retry
      </Button>
    </div>

    <div
      v-else-if="!current"
      class="flex flex-1 items-center justify-center text-sm text-muted-foreground"
    >
      No pending reviews
    </div>

    <div
      v-else
      class="flex min-h-0 flex-1 flex-col"
    >
      <button
        type="button"
        class="mb-1 flex min-w-0 items-center gap-1.5 text-left text-sm font-medium text-foreground hover:text-primary disabled:pointer-events-none disabled:opacity-50"
        :disabled="preview || !current.workflow_id"
        @click="openRun"
      >
        <ExternalLink class="h-3.5 w-3.5 shrink-0" />
        <span class="truncate">
          {{ current.workflow_name }}
          <span class="font-normal text-muted-foreground">· {{ current.agent_label }}</span>
        </span>
      </button>
      <p
        v-if="current.summary"
        class="mt-1 line-clamp-2 text-xs text-muted-foreground"
      >
        {{ current.summary }}
      </p>

      <Textarea
        v-if="editing"
        v-model="editText"
        class="mt-2 min-h-0 flex-1"
        :rows="4"
      />
      <!-- eslint-disable vue/no-v-html -->
      <div
        v-else
        class="mt-2 min-h-0 flex-1 overflow-auto text-sm text-foreground [&_a]:underline [&_p]:mb-2 [&_pre]:overflow-x-auto"
        v-html="currentHtml"
      />
      <!-- eslint-enable vue/no-v-html -->

      <p
        v-if="actionError"
        class="mt-2 text-xs text-destructive"
      >
        {{ actionError }}
      </p>

      <HitlReviewActions
        :editing="editing"
        :submitting="submitting"
        :preview="preview"
        @cancel="cancelEdit"
        @save="decide('edit')"
        @edit="openEdit"
        @accept="decide('accept')"
        @refuse="decide('refuse')"
      />
    </div>
  </div>
</template>
