<script setup lang="ts">
import { computed } from "vue";
import { BookOpen, ExternalLink, MoveRight, Sparkles, X } from "lucide-vue-next";

import ShowcaseDetails from "@/features/showcase/components/ShowcaseDetails.vue";
import ShowcaseHighlights from "@/features/showcase/components/ShowcaseHighlights.vue";
import ShowcaseSummary from "@/features/showcase/components/ShowcaseSummary.vue";
import { getShowcaseIntroContent, getShowcaseIntroVideo } from "@/features/showcase/showcaseIntroRegistry";
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
  <Teleport to="body">
    <Transition name="showcase-sheet">
      <div
        v-if="open"
        class="fixed inset-0 z-[55] flex items-end"
      >
        <div
          class="absolute inset-0 bg-slate-950/28 backdrop-blur-[1.5px]"
          @click="emit('close')"
        />

        <section class="showcase-sheet relative z-[56] w-full rounded-t-[28px] border border-border/60 bg-card/98 px-4 pb-5 pt-3 shadow-2xl backdrop-blur-xl">
          <div class="mx-auto mb-3 h-1.5 w-16 rounded-full bg-border/80" />

          <div class="mb-4 flex items-start justify-between gap-3">
            <div>
              <div class="inline-flex items-center gap-2 rounded-full border border-sky-500/20 bg-sky-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-sky-600 dark:text-sky-300">
                <Sparkles class="h-3.5 w-3.5" />
                Page Guide
              </div>
              <p class="mt-2 text-sm text-muted-foreground">
                Quick orientation for this surface.
              </p>
            </div>

            <button
              type="button"
              class="flex h-10 w-10 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
              aria-label="Close showcase sheet"
              @click="emit('close')"
            >
              <X class="h-4 w-4" />
            </button>
          </div>

          <div class="max-h-[78vh] space-y-6 overflow-y-auto pb-2">
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

            <div class="space-y-2">
              <button
                type="button"
                :class="cn(
                  'group flex w-full items-center justify-between gap-3 rounded-2xl border border-sky-500/20 bg-sky-500/[0.08] px-4 py-3 text-left transition-colors duration-200',
                  'hover:border-sky-500/35 hover:bg-sky-500/[0.12]'
                )"
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
                <MoveRight class="h-4 w-4 shrink-0 text-sky-500" />
              </button>

              <button
                v-for="action in definition.actions"
                :key="action.id"
                type="button"
                :class="cn(
                  'group flex w-full items-center justify-between gap-3 rounded-2xl border border-border/70 bg-background/70 px-4 py-3 text-left transition-colors duration-200',
                  'hover:border-primary/30 hover:bg-primary/[0.04]'
                )"
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
                  class="h-4 w-4 shrink-0 text-muted-foreground"
                />
              </button>
            </div>
          </div>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.showcase-sheet-enter-active,
.showcase-sheet-leave-active {
  transition: opacity 0.22s ease;
}

.showcase-sheet-enter-from,
.showcase-sheet-leave-to {
  opacity: 0;
}

.showcase-sheet {
  animation: showcase-sheet-slide 0.28s cubic-bezier(0.22, 1, 0.36, 1);
}

@keyframes showcase-sheet-slide {
  from {
    transform: translateY(18px);
  }
  to {
    transform: translateY(0);
  }
}

@media (prefers-reduced-motion: reduce) {
  .showcase-sheet,
  .showcase-sheet-enter-active,
  .showcase-sheet-leave-active {
    animation: none;
    transition: none;
  }
}
</style>
