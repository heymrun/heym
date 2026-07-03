import { expect, test, type Page } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

const e2eBackendUrl = `http://127.0.0.1:${process.env.E2E_BACKEND_PORT || "10106"}`;

interface WorkflowNodeFixture {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
}

interface WorkflowEdgeFixture {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
}

interface NodeResultEvent {
  node_label: string;
  status: string;
  output: Record<string, unknown>;
  error: string | null;
}

interface ExecutionCompleteEvent {
  type: "execution_complete";
  status: string;
  outputs: Record<string, unknown>;
  node_results: NodeResultEvent[];
  execution_time_ms: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function workflowNode(
  id: string,
  type: string,
  x: number,
  y: number,
  data: Record<string, unknown>,
): WorkflowNodeFixture {
  return { id, type, position: { x, y }, data };
}

function workflowEdge(
  id: string,
  source: string,
  target: string,
  handles: Pick<WorkflowEdgeFixture, "sourceHandle" | "targetHandle"> = {},
): WorkflowEdgeFixture {
  return { id, source, target, ...handles };
}

function parseNodeResult(value: unknown): NodeResultEvent {
  const row = isRecord(value) ? value : {};
  return {
    node_label: typeof row.node_label === "string" ? row.node_label : "",
    status: typeof row.status === "string" ? row.status : "",
    output: isRecord(row.output) ? row.output : { value: row.output },
    error: typeof row.error === "string" ? row.error : null,
  };
}

function parseExecutionComplete(sseBody: string): ExecutionCompleteEvent {
  const messages = sseBody.split("\n\n");

  for (const message of messages) {
    const dataLines = message.split("\n").filter((line) => line.startsWith("data: "));
    for (const line of dataLines) {
      const parsed = JSON.parse(line.slice("data: ".length)) as unknown;
      if (!isRecord(parsed) || parsed.type !== "execution_complete") {
        continue;
      }

      return {
        type: "execution_complete",
        status: typeof parsed.status === "string" ? parsed.status : "",
        outputs: isRecord(parsed.outputs) ? parsed.outputs : {},
        node_results: Array.isArray(parsed.node_results)
          ? parsed.node_results.map(parseNodeResult)
          : [],
        execution_time_ms:
          typeof parsed.execution_time_ms === "number" ? parsed.execution_time_ms : 0,
      };
    }
  }

  throw new Error(`Execution completion event not found in SSE body:\n${sseBody}`);
}

async function waitForExecutionComplete(
  page: Page,
  workflowId: string,
): Promise<ExecutionCompleteEvent> {
  const response = await page.waitForResponse(
    (candidate) =>
      candidate.request().method() === "POST" &&
      new URL(candidate.url()).pathname === `/api/workflows/${workflowId}/execute/stream`,
    { timeout: 30_000 },
  );
  const responseBody = await response.text();
  expect(response.ok(), responseBody).toBeTruthy();
  return parseExecutionComplete(responseBody);
}

async function runWorkflowFromCanvas(
  page: Page,
  workflowId: string,
  nodeCount: number,
  inputs: Record<string, string> = {},
): Promise<ExecutionCompleteEvent> {
  await page.goto(`/workflows/${workflowId}`);
  await expect(page.locator(".vue-flow__node")).toHaveCount(nodeCount);

  for (const [key, value] of Object.entries(inputs)) {
    await page.getByPlaceholder(`Enter ${key}...`).fill(value);
  }

  const completionPromise = waitForExecutionComplete(page, workflowId);
  await page.getByRole("button", { name: "Run Workflow" }).click();
  const completion = await completionPromise;
  await expect(page.getByText("Last Executed Node")).toBeVisible();
  return completion;
}

function outputResult(event: ExecutionCompleteEvent, label: string): unknown {
  const output = event.outputs[label];
  if (!isRecord(output)) {
    throw new Error(`Missing output for ${label}`);
  }
  return output.result;
}

function firstOutputResult(event: ExecutionCompleteEvent): unknown {
  const firstOutput = Object.values(event.outputs)[0];
  if (!isRecord(firstOutput)) {
    throw new Error("Execution did not return a result output");
  }
  return firstOutput.result;
}

function nodeOutputs(event: ExecutionCompleteEvent, label: string): Record<string, unknown>[] {
  return event.node_results
    .filter((row) => row.node_label === label && row.status === "success")
    .map((row) => row.output);
}

function singleNodeOutput(event: ExecutionCompleteEvent, label: string): Record<string, unknown> {
  const outputs = nodeOutputs(event, label);
  expect(outputs).toHaveLength(1);
  return outputs[0] ?? {};
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("runs a UUID condition workflow and returns the matching branch", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Canvas UUID Condition ${Date.now()}`,
    [
      workflowNode("input_text", "textInput", 80, 180, {
        label: "requestText",
        value: "",
        inputFields: [{ key: "text" }],
      }),
      workflowNode("set_uuid", "set", 340, 180, {
        label: "generateUuid",
        mappings: [
          { key: "uuid", value: "$UUID" },
          { key: "source", value: "$requestText.body.text" },
        ],
      }),
      workflowNode("condition_uuid", "condition", 600, 180, {
        label: "uuidHasTwoOnes",
        condition: '$generateUuid.uuid.length - $generateUuid.uuid.replaceAll("1", "").length == 2',
      }),
      workflowNode("set_okey", "set", 860, 80, {
        label: "okeyResult",
        mappings: [{ key: "verdict", value: "okey" }],
      }),
      workflowNode("set_not", "set", 860, 280, {
        label: "notResult",
        mappings: [{ key: "verdict", value: "not" }],
      }),
      workflowNode("output_okey", "output", 1120, 80, {
        label: "okeyOutput",
        message: "$okeyResult.verdict",
      }),
      workflowNode("output_not", "output", 1120, 280, {
        label: "notOutput",
        message: "$notResult.verdict",
      }),
    ],
    [
      workflowEdge("edge_input_uuid", "input_text", "set_uuid"),
      workflowEdge("edge_uuid_condition", "set_uuid", "condition_uuid"),
      workflowEdge("edge_condition_okey", "condition_uuid", "set_okey", {
        sourceHandle: "true",
      }),
      workflowEdge("edge_condition_not", "condition_uuid", "set_not", {
        sourceHandle: "false",
      }),
      workflowEdge("edge_okey_output", "set_okey", "output_okey"),
      workflowEdge("edge_not_output", "set_not", "output_not"),
    ],
  );

  try {
    const result = await runWorkflowFromCanvas(page, workflow.id, 7, {
      text: "create a uuid",
    });
    const uuidOutput = singleNodeOutput(result, "generateUuid");
    const generatedUuid = String(uuidOutput.uuid);
    const onesCount = [...generatedUuid].filter((character) => character === "1").length;
    const expectedVerdict = onesCount === 2 ? "okey" : "not";

    expect(result.status).toBe("success");
    expect(generatedUuid).toMatch(/^[0-9a-f]{32}$/);
    expect(firstOutputResult(result)).toBe(expectedVerdict);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("uppercases an input parameter and logs it to the console", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Canvas Uppercase Log ${Date.now()}`,
    [
      workflowNode("input_value", "textInput", 80, 160, {
        label: "valueInput",
        value: "",
        inputFields: [{ key: "text" }],
      }),
      workflowNode("set_uppercase", "set", 340, 160, {
        label: "uppercaseValue",
        mappings: [{ key: "text", value: "$valueInput.body.text.toUpperCase()" }],
      }),
      workflowNode("console_uppercase", "consoleLog", 600, 160, {
        label: "logUppercase",
        logMessage: "$uppercaseValue.text",
      }),
      workflowNode("output_uppercase", "output", 860, 160, {
        label: "uppercaseOutput",
        message: "$logUppercase.logMessage",
      }),
    ],
    [
      workflowEdge("edge_input_uppercase", "input_value", "set_uppercase"),
      workflowEdge("edge_uppercase_log", "set_uppercase", "console_uppercase"),
      workflowEdge("edge_log_output", "console_uppercase", "output_uppercase"),
    ],
  );

  try {
    const result = await runWorkflowFromCanvas(page, workflow.id, 4, {
      text: "hello workflow",
    });

    expect(result.status).toBe("success");
    expect(singleNodeOutput(result, "logUppercase").logMessage).toBe("HELLO WORKFLOW");
    expect(outputResult(result, "uppercaseOutput")).toBe("HELLO WORKFLOW");
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("splits a sentence into a word array and prints it", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Canvas Sentence Words ${Date.now()}`,
    [
      workflowNode("input_sentence", "textInput", 80, 160, {
        label: "sentenceInput",
        value: "",
        inputFields: [{ key: "sentence" }],
      }),
      workflowNode("set_words", "set", 340, 160, {
        label: "splitSentence",
        mappings: [{ key: "words", value: '$sentenceInput.body.sentence.split(" ")' }],
      }),
      workflowNode("output_words", "output", 600, 160, {
        label: "wordsOutput",
        message: "$splitSentence.words",
      }),
    ],
    [
      workflowEdge("edge_input_words", "input_sentence", "set_words"),
      workflowEdge("edge_words_output", "set_words", "output_words"),
    ],
  );

  try {
    const result = await runWorkflowFromCanvas(page, workflow.id, 3, {
      sentence: "build clear tests",
    });

    expect(result.status).toBe("success");
    expect(outputResult(result, "wordsOutput")).toEqual(["build", "clear", "tests"]);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("increments an input number through a three-step loop and prints each set value", async ({
  page,
}) => {
  const workflow = await createWorkflow(
    page,
    `Canvas Number Loop ${Date.now()}`,
    [
      workflowNode("input_number", "textInput", 80, 200, {
        label: "numberInput",
        value: "",
        inputFields: [{ key: "number" }],
      }),
      workflowNode("variable_counter", "variable", 330, 200, {
        label: "storeNumber",
        variableName: "counterValue",
        variableValue: "$numberInput.body.number",
        variableType: "number",
        isGlobal: false,
      }),
      workflowNode("variable_screen_init", "variable", 580, 200, {
        label: "initScreenValues",
        variableName: "screenValues",
        variableValue: "$array()",
        variableType: "array",
        isGlobal: false,
      }),
      workflowNode("loop_three", "loop", 830, 200, {
        label: "threeSteps",
        arrayExpression: "$range(0, 3)",
      }),
      workflowNode("variable_increment", "variable", 830, 20, {
        label: "incrementCounter",
        variableName: "counterValue",
        variableValue: "$vars.counterValue + 1",
        variableType: "number",
        isGlobal: false,
      }),
      workflowNode("set_screen", "set", 1080, 20, {
        label: "showCounter",
        mappings: [{ key: "number", value: "$vars.counterValue" }],
      }),
      workflowNode("variable_collect", "variable", 1330, 20, {
        label: "collectScreenValues",
        variableName: "screenValues",
        variableValue: "$vars.screenValues.add($showCounter.number)",
        variableType: "array",
        isGlobal: false,
      }),
      workflowNode("output_loop", "output", 1080, 320, {
        label: "loopOutput",
        message: "$vars.screenValues",
      }),
    ],
    [
      workflowEdge("edge_input_counter", "input_number", "variable_counter"),
      workflowEdge("edge_counter_init", "variable_counter", "variable_screen_init"),
      workflowEdge("edge_init_loop", "variable_screen_init", "loop_three"),
      workflowEdge("edge_loop_increment", "loop_three", "variable_increment", {
        sourceHandle: "loop",
      }),
      workflowEdge("edge_increment_set", "variable_increment", "set_screen"),
      workflowEdge("edge_set_collect", "set_screen", "variable_collect"),
      workflowEdge("edge_collect_loop", "variable_collect", "loop_three", {
        targetHandle: "loop",
      }),
      workflowEdge("edge_loop_output", "loop_three", "output_loop", {
        sourceHandle: "done",
      }),
    ],
  );

  try {
    const result = await runWorkflowFromCanvas(page, workflow.id, 8, {
      number: "2",
    });
    const shownNumbers = nodeOutputs(result, "showCounter").map((output) => output.number);

    expect(result.status).toBe("success");
    expect(shownNumbers).toEqual([3, 4, 5]);
    expect(outputResult(result, "loopOutput")).toEqual([3, 4, 5]);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("accepts input, waits two seconds, and prints done", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Canvas Input Wait ${Date.now()}`,
    [
      workflowNode("input_delay", "textInput", 80, 160, {
        label: "delayInput",
        value: "",
        inputFields: [{ key: "seconds" }],
      }),
      workflowNode("wait_delay", "wait", 340, 160, {
        label: "pauseForInput",
        duration: 2000,
      }),
      workflowNode("output_wait", "output", 600, 160, {
        label: "waitOutput",
        message: "done",
      }),
    ],
    [
      workflowEdge("edge_input_wait", "input_delay", "wait_delay"),
      workflowEdge("edge_wait_output", "wait_delay", "output_wait"),
    ],
  );

  try {
    const result = await runWorkflowFromCanvas(page, workflow.id, 3, {
      seconds: "2",
    });

    expect(result.status).toBe("success");
    expect(singleNodeOutput(result, "delayInput").seconds).toBe("2");
    expect(result.execution_time_ms).toBeGreaterThanOrEqual(1_900);
    expect(outputResult(result, "waitOutput")).toBe("done");
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("captures a failed HTTP response as node output", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Canvas HTTP Error ${Date.now()}`,
    [
      workflowNode("http_error", "http", 120, 160, {
        label: "fetchBrokenApi",
        curl: `curl -X GET ${e2eBackendUrl}/api/e2e-http-error`,
      }),
      workflowNode("output_status", "output", 380, 160, {
        label: "httpStatusOutput",
        message: "$fetchBrokenApi.status",
      }),
    ],
    [workflowEdge("edge_http_output", "http_error", "output_status")],
  );

  try {
    const result = await runWorkflowFromCanvas(page, workflow.id, 2);
    const httpNode = result.node_results.find((row) => row.node_label === "fetchBrokenApi");

    expect(result.status).toBe("success");
    expect(httpNode?.status).toBe("success");
    expect(Number(httpNode?.output.status)).toBeGreaterThanOrEqual(400);
    expect(outputResult(result, "httpStatusOutput")).toBe(httpNode?.output.status);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

const ONE_PX_PNG_BASE64 =
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==";

test("saves a 1px base64 image from canvas input to drive", async ({ page }) => {
  const filename = `e2e-1px-${Date.now()}.png`;

  const workflow = await createWorkflow(
    page,
    `Canvas Drive Save ${Date.now()}`,
    [
      workflowNode("input_file", "textInput", 80, 160, {
        label: "userInput",
        value: "",
        inputFields: [{ key: "filename" }, { key: "base64" }],
      }),
      workflowNode("drive_save", "drive", 340, 160, {
        label: "saveFile",
        driveOperation: "save",
        driveFilename: "$userInput.body.filename",
        driveBase64Content: "$userInput.body.base64",
      }),
      workflowNode("output_save", "output", 600, 160, {
        label: "saveOutput",
        message: "$saveFile.download_url",
      }),
    ],
    [
      workflowEdge("edge_input_save", "input_file", "drive_save"),
      workflowEdge("edge_save_output", "drive_save", "output_save"),
    ],
  );

  try {
    const result = await runWorkflowFromCanvas(page, workflow.id, 3, {
      filename,
      base64: ONE_PX_PNG_BASE64,
    });

    const saveOutput = singleNodeOutput(result, "saveFile");

    expect(result.status).toBe("success");
    expect(saveOutput.operation).toBe("save");
    expect(saveOutput.filename).toBe(filename);
    expect(saveOutput.mime_type).toBe("image/png");
    expect(saveOutput.size_bytes).toBeGreaterThan(0);
    expect(typeof saveOutput.id).toBe("string");
    expect(typeof saveOutput.download_url).toBe("string");

    const filesResponse = await page.request.get("/api/files");
    expect(filesResponse.ok()).toBeTruthy();
    const filesPayload = (await filesResponse.json()) as {
      files: { id: string; filename: string }[];
    };
    const saved = filesPayload.files.find((file) => file.id === saveOutput.id);
    expect(saved?.filename).toBe(filename);
    expect(outputResult(result, "saveOutput")).toBe(saveOutput.download_url);
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
