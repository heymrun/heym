<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Clock } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import {
  formatCountdown,
  useAutoRefresh,
  validateAutoRefreshSeconds,
} from "@/composables/useAutoRefresh";

const emit = defineEmits<{
  (e: "refresh"): void;
}>();

const PRESET_OPTIONS = [
  { value: "off", label: "Off" },
  { value: "60", label: "60s" },
  { value: "300", label: "5m" },
  { value: "900", label: "15m" },
  { value: "custom", label: "Custom" },
] as const;

type PresetValue = (typeof PRESET_OPTIONS)[number]["value"];

const selectedPreset = ref<PresetValue>("off");
const customSecondsInput = ref("120");
const customError = ref<string | null>(null);
const appliedCustomSeconds = ref<number | null>(null);

const { secondsRemaining, validationError, setIntervalMs } = useAutoRefresh(() => {
  emit("refresh");
});

const isCustomMode = computed<boolean>(() => selectedPreset.value === "custom");

const countdownLabel = computed<string | null>(() => {
  if (secondsRemaining.value === null) {
    return null;
  }
  return formatCountdown(secondsRemaining.value, true);
});

const activeError = computed<string | null>(() => customError.value ?? validationError.value);

function applyPreset(value: PresetValue): void {
  customError.value = null;

  if (value === "off") {
    appliedCustomSeconds.value = null;
    setIntervalMs(null);
    return;
  }

  if (value === "custom") {
    if (appliedCustomSeconds.value !== null) {
      setIntervalMs(appliedCustomSeconds.value * 1000);
    } else {
      setIntervalMs(null);
    }
    return;
  }

  appliedCustomSeconds.value = null;
  setIntervalMs(Number(value) * 1000);
}

function applyCustomInterval(): void {
  const parsed = Number.parseInt(customSecondsInput.value, 10);
  const error = validateAutoRefreshSeconds(parsed);
  if (error !== null) {
    customError.value = error;
    setIntervalMs(null);
    return;
  }

  customError.value = null;
  appliedCustomSeconds.value = parsed;
  setIntervalMs(parsed * 1000);
}

function handlePresetChange(value: string | undefined): void {
  const next = (value ?? "off") as PresetValue;
  selectedPreset.value = next;
  applyPreset(next);
}

watch(selectedPreset, (value) => {
  if (value === "custom") {
    return;
  }
  customError.value = null;
});
</script>

<template>
  <div class="flex items-center gap-1.5 flex-wrap">
    <Select
      :model-value="selectedPreset"
      :options="[...PRESET_OPTIONS]"
      class="w-[5.5rem] sm:w-24"
      select-class="h-9 min-h-0 px-2.5 py-1.5 text-xs sm:text-sm"
      @update:model-value="handlePresetChange"
    />

    <template v-if="isCustomMode">
      <Input
        v-model="customSecondsInput"
        type="number"
        min="10"
        max="3600"
        placeholder="Seconds"
        class="w-16 sm:w-20"
        @keydown.enter.prevent="applyCustomInterval"
      />
      <Button
        variant="ghost"
        size="sm"
        class="h-9 px-2 text-xs"
        @click="applyCustomInterval"
      >
        Apply
      </Button>
    </template>

    <div
      v-if="countdownLabel"
      class="inline-flex items-center gap-1 rounded-md border border-border/60 bg-muted/40 px-2 py-1 text-xs text-muted-foreground tabular-nums"
      :title="`Next refresh in ${formatCountdown(secondsRemaining ?? 0)}`"
    >
      <Clock class="h-3.5 w-3.5 shrink-0" />
      <span class="hidden sm:inline">{{ formatCountdown(secondsRemaining ?? 0) }}</span>
      <span class="sm:hidden">{{ countdownLabel }}</span>
    </div>

    <span
      v-if="activeError"
      class="text-xs text-destructive"
    >
      {{ activeError }}
    </span>
  </div>
</template>
