<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { Ban, Copy, ExternalLink, FlaskConical, LayoutTemplate, Power, Trash2 } from "lucide-vue-next";

interface EvalNodeData {
  label: string;
  systemInstruction?: string;
  temperature?: number;
}

interface Props {
  visible: boolean;
  position: { x: number; y: number };
  selectedCount: number;
  hasDisabledNodes: boolean;
  allDisabled: boolean;
  evalNode: { id: string; type: string; data: EvalNodeData } | null;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "extract"): void;
  (e: "evalAgent"): void;
  (e: "disable"): void;
  (e: "duplicate"): void;
  (e: "delete"): void;
  (e: "close"): void;
  (e: "shareAsTemplate"): void;
}>();

const menuRef = ref<HTMLDivElement | null>(null);
const adjustedPosition = ref({ x: 0, y: 0 });

const menuItems = computed(() => [
  {
    label: props.selectedCount > 1 ? "Extract to Sub-Workflow" : "Extract to Sub-Workflow",
    icon: ExternalLink,
    action: () => emit("extract"),
    show: true,
  },
  {
    label: "Eval Agent",
    icon: FlaskConical,
    action: () => emit("evalAgent"),
    show: !!props.evalNode,
  },
  {
    label: props.allDisabled ? "Enable" : "Disable",
    icon: props.allDisabled ? Power : Ban,
    action: () => emit("disable"),
    show: true,
  },
  {
    label: "Duplicate",
    icon: Copy,
    action: () => emit("duplicate"),
    show: true,
  },
  {
    label: "Share as Template",
    icon: LayoutTemplate,
    action: () => { emit("shareAsTemplate"); emit("close"); },
    show: props.selectedCount === 1,
  },
  {
    type: "separator",
    show: true,
  },
  {
    label: "Delete",
    icon: Trash2,
    action: () => emit("delete"),
    show: true,
    destructive: true,
  },
]);

function handleClickOutside(event: MouseEvent): void {
  if (menuRef.value && !menuRef.value.contains(event.target as Node)) {
    event.preventDefault();
    event.stopPropagation();
    emit("close");
  }
}

function handleKeyDown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    emit("close");
  }
}

function handleContextMenuOutside(event: MouseEvent): void {
  if (menuRef.value && !menuRef.value.contains(event.target as Node)) {
    emit("close");
  }
}

function adjustMenuPosition(): void {
  if (!menuRef.value) {
    adjustedPosition.value = props.position;
    return;
  }

  const menuRect = menuRef.value.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;

  let x = props.position.x;
  let y = props.position.y;

  if (x + menuRect.width > viewportWidth - 10) {
    x = viewportWidth - menuRect.width - 10;
  }

  if (y + menuRect.height > viewportHeight - 10) {
    y = viewportHeight - menuRect.height - 10;
  }

  adjustedPosition.value = { x, y };
}

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      adjustedPosition.value = props.position;
      setTimeout(() => {
        adjustMenuPosition();
        document.addEventListener("click", handleClickOutside, true);
        document.addEventListener("contextmenu", handleContextMenuOutside, true);
        document.addEventListener("keydown", handleKeyDown);
      }, 10);
    } else {
      document.removeEventListener("click", handleClickOutside, true);
      document.removeEventListener("contextmenu", handleContextMenuOutside, true);
      document.removeEventListener("keydown", handleKeyDown);
    }
  }
);

onMounted(() => {
  if (props.visible) {
    document.addEventListener("click", handleClickOutside, true);
    document.addEventListener("contextmenu", handleContextMenuOutside, true);
    document.addEventListener("keydown", handleKeyDown);
  }
});

onUnmounted(() => {
  document.removeEventListener("click", handleClickOutside, true);
  document.removeEventListener("contextmenu", handleContextMenuOutside, true);
  document.removeEventListener("keydown", handleKeyDown);
});
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition ease-out duration-100"
      enter-from-class="opacity-0 scale-95"
      enter-to-class="opacity-100 scale-100"
      leave-active-class="transition ease-in duration-75"
      leave-from-class="opacity-100 scale-100"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-if="visible"
        ref="menuRef"
        :style="{
          left: `${adjustedPosition.x}px`,
          top: `${adjustedPosition.y}px`,
        }"
        class="fixed z-[100] min-w-[180px] bg-popover border rounded-lg shadow-lg py-1 origin-top-left"
      >
        <div class="px-3 py-1.5 text-xs text-muted-foreground border-b mb-1">
          {{ selectedCount }} node{{ selectedCount > 1 ? "s" : "" }} selected
        </div>
        <template
          v-for="(item, index) in menuItems"
          :key="index"
        >
          <div
            v-if="item.type === 'separator' && item.show"
            class="border-t my-1"
          />
          <button
            v-else-if="item.show"
            :class="[
              'w-full px-3 py-2 text-sm text-left flex items-center gap-2.5 transition-colors',
              item.destructive
                ? 'text-destructive hover:bg-destructive/10'
                : 'hover:bg-accent hover:text-accent-foreground'
            ]"
            @click="item.action"
          >
            <component
              :is="item.icon"
              class="w-4 h-4"
            />
            {{ item.label }}
          </button>
        </template>
      </div>
    </Transition>
  </Teleport>
</template>
