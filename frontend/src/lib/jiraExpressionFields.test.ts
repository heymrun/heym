import { describe, expect, it } from "vitest";

import { getJiraExpressionFields } from "@/lib/jiraExpressionFields";

describe("getJiraExpressionFields", () => {
  it("returns no fields for getMyself", () => {
    expect(getJiraExpressionFields("getMyself")).toEqual([]);
  });

  it("includes pagination fields for listProjects", () => {
    const keys = getJiraExpressionFields("listProjects").map((field) => field.key);

    expect(keys).toEqual(["jiraLimit", "jiraStartAt"]);
  });

  it("includes pagination, JQL, and fields for searchIssues", () => {
    const keys = getJiraExpressionFields("searchIssues").map((field) => field.key);

    expect(keys).toEqual([
      "jiraLimit",
      "jiraNextPageToken",
      "jiraStartAt",
      "jiraJql",
      "jiraFields",
    ]);
  });

  it("includes issue key for getIssue", () => {
    const keys = getJiraExpressionFields("getIssue").map((field) => field.key);

    expect(keys).toEqual(["jiraIssueKey"]);
  });

  it("includes issue mutation fields for createIssue", () => {
    const keys = getJiraExpressionFields("createIssue").map((field) => field.key);

    expect(keys).toEqual([
      "jiraProjectKey",
      "jiraIssueType",
      "jiraIssueTypeId",
      "jiraSummary",
      "jiraDescription",
      "jiraAssigneeAccountId",
      "jiraLabels",
    ]);
  });

  it("includes issue key and mutation fields for updateIssue", () => {
    const keys = getJiraExpressionFields("updateIssue").map((field) => field.key);

    expect(keys).toEqual([
      "jiraIssueKey",
      "jiraSummary",
      "jiraDescription",
      "jiraAssigneeAccountId",
      "jiraLabels",
    ]);
  });

  it("includes issue key for deleteIssue", () => {
    const keys = getJiraExpressionFields("deleteIssue").map((field) => field.key);

    expect(keys).toEqual(["jiraIssueKey"]);
  });

  it("includes pagination and issue key for getIssueChangelog", () => {
    const keys = getJiraExpressionFields("getIssueChangelog").map((field) => field.key);

    expect(keys).toEqual(["jiraLimit", "jiraStartAt", "jiraIssueKey"]);
  });

  it("includes notification fields for notifyIssue", () => {
    const keys = getJiraExpressionFields("notifyIssue").map((field) => field.key);

    expect(keys).toEqual([
      "jiraIssueKey",
      "jiraNotifySubject",
      "jiraNotifyTextBody",
      "jiraNotifyHtmlBody",
      "jiraNotifyTo",
    ]);
  });

  it("includes pagination and issue key for listComments", () => {
    const keys = getJiraExpressionFields("listComments").map((field) => field.key);

    expect(keys).toEqual(["jiraLimit", "jiraStartAt", "jiraIssueKey"]);
  });

  it("includes issue key and comment body for createComment", () => {
    const keys = getJiraExpressionFields("createComment").map((field) => field.key);

    expect(keys).toEqual(["jiraIssueKey", "jiraCommentBody"]);
  });

  it("includes issue key and comment id for getComment", () => {
    const keys = getJiraExpressionFields("getComment").map((field) => field.key);

    expect(keys).toEqual(["jiraIssueKey", "jiraCommentId"]);
  });

  it("includes comment id and body fields for updateComment", () => {
    const keys = getJiraExpressionFields("updateComment").map((field) => field.key);

    expect(keys).toEqual(["jiraIssueKey", "jiraCommentId", "jiraCommentBody"]);
  });

  it("includes issue key and comment id for deleteComment", () => {
    const keys = getJiraExpressionFields("deleteComment").map((field) => field.key);

    expect(keys).toEqual(["jiraIssueKey", "jiraCommentId"]);
  });

  it("includes issue key for listTransitions", () => {
    const keys = getJiraExpressionFields("listTransitions").map((field) => field.key);

    expect(keys).toEqual(["jiraIssueKey"]);
  });

  it("includes issue key and transition id for transitionIssue", () => {
    const keys = getJiraExpressionFields("transitionIssue").map((field) => field.key);

    expect(keys).toEqual(["jiraIssueKey", "jiraTransitionId"]);
  });

  it("includes attachment upload fields for addAttachment", () => {
    const keys = getJiraExpressionFields("addAttachment").map((field) => field.key);

    expect(keys).toEqual([
      "jiraIssueKey",
      "jiraAttachmentFilename",
      "jiraAttachmentBase64",
      "jiraAttachmentMimeType",
    ]);
  });

  it("includes attachment id field for getAttachment", () => {
    const keys = getJiraExpressionFields("getAttachment").map((field) => field.key);

    expect(keys).toEqual(["jiraAttachmentId"]);
  });

  it("includes pagination and issue key for listAttachments", () => {
    const keys = getJiraExpressionFields("listAttachments").map((field) => field.key);

    expect(keys).toEqual(["jiraLimit", "jiraStartAt", "jiraIssueKey"]);
  });

  it("includes attachment id field for deleteAttachment", () => {
    const keys = getJiraExpressionFields("deleteAttachment").map((field) => field.key);

    expect(keys).toEqual(["jiraAttachmentId"]);
  });

  it("includes account id for getUser", () => {
    const keys = getJiraExpressionFields("getUser").map((field) => field.key);

    expect(keys).toEqual(["jiraAccountId"]);
  });

  it("includes user fields for createUser", () => {
    const keys = getJiraExpressionFields("createUser").map((field) => field.key);

    expect(keys).toEqual([
      "jiraUserEmail",
      "jiraUsername",
      "jiraUserDisplayName",
      "jiraUserProducts",
    ]);
  });

  it("includes account id for deleteUser", () => {
    const keys = getJiraExpressionFields("deleteUser").map((field) => field.key);

    expect(keys).toEqual(["jiraAccountId"]);
  });
});
