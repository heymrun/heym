<script setup lang="ts">
import { computed } from "vue";
import { BookOpen, ExternalLink, MoveRight, Sparkles, X } from "lucide-vue-next";

import ShowcaseDetails from "@/features/showcase/components/ShowcaseDetails.vue";
import ShowcaseHighlights from "@/features/showcase/components/ShowcaseHighlights.vue";
import ShowcaseSummary from "@/features/showcase/components/ShowcaseSummary.vue";
import { getShowcaseIntroContent, getShowcaseIntroVideo } from "@/features/showcase/showcaseIntroRegistry";
import Button from "@/components/ui/Button.vue";
import type { ShowcaseAction, ShowcaseDefinition } from "@/features/showcase/showcase.types";
import { cn } from "@/lib/utils";

interface Props {
  open: boolean;
  definition: ShowcaseDefinition;
  expandedDetailId: string | null;
  askButtonLabel: string;
  askButtonDescription: string;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "askAboutPage"): void;
  (e: "selectAction", action: ShowcaseAction): void;
  (e: "toggleDetail", detailId: string): void;
}>();

function actionIcon(action: ShowcaseAction): typeof BookOpen {
  if (action.kind === "external") return ExternalLink;
  if (action.kind === "route") return MoveRight;
  return BookOpen;
}

const introVideoSrc = computed(() => getShowcaseIntroVideo(props.definition.id));
const introContent = computed(() => getShowcaseIntroContent(props.definition.id));
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-[34] bg-slate-950/14 backdrop-blur-[1.5px]"
    aria-hidden="true"
    @click="emit('close')"
  />

  <aside
    :class="cn(
      'showcase-panel fixed right-0 top-0 z-[45] h-screen border-l border-border/60 bg-card/96 shadow-2xl backdrop-blur-xl transition-transform duration-300 ease-out',
      open ? 'translate-x-0' : 'translate-x-full pointer-events-none'
    )"
    :style="{ width: 'var(--showcase-width)' }"
    aria-label="Contextual showcase panel"
  >
    <div class="relative flex h-full flex-col overflow-hidden">
      <div class="border-b border-border/60 px-5 py-4">
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="inline-flex items-center gap-2 rounded-full border border-sky-500/20 bg-sky-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-600 dark:text-sky-300">
              <Sparkles class="h-3.5 w-3.5" />
              Guidelines
            </div>
            <p class="mt-3 text-sm text-muted-foreground">
              A short, contextual explanation of what this page is for.
            </p>
          </div>

          <Button
            variant="ghost"
            size="icon"
            class="h-10 w-10 shrink-0"
            aria-label="Close showcase panel"
            @click="emit('close')"
          >
            <X class="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div class="flex-1 space-y-6 overflow-y-auto px-5 py-5">
        <section
          v-if="introVideoSrc"
          class="rounded-2xl border border-border/70 bg-background/70 p-3"
        >
          <p class="text-sm font-semibold text-foreground">
            {{ introContent?.title ?? "Quick overview" }}
          </p>
          <p class="mt-1 text-xs text-muted-foreground">
            {{ introContent?.description ?? "Watch this short guide for the current screen." }}
          </p>
          <video
            class="mt-3 w-full overflow-hidden rounded-lg border border-border/60 bg-black/90"
            :src="introVideoSrc"
            controls
            playsinline
            preload="metadata"
          />
        </section>
        <ShowcaseSummary :definition="definition" />
        <ShowcaseHighlights :definition="definition" />
        <ShowcaseDetails
          :definition="definition"
          :expanded-detail-id="expandedDetailId"
          @toggle="emit('toggleDetail', $event)"
        />
      </div>

      <div class="border-t border-border/60 px-5 py-4">
        <div class="space-y-2">
          <button
            type="button"
            class="group flex w-full items-center justify-between gap-3 rounded-2xl border border-sky-500/20 bg-sky-500/[0.08] px-4 py-3 text-left transition-colors duration-200 hover:border-sky-500/35 hover:bg-sky-500/[0.12]"
            @click="emit('askAboutPage')"
          >
            <div class="min-w-0">
              <p class="text-sm font-medium text-foreground">
                {{ askButtonLabel }}
              </p>
              <p class="mt-1 text-xs leading-5 text-muted-foreground">
                {{ askButtonDescription }}
              </p>
            </div>
            <MoveRight class="h-4 w-4 shrink-0 text-sky-500 transition-transform duration-200 group-hover:translate-x-0.5" />
          </button>

          <button
            v-for="action in definition.actions"
            :key="action.id"
            type="button"
            class="group flex w-full items-center justify-between gap-3 rounded-2xl border border-border/70 bg-background/70 px-4 py-3 text-left transition-colors duration-200 hover:border-primary/30 hover:bg-primary/[0.04]"
            @click="emit('selectAction', action)"
          >
            <div class="min-w-0">
              <p class="text-sm font-medium text-foreground">
                {{ action.label }}
              </p>
              <p class="mt-1 text-xs leading-5 text-muted-foreground">
                {{ action.description }}
              </p>
            </div>
            <component
              :is="actionIcon(action)"
              class="h-4 w-4 shrink-0 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-primary"
            />
          </button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
@media (prefers-reduced-motion: reduce) {
  .showcase-panel,
  .showcase-panel :deep(*) {
    transition-duration: 0ms !important;
    animation: none !important;
  }
}
</style>
