<script setup lang="ts">
import { computed, ref } from "vue";
import { Play, Square } from "lucide-vue-next";

import type { YoloInputsRequest } from "@/features/assistant-yolo/useAssistantYoloLoop";
import type { YoloInputDraft } from "@/features/assistant-yolo/yoloProtocol";

import { parseWebhookJson } from "@/lib/webhookBody";

interface Props {
  request: YoloInputsRequest;
}

const props = defineProps<Props>();
const emit = defineEmits<{
  (event: "confirm", draft: YoloInputDraft): void;
  (event: "stop"): void;
}>();

const values = ref<Record<string, string>>(
  props.request.draft.mode === "legacy" ? { ...props.request.draft.values } : {},
);
const json = ref(props.request.draft.mode === "generic" ? props.request.draft.json : "");
const isPending = computed(() => props.request.status === "pending");
const jsonError = computed(() =>
  props.request.draft.mode === "generic" ? parseWebhookJson(json.value).error : null,
);
const caption = computed(() => {
  if (isPending.value) return "The workflow runs with these values. Edit them, then press Run.";
  return props.request.status === "confirmed" ? "Used for the runs below." : "Stopped.";
});

function confirm(): void {
  if (!isPending.value || jsonError.value) return;
  emit(
    "confirm",
    props.request.draft.mode === "generic"
      ? { mode: "generic", json: json.value }
      : { mode: "legacy", values: { ...values.value } },
  );
}
</script>

<template>
  <div
    class="mt-2 flex flex-col gap-3 rounded-lg border border-border bg-card p-3"
    data-testid="ai-assistant-yolo-inputs"
  >
    <div>
      <p class="text-[13px] font-semibold text-foreground">
        Test inputs
      </p>
      <p class="text-xs text-muted-foreground">
        {{ caption }}
      </p>
    </div>
    <template v-if="request.draft.mode === 'legacy'">
      <label
        v-for="key in request.fieldKeys"
        :key="key"
        class="flex flex-col gap-1"
      >
        <span class="font-mono text-[11px] text-muted-foreground">{{ key }}</span>
        <textarea
          v-model="values[key]"
          rows="2"
          class="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-xs text-foreground"
          :disabled="!isPending"
          :data-testid="`ai-assistant-yolo-input-${key}`"
        />
      </label>
    </template>
    <label
      v-else
      class="flex flex-col gap-1"
    >
      <span class="text-[11px] text-muted-foreground">Request body (JSON)</span>
      <textarea
        v-model="json"
        rows="5"
        class="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 font-mono text-xs text-foreground"
        :disabled="!isPending"
        data-testid="ai-assistant-yolo-input-json"
      />
      <span
        v-if="jsonError"
        class="text-[11px] text-destructive"
      >{{ jsonError }}</span>
    </label>
    <div
      v-if="isPending"
      class="flex gap-2"
    >
      <button
        type="button"
        class="flex h-8 flex-1 items-center justify-center gap-1.5 rounded-md bg-primary text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="Boolean(jsonError)"
        data-testid="ai-assistant-yolo-inputs-run"
        @click="confirm"
      >
        <Play class="h-3.5 w-3.5" />
        Run
      </button>
      <button
        type="button"
        class="flex h-8 items-center justify-center gap-1.5 rounded-md border border-border bg-background px-3 text-xs font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        data-testid="ai-assistant-yolo-inputs-stop"
        @click="emit('stop')"
      >
        <Square class="h-3.5 w-3.5" />
        Stop
      </button>
    </div>
  </div>
</template>
