import { createRenderer, h, nextTick, ref, ssrContextKey } from "vue";
import { describe, expect, it, vi } from "vitest";

import type { HitlFilter } from "@/types/dashboard";
import HitlCarousel from "@/components/Dashboards/HitlCarousel.vue";
import { hitlPortKey, type HitlPort } from "@/ports";

// DOMPurify needs a browser DOM; these tests check which reviews are asked for.
vi.mock("@/lib/markdown", () => ({ renderChartMarkdown: (text: string): string => text }));

// No DOM in this project's tests: a renderer whose host operations do nothing still runs
// the component's lifecycle, which is what loads the inbox. Vitest compiles components for
// SSR, so they also expect an SSR context.
const { createApp } = createRenderer<object, object>({
  createElement: () => ({}),
  insert: () => {},
  remove: () => {},
  setElementText: () => {},
  createText: () => ({}),
  createComment: () => ({}),
  setText: () => {},
  patchProp: () => {},
  parentNode: () => null,
  nextSibling: () => null,
});

function mountCarousel(filter: HitlFilter | null): {
  inbox: ReturnType<typeof vi.fn>;
  setFilter: (next: HitlFilter | null) => void;
} {
  const current = ref<HitlFilter | null>(filter);
  const inbox = vi.fn(async () => ({ pending_total: 0, items: [] }));
  const port: HitlPort = { inbox, inboxDecide: vi.fn(), openRun: vi.fn() };
  const app = createApp({ render: () => h(HitlCarousel, { filter: current.value }) });
  app.provide(hitlPortKey, port);
  app.provide(ssrContextKey, { modules: new Set() });
  app.mount({});
  return {
    inbox,
    setFilter: (next) => {
      current.value = next;
    },
  };
}

describe("HitlCarousel", () => {
  it("asks for every review when the widget has no filter", () => {
    const { inbox } = mountCarousel(null);

    expect(inbox).toHaveBeenCalledWith(null);
  });

  it("asks only for the chosen workflow and step", () => {
    const { inbox } = mountCarousel({ workflow_id: "wf-1", node_id: "agent-1" });

    expect(inbox).toHaveBeenCalledWith({ workflow_id: "wf-1", node_id: "agent-1" });
  });

  it("reloads when the filter changes, and not when it is the same", async () => {
    const { inbox, setFilter } = mountCarousel({ workflow_id: "wf-1", node_id: null });

    setFilter({ workflow_id: "wf-1", node_id: null });
    await nextTick();
    expect(inbox).toHaveBeenCalledTimes(1);

    setFilter({ workflow_id: "wf-1", node_id: "agent-2" });
    await nextTick();
    expect(inbox).toHaveBeenCalledTimes(2);
    expect(inbox).toHaveBeenLastCalledWith({ workflow_id: "wf-1", node_id: "agent-2" });
  });
});
