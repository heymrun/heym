export type GitHubExpressionFieldKey =
  | "githubOwner"
  | "githubRepo"
  | "githubOrganization"
  | "githubInviteEmail"
  | "githubIssueNumber"
  | "githubAssignee"
  | "githubCreator"
  | "githubMentioned"
  | "githubLabelsFilter"
  | "githubSince"
  | "githubTitle"
  | "githubBody"
  | "githubCommentBody"
  | "githubLabels"
  | "githubAssignees"
  | "githubHead"
  | "githubBase"
  | "githubPullRequestNumber"
  | "githubReviewId"
  | "githubReviewBody"
  | "githubCommitId"
  | "githubReleaseId"
  | "githubTagName"
  | "githubBranch"
  | "githubWorkflowId"
  | "githubWorkflowInputs"
  | "githubFilePath"
  | "githubCommitMessage"
  | "githubFileContent";

export interface GitHubExpressionField {
  key: GitHubExpressionFieldKey;
  label: string;
}

const githubRepoOptionalOperations = new Set([
  "listOrganizationRepositories",
  "listUserRepositories",
  "getUserRepositories",
  "getUserIssues",
  "inviteUser",
]);

const githubOwnerOptionalOperations = new Set(["getUserIssues", "inviteUser"]);

function isGitHubRepoRequired(operation: string): boolean {
  return !githubRepoOptionalOperations.has(operation);
}

function isGitHubOwnerRequired(operation: string): boolean {
  return !githubOwnerOptionalOperations.has(operation);
}

function ownerLabel(operation: string): string {
  return operation === "listOrganizationRepositories" ? "Organization" : "Owner";
}

function appendOwner(fields: GitHubExpressionField[], operation: string): void {
  if (isGitHubOwnerRequired(operation)) {
    fields.push({ key: "githubOwner", label: ownerLabel(operation) });
  }
}

function appendRepo(fields: GitHubExpressionField[], operation: string): void {
  if (isGitHubRepoRequired(operation)) {
    fields.push({ key: "githubRepo", label: "Repository" });
  }
}

function appendIssueListFilters(
  fields: GitHubExpressionField[],
  operation: string,
): void {
  if (operation !== "getUserIssues") {
    fields.push({ key: "githubAssignee", label: "Assignee" });
    fields.push({ key: "githubCreator", label: "Creator" });
  }
  fields.push({
    key: "githubMentioned",
    label: operation === "getUserIssues" ? "Mentioned Filter" : "Mentioned User",
  });
  fields.push({ key: "githubLabelsFilter", label: "Labels" });
  fields.push({ key: "githubSince", label: "Updated Since" });
}

/** Returns ordered expression-evaluate dialog slots for the given GitHub operation. */
export function getGitHubExpressionFields(operation: string): GitHubExpressionField[] {
  const op = operation || "getRepository";
  const fields: GitHubExpressionField[] = [];

  if (op === "inviteUser") {
    fields.push({ key: "githubOrganization", label: "Organization" });
    fields.push({ key: "githubInviteEmail", label: "Email" });
    return fields;
  }

  if (op === "getUserIssues") {
    appendIssueListFilters(fields, op);
    return fields;
  }

  appendOwner(fields, op);
  appendRepo(fields, op);

  if (op === "listIssues" || op === "getRepositoryIssues") {
    appendIssueListFilters(fields, op);
    return fields;
  }

  if (op === "listPullRequests" || op === "getRepositoryPullRequests" || op === "listReleases" || op === "listWorkflows") {
    return fields;
  }

  if (op === "getIssue" || op === "lockIssue") {
    fields.push({ key: "githubIssueNumber", label: "Issue Number" });
    return fields;
  }

  if (op === "createComment") {
    fields.push({ key: "githubIssueNumber", label: "Issue Number" });
    fields.push({ key: "githubCommentBody", label: "Comment Body" });
    return fields;
  }

  if (op === "createIssue") {
    fields.push({ key: "githubTitle", label: "Title" });
    fields.push({ key: "githubBody", label: "Body" });
    fields.push({ key: "githubLabels", label: "Labels (JSON Array)" });
    fields.push({ key: "githubAssignees", label: "Assignees (JSON Array)" });
    return fields;
  }

  if (op === "updateIssue") {
    fields.push({ key: "githubIssueNumber", label: "Issue Number" });
    fields.push({ key: "githubTitle", label: "Title" });
    fields.push({ key: "githubBody", label: "Body" });
    fields.push({ key: "githubLabels", label: "Labels (JSON Array)" });
    fields.push({ key: "githubAssignees", label: "Assignees (JSON Array)" });
    return fields;
  }

  if (op === "createPullRequest") {
    fields.push({ key: "githubTitle", label: "Title" });
    fields.push({ key: "githubBody", label: "Body" });
    fields.push({ key: "githubHead", label: "Head Branch" });
    fields.push({ key: "githubBase", label: "Base Branch" });
    return fields;
  }

  if (op === "createReview") {
    fields.push({ key: "githubPullRequestNumber", label: "Pull Request Number" });
    fields.push({ key: "githubReviewBody", label: "Review Body" });
    fields.push({ key: "githubCommitId", label: "Commit ID" });
    return fields;
  }

  if (op === "getReview") {
    fields.push({ key: "githubPullRequestNumber", label: "Pull Request Number" });
    fields.push({ key: "githubReviewId", label: "Review ID" });
    return fields;
  }

  if (op === "listReviews") {
    fields.push({ key: "githubPullRequestNumber", label: "Pull Request Number" });
    return fields;
  }

  if (op === "updateReview") {
    fields.push({ key: "githubPullRequestNumber", label: "Pull Request Number" });
    fields.push({ key: "githubReviewId", label: "Review ID" });
    fields.push({ key: "githubReviewBody", label: "Review Body" });
    return fields;
  }

  if (op === "createRelease") {
    fields.push({ key: "githubTitle", label: "Name / Title" });
    fields.push({ key: "githubBody", label: "Body" });
    fields.push({ key: "githubTagName", label: "Tag Name" });
    fields.push({ key: "githubBranch", label: "Target Commitish / Branch" });
    return fields;
  }

  if (op === "updateRelease") {
    fields.push({ key: "githubReleaseId", label: "Release ID" });
    fields.push({ key: "githubTitle", label: "Name / Title" });
    fields.push({ key: "githubBody", label: "Body" });
    fields.push({ key: "githubTagName", label: "Tag Name" });
    fields.push({ key: "githubBranch", label: "Target Commitish / Branch" });
    return fields;
  }

  if (op === "getRelease" || op === "deleteRelease") {
    fields.push({ key: "githubReleaseId", label: "Release ID" });
    return fields;
  }

  if (
    op === "getWorkflow"
    || op === "enableWorkflow"
    || op === "disableWorkflow"
    || op === "getWorkflowUsage"
  ) {
    fields.push({ key: "githubWorkflowId", label: "Workflow ID or File Name" });
    return fields;
  }

  if (op === "dispatchWorkflow" || op === "dispatchWorkflowAndWait") {
    fields.push({ key: "githubWorkflowId", label: "Workflow ID or File Name" });
    fields.push({ key: "githubBranch", label: "Ref or Branch" });
    fields.push({ key: "githubWorkflowInputs", label: "Workflow Inputs (JSON Object)" });
    return fields;
  }

  if (op === "getFile" || op === "listFiles") {
    fields.push({
      key: "githubFilePath",
      label: op === "listFiles" ? "Directory Path" : "File Path",
    });
    fields.push({ key: "githubBranch", label: "Ref or Branch" });
    return fields;
  }

  if (op === "upsertFile") {
    fields.push({ key: "githubFilePath", label: "File Path" });
    fields.push({ key: "githubBranch", label: "Target Branch" });
    fields.push({ key: "githubCommitMessage", label: "Commit Message" });
    fields.push({ key: "githubFileContent", label: "File Content" });
    return fields;
  }

  if (op === "deleteFile") {
    fields.push({ key: "githubFilePath", label: "File Path" });
    fields.push({ key: "githubBranch", label: "Target Branch" });
    fields.push({ key: "githubCommitMessage", label: "Commit Message" });
    return fields;
  }

  return fields;
}
