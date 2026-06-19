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
  "isOrchestrator",
  "isSubAgent",
  "playwrightSteps",
  "playwrightAuthFallbackSteps",
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
  "mappings",
  "inputFields",
]);

const SELECT_FIELDS = new Set([
  "model",
  "credentialId",
  "variableType",
  "ragOperation",
  "gristOperation",
  "githubOperation",
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
  requestTimeoutSeconds: "Request Timeout (s)",
  maxToolIterations: "Max Iterations",
  duration: "Duration (ms)",
  ragOperation: "RAG Operation",
  gristOperation: "Grist Operation",
  githubOperation: "GitHub Operation",
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
  mappings: "Mappings",
  inputFields: "Input Fields",
};

interface MappingPreviewRow {
  key?: unknown;
  value?: unknown;
}

interface InputFieldPreviewRow {
  key?: unknown;
  defaultValue?: unknown;
}

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
      const textValue = formatPreviewValue(key, value);
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

function formatPreviewValue(key: string, value: unknown): string {
  if (key === "mappings" && Array.isArray(value)) {
    return value
      .map((entry, index) => {
        const mapping = entry as MappingPreviewRow;
        const mappingKey = String(mapping.key || `field_${index + 1}`);
        const mappingValue = mapping.value === undefined ? "" : String(mapping.value);
        return `${mappingKey}: ${mappingValue}`;
      })
      .join("\n");
  }
  if (key === "inputFields" && Array.isArray(value)) {
    return value
      .map((entry, index) => {
        const inputField = entry as InputFieldPreviewRow;
        const fieldKey = String(inputField.key || `field_${index + 1}`);
        if (inputField.defaultValue === undefined || inputField.defaultValue === "") {
          return fieldKey;
        }
        return `${fieldKey}: ${String(inputField.defaultValue)}`;
      })
      .join("\n");
  }
  return Array.isArray(value) ? JSON.stringify(value) : String(value);
}

function formatKey(key: string): string {
  return key.replace(/([A-Z])/g, " $1").replace(/^./, (value) => value.toUpperCase()).trim();
}
