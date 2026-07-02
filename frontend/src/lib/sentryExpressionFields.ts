import {
  getSentryOperationMetadata,
  type SentryFieldKey,
  type SentryFieldMetadata,
} from "@/lib/sentryOperationMetadata";

export type SentryExpressionFieldKey = SentryFieldKey;
export type SentryExpressionField = SentryFieldMetadata;

/** Returns ordered expression-evaluate dialog slots for the given Sentry operation. */
export function getSentryExpressionFields(operation: string): SentryExpressionField[] {
  return [...getSentryOperationMetadata(operation).fields];
}
