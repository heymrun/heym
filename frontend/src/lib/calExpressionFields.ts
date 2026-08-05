export type CalExpressionFieldKey = "calWebhookId" | "calWebhook";

export interface CalExpressionField {
  key: CalExpressionFieldKey;
  label: string;
}

/** Returns ordered expression-evaluate dialog slots for a Cal.com operation. */
export function getCalExpressionFields(operation: string): CalExpressionField[] {
  if (operation === "createWebhook") {
    return [{ key: "calWebhook", label: "Webhook Data" }];
  }
  if (operation === "updateWebhook") {
    return [
      { key: "calWebhookId", label: "Webhook ID" },
      { key: "calWebhook", label: "Webhook Data" },
    ];
  }
  if (operation === "deleteWebhook") {
    return [{ key: "calWebhookId", label: "Webhook ID" }];
  }
  return [];
}
