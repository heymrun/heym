<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { ChevronDown, ChevronRight, Mail, Search, X } from "lucide-vue-next";

import Input from "@/components/ui/Input.vue";
import { cn } from "@/lib/utils";
import { DOCS_MANIFEST, getDocPath, type DocCategory } from "@/docs/manifest";
import { useDebounceFn, useEventListener } from "@vueuse/core";

interface Props {
  open?: boolean;
}

withDefaults(defineProps<Props>(), {
  open: true,
});

const emit = defineEmits<{
  (e: "navigate"): void;
}>();

const route = useRoute();

const searchInput = ref("");
const searchQuery = ref("");
const expandedCategories = ref<Set<string>>(new Set(Object.keys(DOCS_MANIFEST)));

const updateSearch = useDebounceFn(() => {
  searchQuery.value = searchInput.value;
}, 300);

watch(searchInput, () => {
  updateSearch();
});

const searchFieldWrapperRef = ref<HTMLElement | null>(null);

const hasSearchText = computed(() => searchInput.value.length > 0);

function clearDocsSearch(): void {
  searchInput.value = "";
  searchQuery.value = "";
  void nextTick(() => {
    searchFieldWrapperRef.value?.querySelector<HTMLInputElement>("input")?.focus();
  });
}

function onDocsSearchEscape(e: KeyboardEvent): void {
  if (e.key !== "Escape") return;
  const inputEl = e.target instanceof HTMLInputElement ? e.target : null;
  const domLen = inputEl?.value.length ?? 0;
  const refLen = String(searchInput.value ?? "").length;
  if (domLen === 0 && refLen === 0) return;
  e.stopImmediatePropagation();
  e.stopPropagation();
  e.preventDefault();
  clearDocsSearch();
}

useEventListener(
  window,
  "keydown",
  (e: KeyboardEvent) => {
    if (e.key !== "Escape") return;
    const w = searchFieldWrapperRef.value;
    if (!w) return;
    if (!(e.target instanceof HTMLInputElement) || !w.contains(e.target)) return;
    onDocsSearchEscape(e);
  },
  { capture: true }
);

function toggleCategory(categoryId: string): void {
  const next = new Set(expandedCategories.value);
  if (next.has(categoryId)) {
    next.delete(categoryId);
  } else {
    next.add(categoryId);
  }
  expandedCategories.value = next;
}

function isCategoryExpanded(categoryId: string): boolean {
  return expandedCategories.value.has(categoryId);
}

function isItemActive(categoryId: string, slug: string): boolean {
  const pathMatch = route.params.pathMatch;
  if (!pathMatch) return false;
  const path = Array.isArray(pathMatch) ? pathMatch.join("/") : pathMatch;
  return path === `${categoryId}/${slug}`;
}

function filterCategory(category: DocCategory): { slug: string; title: string }[] {
  const q = searchQuery.value.toLowerCase().trim();
  if (!q) return category.items;
  return category.items.filter(
    (item) =>
      item.title.toLowerCase().includes(q) ||
      item.slug.toLowerCase().includes(q) ||
      category.label.toLowerCase().includes(q)
  );
}

const filteredManifest = computed(() => {
  const q = searchQuery.value.toLowerCase().trim();
  const result: Record<string, DocCategory> = {};
  for (const [id, cat] of Object.entries(DOCS_MANIFEST)) {
    const items = filterCategory(cat);
    if (items.length > 0 || !q) {
      result[id] = { ...cat, items };
    }
  }
  return result;
});

const navRef = ref<HTMLElement | null>(null);

watch(
  () => route.params.pathMatch,
  async (pathMatch) => {
    if (pathMatch) {
      const path = Array.isArray(pathMatch) ? pathMatch[0] : pathMatch;
      const parts = path.split("/");
      if (parts.length >= 1 && parts[0]) {
        expandedCategories.value = new Set([...expandedCategories.value, parts[0]]);
      }
    }
    await nextTick();
    const activeLink = navRef.value?.querySelector<HTMLElement>("a[data-active]");
    activeLink?.scrollIntoView({ block: "center", behavior: "smooth" });
  },
  { immediate: true }
);
</script>

<template>
  <aside
    class="docs-sidebar w-64 h-full min-h-0 shrink-0 border-r border-border/60 bg-card/30 flex flex-col overflow-hidden"
    role="navigation"
    aria-label="Documentation navigation"
  >
    <div class="p-3 border-b border-border/40">
      <div
        ref="searchFieldWrapperRef"
        class="relative"
      >
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground pointer-events-none z-[1]" />
        <Input
          v-model="searchInput"
          type="text"
          placeholder="Search docs..."
          :class="cn('pl-9 h-10', hasSearchText ? 'pr-10' : '')"
        />
        <button
          v-show="hasSearchText"
          type="button"
          class="absolute right-2 top-1/2 -translate-y-1/2 z-[1] inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-muted/80 hover:text-foreground transition-colors"
          aria-label="Clear search"
          @click="clearDocsSearch()"
        >
          <X class="w-4 h-4" />
        </button>
      </div>
    </div>

    <nav
      ref="navRef"
      class="flex-1 min-h-0 overflow-y-auto overflow-x-hidden py-3 px-2 scrollbar-thin"
    >
      <div
        v-if="Object.keys(filteredManifest).length === 0"
        class="px-3 py-6 text-center space-y-2"
      >
        <p class="text-sm text-muted-foreground">
          No results for "{{ searchQuery }}"
        </p>
        <a
          href="mailto:support@heym.run"
          class="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          <Mail class="w-3.5 h-3.5" />
          <span>Contact support</span>
        </a>
      </div>

      <div
        v-for="(category, categoryId) in filteredManifest"
        :key="categoryId"
        class="docs-category"
      >
        <button
          type="button"
          class="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-sm font-medium text-foreground hover:bg-muted/50 transition-colors text-left"
          @click="toggleCategory(categoryId)"
        >
          <ChevronDown
            v-if="isCategoryExpanded(categoryId)"
            class="w-4 h-4 text-muted-foreground shrink-0"
          />
          <ChevronRight
            v-else
            class="w-4 h-4 text-muted-foreground shrink-0"
          />
          <span>{{ category.label }}</span>
        </button>

        <div
          v-show="isCategoryExpanded(categoryId)"
          class="docs-category-items pl-2 mt-0.5 space-y-0.5"
        >
          <router-link
            v-for="item in category.items"
            :key="item.slug"
            :to="getDocPath(categoryId, item.slug)"
            :data-active="isItemActive(categoryId, item.slug) || undefined"
            :class="cn(
              'block px-3 py-2 rounded-lg text-sm transition-colors',
              isItemActive(categoryId, item.slug)
                ? 'bg-primary/15 text-primary font-medium'
                : 'text-muted-foreground hover:text-foreground hover:bg-muted/40'
            )"
            @click="emit('navigate')"
          >
            {{ item.title }}
          </router-link>
        </div>
      </div>
    </nav>

    <div class="p-2 border-t border-border/40">
      <a
        href="mailto:support@heym.run"
        class="flex items-center gap-2 px-3 py-2 rounded-xl text-sm text-muted-foreground hover:text-foreground hover:bg-muted/50 transition-colors"
      >
        <Mail class="w-4 h-4 shrink-0" />
        <span>support@heym.run</span>
      </a>
    </div>
  </aside>
</template>