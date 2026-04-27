<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { BookOpen, FileText, Search } from "lucide-vue-next";

import { cn } from "@/lib/utils";
import { getAllDocItems, getDocPath } from "@/docs/manifest";

interface Props {
  open: boolean;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "close"): void;
}>();

const router = useRouter();

const searchQuery = ref("");
const selectedIndex = ref(0);
const inputRef = ref<HTMLInputElement | null>(null);
const listRef = ref<HTMLDivElement | null>(null);
const itemRefs = ref<(HTMLDivElement | null)[]>([]);

const allItems = computed(() => getAllDocItems());

const filteredItems = computed(() => {
  const q = searchQuery.value.toLowerCase().trim();
  if (!q) return allItems.value;
  return allItems.value.filter(
    (item) =>
      item.title.toLowerCase().includes(q) ||
      item.slug.toLowerCase().includes(q) ||
      item.categoryLabel.toLowerCase().includes(q)
  );
});

watch(
  () => props.open,
  (open) => {
    if (open) {
      searchQuery.value = "";
      selectedIndex.value = 0;
      nextTick(() => {
        inputRef.value?.focus();
      });
    }
  }
);

watch(filteredItems, () => {
  if (selectedIndex.value >= filteredItems.value.length) {
    selectedIndex.value = Math.max(0, filteredItems.value.length - 1);
  }
});

function scrollToSelected(): void {
  nextTick(() => {
    const el = itemRefs.value[selectedIndex.value];
    if (el && listRef.value) {
      el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  });
}

function handleKeyDown(event: KeyboardEvent): void {
  if (!props.open) return;

  if (event.key === "Escape") {
    event.preventDefault();
    emit("close");
    return;
  }

  if (event.key === "ArrowDown" || (event.key === "Tab" && !event.shiftKey)) {
    event.preventDefault();
    if (filteredItems.value.length > 0) {
      selectedIndex.value =
        selectedIndex.value >= filteredItems.value.length - 1
          ? 0
          : selectedIndex.value + 1;
      scrollToSelected();
    }
    return;
  }

  if (event.key === "ArrowUp" || (event.key === "Tab" && event.shiftKey)) {
    event.preventDefault();
    if (filteredItems.value.length > 0) {
      selectedIndex.value =
        selectedIndex.value <= 0
          ? filteredItems.value.length - 1
          : selectedIndex.value - 1;
      scrollToSelected();
    }
    return;
  }

  if (event.key === "Enter") {
    event.preventDefault();
    const item = filteredItems.value[selectedIndex.value];
    if (item) {
      router.push(getDocPath(item.categoryId, item.slug));
      emit("close");
    }
    return;
  }
}

function selectItem(item: (typeof filteredItems.value)[number]): void {
  router.push(getDocPath(item.categoryId, item.slug));
  emit("close");
}

function handleBackdropClick(): void {
  emit("close");
}

onMounted(() => {
  window.addEventListener("keydown", handleKeyDown);
});

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeyDown);
});
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="open"
        class="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh] px-4"
        role="dialog"
        aria-modal="true"
        aria-label="Search documentation"
      >
        <div
          class="docs-palette-backdrop fixed inset-0 bg-background/80 backdrop-blur-sm"
          aria-hidden="true"
          @click="handleBackdropClick"
        />

        <div
          class="docs-palette-content relative z-10 w-full max-w-2xl"
          @click.stop
        >
          <div
            class="rounded-2xl border border-border/60 bg-card/95 backdrop-blur-xl shadow-metallic overflow-hidden"
          >
            <div class="flex items-center gap-3 px-4 py-3 border-b border-border/40">
              <Search class="w-5 h-5 text-muted-foreground shrink-0" />
              <input
                ref="inputRef"
                v-model="searchQuery"
                type="text"
                placeholder="Search documentation..."
                class="flex-1 bg-transparent text-foreground placeholder:text-muted-foreground focus:outline-none text-base"
                autocomplete="off"
              >
              <kbd class="hidden sm:inline-flex h-6 items-center gap-1 rounded border border-border/60 bg-muted/50 px-2 text-xs text-muted-foreground">
                ESC
              </kbd>
            </div>

            <div
              ref="listRef"
              class="max-h-[60vh] overflow-y-auto scrollbar-thin"
            >
              <div
                v-for="(item, idx) in filteredItems"
                :key="`${item.categoryId}-${item.slug}`"
                :ref="(el) => { itemRefs[idx] = el as HTMLDivElement }"
                role="option"
                :aria-selected="idx === selectedIndex"
                :class="cn(
                  'flex items-center gap-3 px-4 py-3 cursor-pointer transition-colors',
                  idx === selectedIndex ? 'bg-primary/15 text-primary' : 'hover:bg-muted/50'
                )"
                @click="selectItem(item)"
              >
                <FileText
                  v-if="item.categoryId === 'reference'"
                  class="w-4 h-4 shrink-0 text-muted-foreground"
                />
                <BookOpen
                  v-else
                  class="w-4 h-4 shrink-0 text-muted-foreground"
                />
                <div class="min-w-0 flex-1">
                  <span class="font-medium">{{ item.title }}</span>
                  <span class="ml-2 text-xs text-muted-foreground">
                    {{ item.categoryLabel }}
                  </span>
                </div>
              </div>
              <div
                v-if="filteredItems.length === 0"
                class="px-4 py-8 text-center text-muted-foreground"
              >
                No results found
              </div>
            </div>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
