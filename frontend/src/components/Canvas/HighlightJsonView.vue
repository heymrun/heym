<script setup lang="ts">
import { computed, ref } from "vue";
import { ChevronRight } from "lucide-vue-next";

const props = withDefaults(
  defineProps<{ value: unknown; keyName?: string; depth?: number }>(),
  { keyName: undefined, depth: 0 },
);

// Top level is expanded; nested objects/arrays start collapsed.
const collapsed = ref((props.depth ?? 0) >= 1);

const isContainer = computed<boolean>(
  () => props.value !== null && typeof props.value === "object",
);
const isArray = computed<boolean>(() => Array.isArray(props.value));

const entries = computed<[string, unknown][]>(() => {
  if (!isContainer.value) {
    return [];
  }
  if (isArray.value) {
    return (props.value as unknown[]).map((v, i) => [String(i), v]);
  }
  return Object.entries(props.value as Record<string, unknown>);
});

const brackets = computed<[string, string]>(() => (isArray.value ? ["[", "]"] : ["{", "}"]));
const summary = computed<string>(() => `${brackets.value[0]} ${entries.value.length} ${brackets.value[1]}`);

function primitive(v: unknown): string {
  if (typeof v === "string") {
    return `"${v}"`;
  }
  return String(v);
}

function primitiveClass(v: unknown): string {
  if (typeof v === "string") {
    return "text-success";
  }
  if (typeof v === "number") {
    return "text-accent-blue";
  }
  if (typeof v === "boolean" || v === null) {
    return "text-violet-400";
  }
  return "text-foreground";
}
</script>

<template>
  <div class="font-mono text-[11px] leading-relaxed">
    <template v-if="isContainer">
      <button
        type="button"
        class="inline-flex items-start gap-0.5 text-left hover:text-foreground"
        @click.stop="collapsed = !collapsed"
      >
        <ChevronRight
          class="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground transition-transform"
          :class="collapsed ? '' : 'rotate-90'"
        />
        <span>
          <span
            v-if="keyName !== undefined"
            class="text-accent-blue"
          >{{ keyName }}: </span>
          <span class="text-muted-foreground">{{ collapsed ? summary : brackets[0] }}</span>
        </span>
      </button>
      <div
        v-if="!collapsed"
        class="ml-2 border-l border-border/50 pl-2"
      >
        <HighlightJsonView
          v-for="[k, v] in entries"
          :key="k"
          :value="v"
          :key-name="k"
          :depth="(depth ?? 0) + 1"
        />
      </div>
      <div
        v-if="!collapsed"
        class="pl-3.5 text-muted-foreground"
      >
        {{ brackets[1] }}
      </div>
    </template>
    <div
      v-else
      class="break-words pl-3.5"
    >
      <span
        v-if="keyName !== undefined"
        class="text-accent-blue"
      >{{ keyName }}: </span>
      <span :class="primitiveClass(value)">{{ primitive(value) }}</span>
    </div>
  </div>
</template>
