import { expect, test } from "@playwright/test";

import { deleteWorkflow, prepareAuthenticatedPage } from "./support";

interface ToolNodeCase {
  id: string;
  expectedToggles: number;
}

const toolNodeCases: ToolNodeCase[] = [
  {
    id: "node_1782319471465_xcu6o8kqh",
    expectedToggles: 3,
  },
  {
    id: "node_1782319434457_h6y12qg8q",
    expectedToggles: 2,
  },
  {
    id: "node_1782319488123_linear01",
    expectedToggles: 4,
  },
  {
    id: "node_1782319499999_sentry1",
    expectedToggles: 4,
  },
  {
    id: "node_1782319357334_hlkt3kgd3",
    expectedToggles: 6,
  },
  {
    id: "node_1782319423257_frrvfmc3q",
    expectedToggles: 5,
  },
  {
    id: "node_1782319457181_rqtkfzboq",
    expectedToggles: 4,
  },
];

function integrationToolDsl(): Record<string, unknown> {
  return {
    heym: true,
    nodes: [
      {
        id: "node_1782319352067_262pue5rk",
        type: "agent",
        position: { x: 350, y: 200 },
        data: {
          label: "agent",
          model: "",
          temperature: 0.7,
          systemInstruction: "",
          userMessage: "$input.text",
          tools: [],
          mcpConnections: [],
          skills: [],
          toolTimeoutSeconds: 30,
          requestTimeoutSeconds: 60,
          maxToolIterations: 30,
          imageInputEnabled: false,
          imageInput: "",
          isOrchestrator: false,
          subAgentLabels: [],
          subWorkflowIds: [],
          hitlEnabled: false,
          hitlSummary: "",
          jsonOutputEnabled: false,
          jsonOutputSchema: "",
          guardrailsEnabled: false,
          guardrailsCategories: [],
          guardrailsSeverity: "medium",
          fallbackCredentialId: "",
          fallbackModel: "",
          persistentMemoryEnabled: false,
        },
      },
      {
        id: "node_1782319357334_hlkt3kgd3",
        type: "supabase",
        position: { x: -255, y: 60 },
        data: {
          label: "supabase",
          credentialId: "",
          supabaseOperation: "select",
          supabaseSchema: "public",
          supabaseTable: "",
          supabaseSelectColumns: "*",
          supabaseFilter: "{}",
          supabaseLimit: "100",
          supabaseOrderBy: "",
          supabaseAscending: true,
          supabaseRowsInputMode: "raw",
          supabaseDataInputMode: "raw",
          supabaseIgnoredInputFields: "",
          supabaseRows: "[]",
          supabaseOnConflict: "",
          supabaseData: "{}",
        },
      },
      {
        id: "node_1782319423257_frrvfmc3q",
        type: "notion",
        position: { x: 45, y: 60 },
        data: {
          label: "notion",
          credentialId: "",
          notionOperation: "search",
          notionQuery: "",
          notionPageId: "",
          notionDatabaseId: "",
          notionDatabase: "{}",
          notionDataSourceId: "",
          notionDataSource: "{}",
          notionDataSourceInputMode: "select",
          notionParentPageId: "",
          notionBlockId: "",
          notionBlock: "{}",
          notionProperties: "{}",
          notionChildren: "[]",
          notionFilter: "{}",
          notionSort: "{}",
          notionSorts: "[]",
          notionIcon: "{}",
          notionCover: "{}",
          notionPageSize: "100",
          notionStartCursor: "",
          notionAppendPosition: "end",
          notionAfterBlockId: "",
        },
      },
      {
        id: "node_1782319434457_h6y12qg8q",
        type: "github",
        position: { x: 345, y: 60 },
        data: {
          label: "github",
          credentialId: "",
          githubOperation: "getRepository",
          githubOwner: "",
          githubRepo: "",
          githubOrganization: "",
          githubInviteEmail: "",
          githubIssueNumber: "",
          githubCommentBody: "$agent.text",
          githubAssignee: "",
          githubCreator: "",
          githubMentioned: "",
          githubLabelsFilter: "",
          githubSince: "",
          githubSort: "",
          githubDirection: "",
          githubLockReason: "",
          githubHead: "",
          githubBase: "main",
          githubPullRequestNumber: "",
          githubReviewId: "",
          githubReviewEvent: "APPROVE",
          githubReviewBody: "",
          githubCommitId: "",
          githubFilePath: "",
          githubFileContent: "$agent.text",
          githubCommitMessage: "",
          githubBranch: "",
          githubPerPage: "30",
          githubTagName: "",
          githubReleaseId: "",
          githubWorkflowId: "",
          githubWaitTimeoutSeconds: "600",
          githubPollIntervalSeconds: "5",
        },
      },
      {
        id: "node_1782319488123_linear01",
        type: "linear",
        position: { x: 495, y: 60 },
        data: {
          label: "linear",
          credentialId: "",
          linearOperation: "listIssues",
          linearTeamId: "",
          linearProjectId: "",
          linearIssueId: "",
          linearTitle: "",
          linearDescription: "",
          linearStateId: "",
          linearAssigneeId: "",
          linearPriority: "",
          linearIssueLinkUrl: "",
          linearCommentId: "",
          linearCommentBody: "",
          linearParentCommentId: "",
          linearLimit: "50",
          linearAfter: "",
          linearReturnAll: false,
        },
      },
      {
        id: "node_1782319457181_rqtkfzboq",
        type: "s3",
        position: { x: 795, y: 60 },
        data: {
          label: "amazonS3",
          credentialId: "",
          s3Operation: "putObject",
          s3Bucket: "",
          s3Key: "$input.filename || 'output.txt'",
          s3SourceBucket: "",
          s3SourceKey: "",
          s3Prefix: "",
          s3ContinuationToken: "",
          s3Body: "$input.text",
          s3ContentType: "text/plain",
          s3MaxKeys: "100",
          s3IncludeBinary: false,
        },
      },
      {
        id: "node_1782319499999_sentry1",
        type: "sentry",
        position: { x: 945, y: 60 },
        data: {
          label: "sentry",
          credentialId: "",
          sentryOperation: "updateIssue",
          sentryOrganizationSlug: "",
          sentryProjectSlug: "",
          sentryTeamSlug: "",
          sentryIssueId: "",
          sentryEventId: "",
          sentryReleaseVersion: "",
          sentryName: "",
          sentrySlug: "",
          sentryPlatform: "",
          sentryStatus: "",
          sentryAssignedTo: "",
          sentryQuery: "",
          sentryStatsPeriod: "14d",
          sentryLimit: "25",
          sentryReleaseProjects: "[]",
          sentryReleaseRefs: "[]",
          sentryPayload: "{}",
          agentProvidedFields: [],
        },
      },
      {
        id: "node_1782319471465_xcu6o8kqh",
        type: "discord",
        position: { x: 1095, y: 60 },
        data: {
          label: "discord",
          credentialId: "",
          message: "$agent.text",
          username: "",
          avatarUrl: "",
          agentProvidedFields: [],
        },
      },
    ],
    edges: toolNodeCases.map((node) => ({
      id: `edge_${node.id}_node_1782319352067_262pue5rk`,
      source: node.id,
      target: "node_1782319352067_262pue5rk",
      sourceHandle: "tool-output",
      targetHandle: "tool-input",
    })),
  };
}

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("exposes integration inputs to an agent tool", async ({ page }) => {
  const fileName = `agent-integration-tools-${Date.now()}.json`;
  const dsl = integrationToolDsl();
  await page.goto("/");
  const dataTransfer = await page.evaluateHandle((payload) => {
    const transfer = new DataTransfer();
    transfer.items.add(
      new File([JSON.stringify(payload.dsl)], payload.fileName, { type: "application/json" }),
    );
    return transfer;
  }, { dsl, fileName });
  await page.getByTestId("workflow-import-dropzone").dispatchEvent("drop", { dataTransfer });
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]+$/);

  try {
    await expect(page.locator(".vue-flow__node")).toHaveCount(8);
    const propertiesPanel = page.locator(".properties-panel");
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await expect(propertiesPanel).toBeVisible();

    for (const nodeCase of toolNodeCases) {
      await page.locator(`.vue-flow__node[data-id="${nodeCase.id}"]`).click();
      const enableButtons = propertiesPanel.getByTitle(
        "Click to let agent fill this at runtime",
      );
      await expect(enableButtons).toHaveCount(nodeCase.expectedToggles);
      await enableButtons.first().click();
      await expect(
        propertiesPanel.getByTitle("Agent fills this — click to use fixed value"),
      ).toHaveCount(1);
    }
  } finally {
    const workflowId = page.url().split("/").pop();
    if (workflowId) {
      await deleteWorkflow(page, workflowId);
    }
  }
});
