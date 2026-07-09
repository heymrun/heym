import {
  jiraAccountIdOperations,
  jiraAttachmentIdOperations,
  jiraCommentIdOperations,
  jiraIssueKeyOperations,
  jiraPaginatedOperations,
  jiraStartAtPaginatedOperations,
} from "@/components/Panels/propertiesPanel/operationOptions";

export type JiraExpressionFieldKey =
  | "jiraLimit"
  | "jiraStartAt"
  | "jiraNextPageToken"
  | "jiraFields"
  | "jiraProjectKey"
  | "jiraIssueKey"
  | "jiraIssueType"
  | "jiraIssueTypeId"
  | "jiraSummary"
  | "jiraDescription"
  | "jiraJql"
  | "jiraAssigneeAccountId"
  | "jiraLabels"
  | "jiraCommentBody"
  | "jiraCommentId"
  | "jiraTransitionId"
  | "jiraAttachmentId"
  | "jiraAttachmentFilename"
  | "jiraAttachmentBase64"
  | "jiraAttachmentMimeType"
  | "jiraNotifySubject"
  | "jiraNotifyTextBody"
  | "jiraNotifyHtmlBody"
  | "jiraNotifyTo"
  | "jiraAccountId"
  | "jiraUsername"
  | "jiraUserEmail"
  | "jiraUserDisplayName"
  | "jiraUserProducts";

export interface JiraExpressionField {
  key: JiraExpressionFieldKey;
  label: string;
}

/** Returns ordered expression-evaluate dialog slots for the given Jira operation. */
export function getJiraExpressionFields(operation: string): JiraExpressionField[] {
  const op = operation || "searchIssues";
  const fields: JiraExpressionField[] = [];

  if (jiraPaginatedOperations.has(op)) {
    fields.push({ key: "jiraLimit", label: "Limit" });
    if (op === "searchIssues") {
      fields.push({ key: "jiraNextPageToken", label: "Next Page Token" });
    }
    if (jiraStartAtPaginatedOperations.has(op)) {
      fields.push({ key: "jiraStartAt", label: "Start At" });
    }
  }

  if (op === "createIssue") {
    fields.push({ key: "jiraProjectKey", label: "Project Key" });
    fields.push({ key: "jiraIssueType", label: "Issue Type" });
    fields.push({ key: "jiraIssueTypeId", label: "Issue Type ID" });
  }

  if (jiraIssueKeyOperations.has(op)) {
    fields.push({ key: "jiraIssueKey", label: "Issue Key or ID" });
  }

  if (op === "searchIssues") {
    fields.push({ key: "jiraJql", label: "JQL" });
    fields.push({ key: "jiraFields", label: "Issue Fields" });
  }

  if (op === "createIssue" || op === "updateIssue") {
    fields.push({ key: "jiraSummary", label: "Summary" });
    fields.push({ key: "jiraDescription", label: "Description" });
    fields.push({ key: "jiraAssigneeAccountId", label: "Assignee Account ID / Username" });
    fields.push({ key: "jiraLabels", label: "Labels" });
  }

  if (jiraCommentIdOperations.has(op)) {
    fields.push({ key: "jiraCommentId", label: "Comment ID" });
  }

  if (op === "createComment" || op === "updateComment") {
    fields.push({ key: "jiraCommentBody", label: "Comment Body" });
  }

  if (op === "transitionIssue") {
    fields.push({ key: "jiraTransitionId", label: "Transition ID" });
  }

  if (jiraAttachmentIdOperations.has(op)) {
    fields.push({ key: "jiraAttachmentId", label: "Attachment ID" });
  }

  if (op === "addAttachment") {
    fields.push({ key: "jiraAttachmentFilename", label: "Attachment Filename" });
    fields.push({ key: "jiraAttachmentBase64", label: "Attachment Base64" });
    fields.push({ key: "jiraAttachmentMimeType", label: "Attachment MIME Type" });
  }

  if (op === "notifyIssue") {
    fields.push({ key: "jiraNotifySubject", label: "Subject" });
    fields.push({ key: "jiraNotifyTextBody", label: "Text Body" });
    fields.push({ key: "jiraNotifyHtmlBody", label: "HTML Body" });
    fields.push({ key: "jiraNotifyTo", label: "Recipients JSON" });
  }

  if (jiraAccountIdOperations.has(op)) {
    fields.push({ key: "jiraAccountId", label: "Account ID / Username" });
  }

  if (op === "createUser") {
    fields.push({ key: "jiraUserEmail", label: "User Email" });
    fields.push({ key: "jiraUsername", label: "Username" });
    fields.push({ key: "jiraUserDisplayName", label: "Display Name" });
    fields.push({ key: "jiraUserProducts", label: "Products" });
  }

  return fields;
}
