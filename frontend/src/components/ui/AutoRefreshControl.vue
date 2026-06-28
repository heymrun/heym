<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Clock } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import {
  AUTO_REFRESH_MAX_SECONDS,
  AUTO_REFRESH_MIN_SECONDS,
  formatCountdown,
  useAutoRefresh,
  validateAutoRefreshSeconds,
  type AutoRefreshBounds,
} from "@/composables/useAutoRefresh";

interface PresetOption {
  value: string;
  label: string;
}

interface Props {
  presetOptions?: PresetOption[];
  bounds?: AutoRefreshBounds;
  defaultCustomSeconds?: string;
  active?: boolean;
}

const props = withDefaults(defineProps<Props>(), {
  presetOptions: () => [
    { value: "off", label: "Off" },
    { value: "60", label: "60s" },
    { value: "300", label: "5m" },
    { value: "900", label: "15m" },
    { value: "custom", label: "Custom" },
  ],
  bounds: () => ({
    minSeconds: AUTO_REFRESH_MIN_SECONDS,
    maxSeconds: AUTO_REFRESH_MAX_SECONDS,
  }),
  defaultCustomSeconds: "120",
  active: true,
});

const emit = defineEmits<{
  (e: "refresh"): void;
}>();

type PresetValue = string;

const selectedPreset = ref<PresetValue>("off");
const customSecondsInput = ref(props.defaultCustomSeconds);
const customError = ref<string | null>(null);
const appliedCustomSeconds = ref<number | null>(null);

const minSeconds = computed<number>(() => props.bounds.minSeconds ?? AUTO_REFRESH_MIN_SECONDS);
const maxSeconds = computed<number>(() => props.bounds.maxSeconds ?? AUTO_REFRESH_MAX_SECONDS);

const { secondsRemaining, validationError, setIntervalMs, stop } = useAutoRefresh(
  () => {
    emit("refresh");
  },
  props.bounds,
);

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
  const error = validateAutoRefreshSeconds(parsed, props.bounds);
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
  const next = value ?? "off";
  selectedPreset.value = next;
  applyPreset(next);
}

watch(selectedPreset, (value) => {
  if (value === "custom") {
    return;
  }
  customError.value = null;
});

watch(
  () => props.active,
  (isActive) => {
    if (isActive) {
      applyPreset(selectedPreset.value);
      return;
    }
    stop();
  },
);
</script>

<template>
  <div class="flex items-center gap-1.5 flex-wrap">
    <Select
      :model-value="selectedPreset"
      :options="presetOptions"
      class="w-[5.5rem] sm:w-24"
      select-class="h-9 min-h-0 px-2.5 py-1.5 text-xs sm:text-sm"
      @update:model-value="handlePresetChange"
    />

    <template v-if="isCustomMode">
      <Input
        v-model="customSecondsInput"
        type="number"
        :min="minSeconds"
        :max="maxSeconds"
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
