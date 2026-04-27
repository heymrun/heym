export interface ReadonlyPreviewDisplayField {
  key: string;
  label: string;
  value: string;
  kind: "textarea" | "select" | "input" | "boolean";
  isTrue?: boolean;
}

const SKIP_FIELDS = new Set([
  "nodeId",
  "nodeType",
  "label",
  "active",
  "status",
  "tools",
  "mcpConnections",
  "skills",
  "subAgentLabels",
  "inputFields",
  "isOrchestrator",
  "isSubAgent",
  "playwrightSteps",
  "playwrightAuthFallbackSteps",
  "mappings",
  "cases",
  "executeTargets",
  "outputSchema",
  "guardrails",
  "crawlerSelectors",
  "hitlEnabled",
  "hitlSummary",
  "allowDownstream",
  "jsonOutputEnabled",
]);

const TEXTAREA_FIELDS = new Set([
  "systemInstruction",
  "userMessage",
  "curl",
  "websocketHeaders",
  "websocketMessage",
  "cronExpression",
  "variableValue",
  "executeInput",
  "logMessage",
  "errorMessage",
  "playwrightCode",
  "rabbitmqMessageBody",
  "arrayExpression",
]);

const SELECT_FIELDS = new Set([
  "model",
  "credentialId",
  "variableType",
  "ragOperation",
  "gristOperation",
  "redisOperation",
  "rabbitmqOperation",
  "websocketTriggerEvents",
  "dataTableOperation",
  "driveOperation",
  "executeWorkflowId",
  "vectorStoreId",
  "bqOperation",
  "gsOperation",
]);

const FIELD_LABELS: Record<string, string> = {
  model: "Model",
  credentialId: "Credential",
  temperature: "Temperature",
  systemInstruction: "System Instruction",
  userMessage: "User Message",
  condition: "Condition",
  expression: "Expression",
  curl: "cURL",
  websocketUrl: "WebSocket URL",
  websocketHeaders: "WebSocket Headers",
  websocketSubprotocols: "WebSocket Subprotocols",
  websocketMessage: "WebSocket Message",
  websocketTriggerEvents: "WebSocket Trigger Events",
  cronExpression: "Cron Expression",
  pollIntervalMinutes: "Poll Interval (Minutes)",
  variableName: "Variable Name",
  variableValue: "Variable Value",
  variableType: "Variable Type",
  executeInput: "Execute Input",
  executeWorkflowId: "Target Workflow",
  logMessage: "Log Message",
  errorMessage: "Error Message",
  httpStatusCode: "HTTP Status Code",
  toolTimeoutSeconds: "Tool Timeout (s)",
  maxToolIterations: "Max Iterations",
  duration: "Duration (ms)",
  ragOperation: "RAG Operation",
  gristOperation: "Grist Operation",
  redisOperation: "Redis Operation",
  rabbitmqOperation: "RabbitMQ Operation",
  rabbitmqMessageBody: "Message Body",
  dataTableOperation: "Operation",
  driveOperation: "Drive Operation",
  vectorStoreId: "Vector Store",
  arrayExpression: "Array Expression",
  playwrightCode: "Code",
  playwrightHeadless: "Headless",
  playwrightTimeout: "Timeout (ms)",
  playwrightCaptureNetwork: "Capture Network",
  playwrightAuthEnabled: "Auth Enabled",
  jsonOutputSchema: "JSON Schema",
  value: "Value",
  bqOperation: "BigQuery Operation",
  gsOperation: "Google Sheets Operation",
};

export function getReadonlyPreviewFields(
  data: Record<string, unknown>,
): ReadonlyPreviewDisplayField[] {
  return Object.entries(data)
    .filter(([key, value]) => {
      if (SKIP_FIELDS.has(key)) return false;
      if (value === null || value === undefined || value === "") return false;
      if (Array.isArray(value) && value.length === 0) return false;
      if (typeof value === "object" && !Array.isArray(value)) return false;
      return true;
    })
    .map(([key, value]) => {
      const textValue = Array.isArray(value) ? JSON.stringify(value) : String(value);
      const label = FIELD_LABELS[key] ?? formatKey(key);
      if (typeof value === "boolean") {
        return { key, label, value: textValue, kind: "boolean", isTrue: value };
      }
      if (TEXTAREA_FIELDS.has(key) || textValue.length > 80) {
        return { key, label, value: textValue, kind: "textarea" };
      }
      if (SELECT_FIELDS.has(key)) {
        return { key, label, value: textValue, kind: "select" };
      }
      return { key, label, value: textValue, kind: "input" };
    });
}

function formatKey(key: string): string {
  return key.replace(/([A-Z])/g, " $1").replace(/^./, (value) => value.toUpperCase()).trim();
}
