<script setup lang="ts">
import { computed, ref, watch } from "vue";
import {
  ComboboxAnchor,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxGroup,
  ComboboxInput,
  ComboboxItem,
  ComboboxItemIndicator,
  ComboboxLabel,
  ComboboxRoot,
  ComboboxTrigger,
  ComboboxViewport,
} from "radix-vue";
import { Check, ChevronDown, Search, X } from "lucide-vue-next";

import { cn } from "@/lib/utils";

interface Option {
  value: string | undefined;
  label: string;
}

interface InternalOption extends Option {
  key: string;
}

interface OptionGroup {
  label?: string;
  options: Option[];
}

interface InternalOptionGroup {
  key: string;
  label?: string;
  options: InternalOption[];
}

interface Props {
  modelValue?: string | undefined;
  options?: Option[];
  groups?: OptionGroup[];
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  clearable?: boolean;
  clearAriaLabel?: string;
  class?: string;
  selectClass?: string;
  contentClass?: string;
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: "",
  options: () => [],
  groups: undefined,
  placeholder: "Select...",
  searchPlaceholder: "Search...",
  emptyText: "No results found.",
  disabled: false,
  clearable: false,
  clearAriaLabel: "Clear selection",
  class: undefined,
  selectClass: undefined,
  contentClass: undefined,
});

const emit = defineEmits<{
  (e: "update:modelValue", value: string | undefined): void;
}>();

const open = ref(false);
const searchTerm = ref("");
const selectedKey = ref<string>("");

const optionGroups = computed<InternalOptionGroup[]>(() => {
  const groups = props.groups && props.groups.length > 0
    ? props.groups
    : [{ options: props.options }];

  return groups.map((group, groupIndex) => ({
    key: `group-${groupIndex}`,
    label: group.label,
    options: group.options.map((option, optionIndex) => ({
      ...option,
      key: `group-${groupIndex}-option-${optionIndex}`,
    })),
  })).filter((group) => group.options.length > 0);
});

const internalOptions = computed<InternalOption[]>(() =>
  optionGroups.value.flatMap((group) => group.options)
);

const selectedOption = computed<InternalOption | undefined>(() => {
  return internalOptions.value.find((option) => {
    const value = option.value ?? "";
    return value === (props.modelValue ?? "");
  });
});

const hasValue = computed<boolean>(() => {
  return typeof props.modelValue === "string" && props.modelValue.length > 0;
});

const wrapperClass = computed(() =>
  cn("relative group min-w-0 w-full", props.class)
);

const anchorClass = computed(() =>
  cn(
    "flex h-11 min-h-[44px] md:h-10 w-full items-center rounded-xl border border-border bg-background text-sm",
    "focus-within:outline-none focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/15",
    "disabled:cursor-not-allowed disabled:opacity-50 disabled:bg-muted/50",
    "transition-all duration-200 shadow-sm hover:border-border/80",
    props.disabled && "cursor-not-allowed opacity-50 bg-muted/50",
    props.selectClass
  )
);

const contentClass = computed(() =>
  cn(
    "z-50 mt-1 max-h-72 min-w-[var(--radix-combobox-trigger-width)] overflow-hidden rounded-xl border border-border bg-popover text-popover-foreground shadow-lg",
    "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
    props.contentClass
  )
);

watch(
  [selectedOption, internalOptions],
  () => {
    selectedKey.value = selectedOption.value?.key ?? "";
  },
  { immediate: true }
);

watch(open, (isOpen) => {
  if (isOpen) {
    searchTerm.value = "";
  }
});

function displayValue(key: string): string {
  const option = internalOptions.value.find((item) => item.key === key);
  return option?.label ?? "";
}

function filterOptions(keys: string[], term: string): string[] {
  const normalizedTerm = term.trim().toLowerCase();
  if (!normalizedTerm) {
    return keys;
  }

  return keys.filter((key) => {
    const option = internalOptions.value.find((item) => item.key === key);
    if (!option) {
      return false;
    }

    return [option.label, option.value ?? ""].some((text) =>
      text.toLowerCase().includes(normalizedTerm)
    );
  });
}

function openOptions(): void {
  if (!props.disabled) {
    open.value = true;
  }
}

function handleUpdateSelectedKey(key: string): void {
  selectedKey.value = key;
  const option = internalOptions.value.find((item) => item.key === key);
  const value = option?.value;
  emit("update:modelValue", value && value.length > 0 ? value : undefined);
}

function clearValue(): void {
  selectedKey.value = "";
  searchTerm.value = "";
  emit("update:modelValue", undefined);
}
</script>

<template>
  <ComboboxRoot
    v-model="selectedKey"
    v-model:open="open"
    v-model:search-term="searchTerm"
    :disabled="disabled"
    :display-value="displayValue"
    :filter-function="filterOptions"
    :reset-search-term-on-blur="false"
    class="relative w-full"
    @update:model-value="handleUpdateSelectedKey"
  >
    <ComboboxAnchor :class="wrapperClass">
      <div
        :class="anchorClass"
        @click="openOptions"
      >
        <Search class="ml-3.5 h-4 w-4 shrink-0 text-muted-foreground" />
        <ComboboxInput
          class="h-full min-w-0 flex-1 bg-transparent px-2 text-sm outline-none placeholder:text-muted-foreground/60 disabled:cursor-not-allowed"
          :placeholder="open ? searchPlaceholder : placeholder"
          :disabled="disabled"
        />
        <button
          v-if="clearable && hasValue && !disabled"
          type="button"
          :aria-label="clearAriaLabel"
          class="mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-muted-foreground opacity-0 pointer-events-none transition-all hover:bg-muted hover:text-foreground group-hover:opacity-100 group-hover:pointer-events-auto group-focus-within:opacity-100 group-focus-within:pointer-events-auto"
          @mousedown.prevent.stop
          @click.prevent.stop="clearValue"
        >
          <X class="h-3.5 w-3.5" />
        </button>
        <ComboboxTrigger
          class="mr-2 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:cursor-not-allowed"
          :class="clearable && hasValue ? 'group-hover:opacity-0 group-focus-within:opacity-0' : ''"
          :disabled="disabled"
          aria-label="Toggle options"
        >
          <ChevronDown class="h-4 w-4" />
        </ComboboxTrigger>
      </div>
    </ComboboxAnchor>

    <ComboboxContent
      position="popper"
      side="bottom"
      align="start"
      :side-offset="4"
      :class="contentClass"
    >
      <ComboboxViewport class="max-h-72 overflow-y-auto p-1">
        <ComboboxEmpty class="px-3 py-6 text-center text-sm text-muted-foreground">
          {{ emptyText }}
        </ComboboxEmpty>
        <ComboboxGroup
          v-for="group in optionGroups"
          :key="group.key"
          class="py-1"
        >
          <ComboboxLabel
            v-if="group.label"
            class="mb-1 mt-2 rounded-md bg-muted/70 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground first:mt-0"
          >
            {{ group.label }}
          </ComboboxLabel>
          <ComboboxItem
            v-for="option in group.options"
            :key="option.key"
            :value="option.key"
            class="relative flex min-h-9 cursor-pointer select-none items-center rounded-lg py-2 pl-8 pr-3 text-sm outline-none transition-colors data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50"
          >
            <ComboboxItemIndicator class="absolute left-2 flex h-4 w-4 items-center justify-center">
              <Check class="h-4 w-4" />
            </ComboboxItemIndicator>
            <span class="truncate">{{ option.label }}</span>
          </ComboboxItem>
        </ComboboxGroup>
      </ComboboxViewport>
    </ComboboxContent>
  </ComboboxRoot>
</template>
