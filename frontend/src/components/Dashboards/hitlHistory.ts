import type { InjectionKey } from "vue";

/** Opens the dashboard history dialog on one run, without leaving the page. */
export interface OpenHitlHistory {
  (workflowId: string, executionId: string): void;
}

export const openHitlHistoryKey: InjectionKey<OpenHitlHistory> = Symbol("openHitlHistory");

/** The review the widget header's history icon should open. */
export interface HitlHistoryTarget {
  workflowId: string;
  executionId: string;
}

export interface SetHitlHistoryTarget {
  (target: HitlHistoryTarget | null): void;
}

export const setHitlHistoryTargetKey: InjectionKey<SetHitlHistoryTarget> = Symbol(
  "setHitlHistoryTarget",
);
