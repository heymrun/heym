<script setup lang="ts">
import { ref } from "vue";

import ImageLightbox from "@/components/ui/ImageLightbox.vue";

const props = defineProps<{
  /** Images of the selected span's output. */
  srcs: string[];
  /** Every image of the run in execution order; the lightbox cycles through it. */
  gallery: string[];
}>();

const lightboxSrc = ref<string | null>(null);
const lightboxSrcs = ref<string[]>([]);

function openLightbox(src: string): void {
  const unique = [...new Set(props.gallery.length > 0 ? props.gallery : props.srcs)];
  if (!unique.includes(src)) {
    unique.unshift(src);
  }
  lightboxSrcs.value = unique;
  lightboxSrc.value = src;
}

function closeLightbox(): void {
  lightboxSrc.value = null;
  lightboxSrcs.value = [];
}
</script>

<template>
  <div
    class="mb-2 flex flex-wrap gap-1.5"
    data-testid="execution-span-images"
  >
    <button
      v-for="(src, idx) in srcs"
      :key="idx"
      type="button"
      class="rounded border border-border/60 transition-all hover:ring-2 hover:ring-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      :aria-label="`Open image ${idx + 1} of ${srcs.length}`"
      @click="openLightbox(src)"
    >
      <img
        :src="src"
        :alt="`Output image ${idx + 1}`"
        class="h-16 w-16 rounded object-cover"
      >
    </button>
  </div>
  <ImageLightbox
    :src="lightboxSrc"
    :srcs="lightboxSrcs"
    alt="Span output image"
    @update:src="lightboxSrc = $event"
    @close="closeLightbox"
  />
</template>
