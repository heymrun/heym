import { defineComponent, onBeforeUnmount, watch } from "vue";
import { useEventListener, useThrottleFn } from "@vueuse/core";
import { useVueFlow } from "@vue-flow/core";

import type { FlowViewport } from "@/features/collab/types";
import { followerCount } from "@/features/collab/followSignals";
import { hoverHint } from "@/features/collab/uiReplay";
import { useCollabContext } from "@/features/collab/useCanvasCollab";

const VIEWPORT_REPORT_MS = 100;

/**
 * Lives inside VueFlow so it reaches the right Vue Flow instance: reports this canvas's
 * viewport, pointer and drags, applies a followed viewport, and stops following on a manual
 * pan or zoom.
 */
function hoveredNodeId(target: EventTarget | null): string | null {
  return target instanceof Element
    ? (target.closest(".vue-flow__node")?.getAttribute("data-id") ?? null)
    : null;
}

export default defineComponent({
  name: "CollabCanvasBridge",
  setup() {
    const collab = useCollabContext();
    if (!collab) return (): null => null;
    const {
      viewport,
      dimensions,
      fitBounds,
      screenToFlowCoordinate,
      onMoveStart,
      onNodeDrag,
      vueFlowRef,
    } = useVueFlow();

    const report = useThrottleFn(
      () => {
        collab.reportViewport({
          x: viewport.value.x,
          y: viewport.value.y,
          zoom: viewport.value.zoom,
          width: dimensions.value.width,
          height: dimensions.value.height,
        });
      },
      VIEWPORT_REPORT_MS,
      true,
    );
    watch(
      [viewport, dimensions],
      () => {
        void report();
      },
      { deep: true, immediate: true },
    );

    collab.setViewportApplier((target: FlowViewport) => {
      if (!target.zoom || !target.width || !target.height) return;
      void fitBounds(
        {
          x: -target.x / target.zoom,
          y: -target.y / target.zoom,
          width: target.width / target.zoom,
          height: target.height / target.zoom,
        },
        { padding: 0, duration: 150 },
      );
    });
    onBeforeUnmount(() => collab.setViewportApplier(null));

    onMoveStart(({ event }) => {
      // Programmatic moves (fitBounds) carry a zoom event without a source event.
      const userDriven =
        event instanceof Event ||
        Boolean((event as { sourceEvent?: unknown } | null)?.sourceEvent);
      if (userDriven) collab.stopFollowing();
    });

    onNodeDrag(({ nodes }) => {
      collab.sendDragPositions(
        nodes.map((node) => ({ id: node.id, x: node.position.x, y: node.position.y })),
      );
    });

    useEventListener(vueFlowRef, "pointermove", (event: PointerEvent) => {
      const point = screenToFlowCoordinate({ x: event.clientX, y: event.clientY });
      collab.reportCursor({
        region: "canvas",
        anchor: "start",
        x: point.x,
        y: point.y,
        hint: followerCount.value > 0 ? hoverHint(event.target) : null,
        node: hoveredNodeId(event.target),
      });
    });
    useEventListener(vueFlowRef, "pointerleave", () => collab.reportCursor(null));
    useEventListener(vueFlowRef, "pointerdown", (event: PointerEvent) => {
      const point = screenToFlowCoordinate({ x: event.clientX, y: event.clientY });
      collab.reportClick({ region: "canvas", anchor: "start", x: point.x, y: point.y });
    });

    return (): null => null;
  },
});
