export type LinearExpressionFieldKey =
  | "linearLimit"
  | "linearAfter"
  | "linearTeamId"
  | "linearProjectId"
  | "linearIssueId"
  | "linearTitle"
  | "linearDescription"
  | "linearStateId"
  | "linearIssueLinkUrl"
  | "linearAssigneeId"
  | "linearPriority"
  | "linearCommentId"
  | "linearCommentBody"
  | "linearParentCommentId";

export interface LinearExpressionField {
  key: LinearExpressionFieldKey;
  label: string;
}

export interface LinearExpressionFieldContext {
  returnAll?: boolean;
}

const listOperations = new Set([
  "listTeams",
  "listProjects",
  "listIssues",
  "listTeamMembers",
  "listComments",
]);

function appendPaginationFields(
  fields: LinearExpressionField[],
  context: LinearExpressionFieldContext,
): void {
  if (!context.returnAll) {
    fields.push({ key: "linearLimit", label: "Limit" });
    fields.push({ key: "linearAfter", label: "After Cursor" });
  }
}

/** Returns ordered expression-evaluate dialog slots for the given Linear operation. */
export function getLinearExpressionFields(
  operation: string,
  context: LinearExpressionFieldContext = {},
): LinearExpressionField[] {
  const op = operation || "listIssues";
  const fields: LinearExpressionField[] = [];

  if (listOperations.has(op)) {
    appendPaginationFields(fields, context);
  }

  if (
    op === "listIssues" ||
    op === "createIssue" ||
    op === "updateIssue" ||
    op === "listWorkflowStates" ||
    op === "listTeamMembers"
  ) {
    fields.push({ key: "linearTeamId", label: "Team ID" });
  }

  if (op === "listIssues" || op === "createIssue" || op === "updateIssue") {
    fields.push({ key: "linearProjectId", label: "Project ID" });
  }

  if (
    op === "getIssue" ||
    op === "updateIssue" ||
    op === "deleteIssue" ||
    op === "addIssueLink" ||
    op === "createComment" ||
    op === "listComments"
  ) {
    fields.push({ key: "linearIssueId", label: "Issue ID or Identifier" });
  }

  if (
    op === "updateComment" ||
    op === "deleteComment" ||
    op === "resolveComment" ||
    op === "unresolveComment"
  ) {
    fields.push({ key: "linearCommentId", label: "Comment ID" });
  }

  if (op === "createIssue" || op === "updateIssue") {
    fields.push({ key: "linearTitle", label: "Title" });
    fields.push({ key: "linearDescription", label: "Description" });
    fields.push({ key: "linearStateId", label: "State ID" });
  }

  if (op === "addIssueLink") {
    fields.push({ key: "linearIssueLinkUrl", label: "Link URL" });
  }

  if (op === "createIssue" || op === "updateIssue") {
    fields.push({ key: "linearAssigneeId", label: "Assignee ID" });
    fields.push({ key: "linearPriority", label: "Priority" });
  }

  if (op === "createComment" || op === "updateComment") {
    fields.push({ key: "linearCommentBody", label: "Comment Body" });
  }

  if (op === "createComment") {
    fields.push({ key: "linearParentCommentId", label: "Parent Comment ID" });
  }

  return fields;
}
