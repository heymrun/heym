import type { ComputedRef } from "vue";

import type { WorkflowNode } from "@/types/workflow";
import {
  getOutlookCalendarFields,
  type OutlookCalendarField,
  type OutlookCalendarFieldKey,
} from "@/lib/outlookCalendarFields";
import {
  useOperationExpressionFields,
  type OperationExpressionFields,
} from "./operationExpressionFields";

/** Expression dialog navigation over the Outlook Calendar operation's fields. */
export function useOutlookCalendarExpressionFields(
  node: ComputedRef<WorkflowNode | null>,
): OperationExpressionFields<OutlookCalendarFieldKey, OutlookCalendarField> {
  return useOperationExpressionFields<OutlookCalendarFieldKey, OutlookCalendarField>(
    node,
    "outlookCalendar",
    (data) => getOutlookCalendarFields(data.ocOperation),
    (data) => data.ocOperation,
  );
}
