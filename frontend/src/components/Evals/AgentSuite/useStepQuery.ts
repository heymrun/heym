import { watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import type { AgentSuiteStep } from "@/components/Evals/AgentSuite/AgentSuiteStepper.vue";

/**
 * Keeps a new suite's step in the URL (`?step=2`), so the browser's back button returns
 * to the previous step instead of leaving the page.
 */
export function useStepQuery(
  onStep: (step: AgentSuiteStep) => void,
  enabled: () => boolean,
): { pushStep: (step: AgentSuiteStep) => void } {
  const route = useRoute();
  const router = useRouter();

  watch(
    () => route.query.step,
    (raw) => {
      if (!enabled()) return;
      const step = Number(raw);
      onStep(step === 2 || step === 3 ? step : 1);
    },
    { immediate: true },
  );

  function pushStep(step: AgentSuiteStep): void {
    const query = { ...route.query };
    if (step === 1) delete query.step;
    else query.step = String(step);
    void router.push({ query });
  }

  return { pushStep };
}
