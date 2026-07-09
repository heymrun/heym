import { expect, test } from "@playwright/test";

import { createWorkflow, deleteWorkflow, prepareAuthenticatedPage } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareAuthenticatedPage(page);
});

test("shows Jira node operation-specific fields", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Jira Node Properties ${Date.now()}`,
    [
      {
        id: "jira-node",
        type: "jira",
        position: { x: 120, y: 160 },
        data: {
          label: "jira",
          credentialId: "",
          jiraOperation: "createIssue",
          jiraProjectKey: "",
          jiraIssueType: "Task",
          jiraSummary: "",
          jiraDescription: "$input.text",
        },
      },
    ],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="jira-node"]').click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("jira-credential-field")).toBeVisible();
    await expect(panel.getByTestId("jira-operation-field")).toBeVisible();
    await expect(panel.getByTestId("jira-project-key-field")).toBeVisible();
    await expect(panel.getByTestId("jira-issue-type-field")).toBeVisible();
    await expect(panel.getByTestId("jira-summary-field")).toBeVisible();
    await expect(panel.getByTestId("jira-description-field")).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("shows Jira notify operation fields", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Jira Notify Properties ${Date.now()}`,
    [
      {
        id: "jira-node",
        type: "jira",
        position: { x: 120, y: 160 },
        data: {
          label: "jira",
          credentialId: "",
          jiraOperation: "notifyIssue",
          jiraIssueKey: "ENG-1",
          jiraNotifySubject: "Issue update",
          jiraNotifyTextBody: "$input.text",
          jiraNotifyTo: "{\"assignee\":true}",
        },
      },
    ],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="jira-node"]').click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("jira-issue-key-field")).toBeVisible();
    await expect(panel.getByTestId("jira-notify-subject-field")).toBeVisible();
    await expect(panel.getByTestId("jira-notify-text-body-field")).toBeVisible();
    await expect(panel.getByTestId("jira-notify-to-field")).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("shows Jira attachment operation fields", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Jira Attachment Properties ${Date.now()}`,
    [
      {
        id: "jira-node",
        type: "jira",
        position: { x: 120, y: 160 },
        data: {
          label: "jira",
          credentialId: "",
          jiraOperation: "addAttachment",
          jiraIssueKey: "ENG-1",
          jiraAttachmentFilename: "report.txt",
          jiraAttachmentBase64: "aGVsbG8=",
        },
      },
    ],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="jira-node"]').click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("jira-issue-key-field")).toBeVisible();
    await expect(panel.getByTestId("jira-attachment-filename-field")).toBeVisible();
    await expect(panel.getByTestId("jira-attachment-base64-field")).toBeVisible();
    await expect(panel.getByTestId("jira-attachment-mime-type-field")).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("shows Jira search operation fields", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Jira Search Properties ${Date.now()}`,
    [
      {
        id: "jira-node",
        type: "jira",
        position: { x: 120, y: 160 },
        data: {
          label: "jira",
          credentialId: "",
          jiraOperation: "searchIssues",
          jiraJql: "project = ENG AND updated >= -30d ORDER BY updated DESC",
          jiraFields: "[\"key\",\"summary\"]",
          jiraLimit: "25",
          jiraNextPageToken: "",
        },
      },
    ],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="jira-node"]').click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("jira-jql-field")).toBeVisible();
    await expect(panel.getByTestId("jira-fields-field")).toBeVisible();
    await expect(panel.getByText("Limit", { exact: true })).toBeVisible();
    await expect(panel.getByText("Next Page Token", { exact: true })).toBeVisible();
    await expect(panel.getByText("Start At", { exact: true })).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("shows Jira list attachments operation fields", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Jira List Attachments Properties ${Date.now()}`,
    [
      {
        id: "jira-node",
        type: "jira",
        position: { x: 120, y: 160 },
        data: {
          label: "jira",
          credentialId: "",
          jiraOperation: "listAttachments",
          jiraIssueKey: "ENG-1",
          jiraLimit: "25",
          jiraStartAt: "0",
          jiraIncludeBinary: true,
        },
      },
    ],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="jira-node"]').click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("jira-issue-key-field")).toBeVisible();
    await expect(panel.getByText("Limit", { exact: true })).toBeVisible();
    await expect(panel.getByText("Start At", { exact: true })).toBeVisible();
    await expect(panel.getByText("Include binary content as base64")).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});

test("shows Jira create user identity fields", async ({ page }) => {
  const workflow = await createWorkflow(
    page,
    `Jira Create User Properties ${Date.now()}`,
    [
      {
        id: "jira-node",
        type: "jira",
        position: { x: 120, y: 160 },
        data: {
          label: "jira",
          credentialId: "",
          jiraOperation: "createUser",
          jiraUserEmail: "ada@example.com",
          jiraUsername: "ada",
          jiraUserDisplayName: "Ada Lovelace",
        },
      },
    ],
  );

  try {
    await page.goto(`/workflows/${workflow.id}`);
    await expect(page.locator(".vue-flow__node")).toHaveCount(1);
    await page.getByRole("button", { name: "Properties", exact: true }).click();
    await page.locator('.vue-flow__node[data-id="jira-node"]').click();

    const panel = page.locator(".properties-panel");
    await expect(panel.getByTestId("jira-user-email-field")).toBeVisible();
    await expect(panel.getByTestId("jira-username-field")).toBeVisible();
    await expect(panel.getByTestId("jira-user-display-name-field")).toBeVisible();
  } finally {
    await deleteWorkflow(page, workflow.id);
  }
});
