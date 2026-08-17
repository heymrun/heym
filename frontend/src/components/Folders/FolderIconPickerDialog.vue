<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { Folder } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import { folderIconOptions, getFolderIcon } from "@/lib/folderIcons";

interface Props {
  open: boolean;
  folderName?: string;
  currentIcon?: string | null;
}

const props = withDefaults(defineProps<Props>(), {
  folderName: "",
  currentIcon: null,
});

const emit = defineEmits<{
  close: [];
  save: [icon: string | null];
}>();

const selectedIcon = ref<string | null>(props.currentIcon ?? null);

watch(
  () => props.open,
  (open) => {
    if (open) {
      selectedIcon.value = props.currentIcon ?? null;
    }
  },
);

const selectedComponent = computed(() => getFolderIcon(selectedIcon.value));

function humanizeIconKey(key: string): string {
  return key.replace(/([a-z0-9])([A-Z])/g, "$1 $2");
}

function selectIcon(key: string): void {
  selectedIcon.value = key;
}

function clearIcon(): void {
  selectedIcon.value = null;
}

function save(): void {
  emit("save", selectedIcon.value);
}
</script>

<template>
  <Dialog
    :open="open"
    title="Choose Folder Icon"
    size="2xl"
    @close="emit('close')"
  >
    <div class="flex flex-col">
      <div class="flex shrink-0 items-center gap-3 pb-4">
        <div
          class="w-12 h-12 shrink-0 rounded-lg bg-muted/60 ring-1 ring-inset ring-border flex items-center justify-center"
        >
          <component
            :is="selectedComponent ?? Folder"
            class="w-6 h-6 text-amber-500"
          />
        </div>
        <div class="min-w-0">
          <p class="text-sm font-medium truncate">
            {{ folderName || "Folder" }}
          </p>
          <p class="text-xs text-muted-foreground">
            {{ selectedIcon ? humanizeIconKey(selectedIcon) : "Default folder icon" }}
          </p>
        </div>
      </div>

      <div class="max-h-[40vh] overflow-y-auto overscroll-y-contain pr-1">
        <div class="grid grid-cols-6 sm:grid-cols-8 gap-2">
          <button
            type="button"
            class="flex flex-col items-center justify-center gap-1 p-2 rounded-lg border transition-colors"
            :class="
              selectedIcon === null
                ? 'border-primary bg-primary/10'
                : 'border-border hover:bg-muted/60'
            "
            @click="clearIcon"
          >
            <Folder class="w-5 h-5 text-amber-500" />
            <span class="text-[10px] leading-none text-muted-foreground">Default</span>
          </button>
          <button
            v-for="option in folderIconOptions"
            :key="option.key"
            type="button"
            class="flex flex-col items-center justify-center gap-1 p-2 rounded-lg border transition-colors"
            :class="
              selectedIcon === option.key
                ? 'border-primary bg-primary/10'
                : 'border-border hover:bg-muted/60'
            "
            :title="humanizeIconKey(option.key)"
            @click="selectIcon(option.key)"
          >
            <component
              :is="option.component"
              class="w-5 h-5 text-foreground"
            />
            <span class="text-[10px] leading-none text-muted-foreground truncate w-full text-center">
              {{ humanizeIconKey(option.key) }}
            </span>
          </button>
        </div>
      </div>

      <div class="flex shrink-0 flex-col-reverse justify-end gap-3 border-t border-border/60 pt-4 mt-4 sm:flex-row">
        <Button
          variant="outline"
          type="button"
          @click="emit('close')"
        >
          Cancel
        </Button>
        <Button
          type="button"
          @click="save"
        >
          Save
        </Button>
      </div>
    </div>
  </Dialog>
</template>
