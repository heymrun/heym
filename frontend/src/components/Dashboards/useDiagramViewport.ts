import { onBeforeUnmount, onMounted, ref, type Ref } from "vue";

import type { DiagramSize } from "@/components/Dashboards/diagramLayout";

/** Observe the host box without letting the SVG's intrinsic size grow that box. */
export function useDiagramViewport(): {
  container: Ref<HTMLElement | null>;
  size: Ref<DiagramSize>;
} {
  const container = ref<HTMLElement | null>(null);
  const size = ref<DiagramSize>({ width: 640, height: 240 });
  let observer: ResizeObserver | null = null;

  onMounted(() => {
    if (!container.value) return;
    const measure = (width: number, height: number): void => {
      if (width > 0 && height > 0) {
        size.value = { width: Math.floor(width), height: Math.floor(height) };
      }
    };
    measure(container.value.clientWidth, container.value.clientHeight);
    observer = new ResizeObserver(([entry]) => {
      if (entry) measure(entry.contentRect.width, entry.contentRect.height);
    });
    observer.observe(container.value);
  });

  onBeforeUnmount(() => observer?.disconnect());
  return { container, size };
}
