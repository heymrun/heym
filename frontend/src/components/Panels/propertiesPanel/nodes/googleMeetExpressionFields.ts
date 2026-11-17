import type { ComputedRef } from "vue";

import type { WorkflowNode } from "@/types/workflow";
import {
  getGoogleMeetFields,
  type GoogleMeetField,
  type GoogleMeetFieldKey,
} from "@/lib/googleMeetFields";
import {
  useOperationExpressionFields,
  type OperationExpressionFields,
} from "./operationExpressionFields";

/** Keep operation-specific form state outside the shared properties controller. */
export function useGoogleMeetExpressionFields(
  node: ComputedRef<WorkflowNode | null>,
): OperationExpressionFields<GoogleMeetFieldKey, GoogleMeetField> {
  return useOperationExpressionFields<GoogleMeetFieldKey, GoogleMeetField>(
    node,
    "googleMeet",
    (data) => getGoogleMeetFields(data.gmOperation),
    (data) => data.gmOperation,
  );
}
