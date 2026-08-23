import { expect, test, type Page } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

/**
 * Smoke test for the expression operator surface, driven from the canvas.
 *
 * One `set` node builds a fixture and a second `set` node applies every operator family to
 * it. The workflow runs from the canvas, then every expression is replayed through
 * `/api/expressions/evaluate` so the evaluate dialog and the run can never drift apart.
 *
 * Adding an operator: add a row to `OPERATOR_CASES` below. The exhaustive per-method matrix
 * lives in `backend/tests/test_expression_operator_smoke.py`, whose coverage guard fails
 * when a Dot wrapper method or a registered function has no case at all.
 */

interface WorkflowNodeFixture {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
}

interface NodeResultEvent {
  node_label: string;
  status: string;
  output: Record<string, unknown>;
}

interface ExecutionCompleteEvent {
  status: string;
  node_results: NodeResultEvent[];
}

interface OperatorCase {
  key: string;
  expression: string;
  expected: unknown;
}

const FIXED_DATE = "2026-03-05T14:30:00";
const GLOBAL_LINK = "https://x.com/heym/status/1";

const SAMPLE_MAPPINGS = [
  { key: "text", value: "  Heym Workflow  " },
  { key: "url", value: "https://heym.run/docs?q=a b" },
  { key: "jsonText", value: '{"name": "ada", "age": 36}' },
  { key: "num", value: "$int(7)" },
  { key: "words", value: "$array('beta', 'alpha', 'beta')" },
  { key: "people", value: "$array(dict(name='ada', age=36), dict(name='bob', age=24))" },
  { key: "profile", value: "$dict(name='ada', age=36)" },
];

const OPERATOR_CASES: OperatorCase[] = [
  // Strings
  { key: "strTrim", expression: "$sample.text.trim()", expected: "Heym Workflow" },
  { key: "strUpper", expression: "$sample.text.trim().upper()", expected: "HEYM WORKFLOW" },
  { key: "strLength", expression: "$sample.text.length", expected: 17 },
  { key: "strSubstring", expression: "$sample.text.trim().substring(0, 4)", expected: "Heym" },
  { key: "strSubstr", expression: "$sample.text.trim().substr(5, 8)", expected: "Workflow" },
  {
    key: "strHash",
    expression: "$sample.text.trim().hash()",
    expected: "443fea6b2674a9890691e7016fe153f7",
  },
  {
    key: "strReplaceAll",
    expression: "$sample.text.trim().replaceAll(' ', '-')",
    expected: "Heym-Workflow",
  },
  { key: "strSplit", expression: "$sample.text.trim().split(' ')", expected: ["Heym", "Workflow"] },
  { key: "strIndexOf", expression: "$sample.text.trim().indexOf('Work')", expected: 5 },
  {
    key: "strBase64",
    expression: "$sample.text.trim().base64Encode().base64Decode()",
    expected: "Heym Workflow",
  },
  {
    key: "strUrl",
    expression: "$sample.url.urlEncode().urlDecode()",
    expected: "https://heym.run/docs?q=a b",
  },
  { key: "strToJson", expression: "$sample.jsonText.toJson().name", expected: "ada" },
  { key: "strOrEmpty", expression: "$sample.missing.orEmpty()", expected: "" },
  // Numbers and booleans
  { key: "numToString", expression: "$sample.num.toString()", expected: "7" },
  { key: "numArithmetic", expression: "$sample.num + 3", expected: 10 },
  { key: "numComparison", expression: "$sample.num >= 7", expected: true },
  { key: "numTernary", expression: "$sample.num > 5 ? 'big' : 'small'", expected: "big" },
  // Lists
  { key: "listLength", expression: "$sample.words.length", expected: 3 },
  { key: "listDistinct", expression: "$sample.words.distinct()", expected: ["beta", "alpha"] },
  { key: "listSort", expression: "$sample.words.sort()", expected: ["alpha", "beta", "beta"] },
  { key: "listJoin", expression: "$sample.words.join('|')", expected: "beta|alpha|beta" },
  { key: "listMap", expression: "$sample.people.map('item.name')", expected: ["ada", "bob"] },
  {
    key: "listFilter",
    expression: "$sample.people.filter('item.age > 30')",
    expected: [{ name: "ada", age: 36 }],
  },
  { key: "listSum", expression: "$sum($sample.people.map('item.age'))", expected: 60 },
  // Objects
  { key: "dictKeys", expression: "$sample.profile.keys()", expected: ["name", "age"] },
  { key: "dictGet", expression: "$sample.profile.get('name')", expected: "ada" },
  { key: "dictMap", expression: "$sample.profile.map('item.key')", expected: ["name", "age"] },
  // Dates
  { key: "dateYear", expression: `$Date('${FIXED_DATE}').year`, expected: 2026 },
  { key: "dateToDate", expression: `$Date('${FIXED_DATE}').toDate()`, expected: "2026-03-05" },
  {
    key: "dateFormat",
    expression: `$Date('${FIXED_DATE}').format('DD MMM YYYY HH:mm')`,
    expected: "05 Mar 2026 14:30",
  },
  {
    key: "dateAddDays",
    expression: `$Date('${FIXED_DATE}').addDays(2).toDate()`,
    expected: "2026-03-07",
  },
  // Functions
  { key: "fnConcat", expression: "$concat('a', 'b')", expected: "ab" },
  { key: "fnRange", expression: "$range(1, 4)", expected: [1, 2, 3] },
  { key: "fnUpper", expression: "$upper($sample.text.trim())", expected: "HEYM WORKFLOW" },
];

/**
 * `global` is a Python keyword, so `$global.x.substring(0, 5)` once failed to parse and fell
 * through to a fallback resolver that answered null for most operators. These cases keep the
 * global scope on the same footing as every other context root.
 */
function globalScopeCases(variableName: string): OperatorCase[] {
  return [
    {
      key: "globalPlain",
      expression: `$global.${variableName}`,
      expected: GLOBAL_LINK,
    },
    {
      key: "globalHash",
      expression: `$global.${variableName}.hash()`,
      expected: "c55350fa8bf2d285b1b41002dc1e222d",
    },
    {
      key: "globalSubstring",
      expression: `$global.${variableName}.substring(0, 5)`,
      expected: "https",
    },
    {
      key: "globalSubstr",
      expression: `$global.${variableName}.substr(8, 5)`,
      expected: "x.com",
    },
    {
      key: "globalSplit",
      expression: `$global.${variableName}.split('/').length`,
      expected: 6,
    },
    {
      key: "globalUpper",
      expression: `$global.${variableName}.upper()`,
      expected: GLOBAL_LINK.toUpperCase(),
    },
    {
      key: "globalContains",
      expression: `$global.${variableName}.contains('x.com')`,
      expected: true,
    },
  ];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function workflowNode(
  id: string,
  x: number,
  data: Record<string, unknown>,
): WorkflowNodeFixture {
  return { id, type: "set", position: { x, y: 180 }, data };
}

function parseExecutionComplete(sseBody: string): ExecutionCompleteEvent {
  for (const message of sseBody.split("\n\n")) {
    for (const line of message.split("\n").filter((row) => row.startsWith("data: "))) {
      const parsed = JSON.parse(line.slice("data: ".length)) as unknown;
      if (!isRecord(parsed) || parsed.type !== "execution_complete") continue;
      return {
        status: typeof parsed.status === "string" ? parsed.status : "",
        node_results: Array.isArray(parsed.node_results)
          ? parsed.node_results.map((row) => {
            const record = isRecord(row) ? row : {};
            return {
              node_label: typeof record.node_label === "string" ? record.node_label : "",
              status: typeof record.status === "string" ? record.status : "",
              output: isRecord(record.output) ? record.output : {},
            };
          })
          : [],
      };
    }
  }
  throw new Error(`Execution completion event not found in SSE body:\n${sseBody}`);
}

async function createGlobalVariable(page: Page, name: string, value: string): Promise<string> {
  const response = await page.request.post("/api/global-variables", {
    data: { name, value, value_type: "string" },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return ((await response.json()) as { id: string }).id;
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("resolves every expression operator family in a set node and in the evaluate dialog", async ({
  page,
}) => {
  const variableName = `e2eExprLink${Date.now()}`;
  const variableId = await createGlobalVariable(page, variableName, GLOBAL_LINK);
  const cases = [...OPERATOR_CASES, ...globalScopeCases(variableName)];

  const workflow = await createWorkflow(
    page,
    `Expression Operators ${Date.now()}`,
    [
      workflowNode("sample_node", 80, { label: "sample", mappings: SAMPLE_MAPPINGS }),
      workflowNode("ops_node", 420, {
        label: "operators",
        mappings: cases.map(({ key, expression }) => ({ key, value: expression })),
      }),
    ],
    [{ id: "edge_1", source: "sample_node", target: "ops_node" }],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(2);

    const completionPromise = page.waitForResponse(
      (candidate) =>
        candidate.request().method() === "POST" &&
        new URL(candidate.url()).pathname === `/api/workflows/${workflow.id}/execute/stream`,
      { timeout: 60_000 },
    );
    await page.getByRole("button", { name: "Run Workflow" }).click();
    const response = await completionPromise;
    const body = await response.text();
    expect(response.ok(), body).toBeTruthy();

    const completion = parseExecutionComplete(body);
    expect(completion.status).toBe("success");

    const sampleOutput = completion.node_results.find((row) => row.node_label === "sample")?.output;
    const operatorsOutput = completion.node_results.find(
      (row) => row.node_label === "operators",
    );
    expect(operatorsOutput?.status, JSON.stringify(completion.node_results)).toBe("success");

    const runValues = operatorsOutput?.output ?? {};
    for (const { key, expression, expected } of cases) {
      expect(runValues[key], `run: ${expression}`).toEqual(expected);
    }

    // The evaluate dialog must answer exactly what the run produced.
    for (const { expression, expected } of cases) {
      const preview = await page.request.post("/api/expressions/evaluate", {
        data: {
          workflow_id: workflow.id,
          current_node_id: "ops_node",
          expression,
          node_results: [
            { node_id: "sample_node", label: "sample", output: sampleOutput ?? {} },
          ],
        },
      });
      expect(preview.ok(), await preview.text()).toBeTruthy();
      const previewBody = (await preview.json()) as { result: unknown; error: string | null };
      expect(previewBody.error, `preview: ${expression}`).toBeNull();
      expect(previewBody.result, `preview: ${expression}`).toEqual(expected);
    }
  } finally {
    await deleteWorkflow(page, workflow.id);
    await page.request.delete(`/api/global-variables/${variableId}`);
  }
});
