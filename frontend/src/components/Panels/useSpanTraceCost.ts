import { computed, ref, watch, type ComputedRef, type Ref } from "vue";

import type { SpanItem } from "@/components/Panels/executionTimeline";
import { isSpanSettled } from "@/components/Panels/executionTimeline";
import { traceApi } from "@/services/api";

/**
 * USD cost of the selected span's LLM trace, priced like the Traces tab. Null while it
 * loads, for unpriced models, and for spans without a trace. Each trace is fetched once.
 */
export function useSpanTraceCost(selectedSpan: Ref<SpanItem | null>): ComputedRef<string | null> {
  const costByTraceId = ref<Record<string, string | null>>({});
  const loading = new Set<string>();

  const settledTraceId = computed(() => {
    const span = selectedSpan.value;
    return span && isSpanSettled(span) ? span.traceId : null;
  });

  watch(
    settledTraceId,
    async (traceId) => {
      if (!traceId || traceId in costByTraceId.value || loading.has(traceId)) return;
      loading.add(traceId);
      try {
        const trace = await traceApi.get(traceId);
        costByTraceId.value = {
          ...costByTraceId.value,
          [traceId]: trace.is_priced ? trace.cost_usd : null,
        };
      } catch {
        // Cost is optional detail: leave it out, and try again when the span is reopened.
      } finally {
        loading.delete(traceId);
      }
    },
    { immediate: true },
  );

  return computed(() =>
    settledTraceId.value ? (costByTraceId.value[settledTraceId.value] ?? null) : null,
  );
}
