"""Tests for workflow assistant prompt including node templates."""

import unittest

from app.services.workflow_dsl_prompt import build_assistant_prompt


class TestBuildAssistantPromptNodeTemplates(unittest.TestCase):
    """Verify node templates are surfaced to the canvas AI builder prompt."""

    def test_includes_node_templates_section(self) -> None:
        templates = [
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "name": "Shared LLM preset",
                "description": "A shared configuration",
                "tags": ["demo"],
                "node_type": "llm",
                "node_data": {"label": "llm1", "userMessage": "Hi"},
            }
        ]
        prompt = build_assistant_prompt(
            None,
            None,
            None,
            available_node_templates=templates,
        )
        self.assertIn("## Available node templates", prompt)
        self.assertIn("Shared LLM preset", prompt)
        self.assertIn("node_type", prompt)

    def test_includes_current_workflow_goal_without_nodes(self) -> None:
        prompt = build_assistant_prompt(
            {
                "id": "00000000-0000-4000-8000-000000000002",
                "name": "Lead qualification workflow",
                "description": "Score inbound leads and route qualified prospects.",
                "nodes": [],
                "edges": [],
            }
        )

        self.assertIn("## Current Workflow Goal", prompt)
        self.assertIn("Lead qualification workflow", prompt)
        self.assertIn("Score inbound leads", prompt)
        self.assertIn("when the user says to generate/build/create it", prompt)

    def test_includes_imap_trigger_guidance(self) -> None:
        prompt = build_assistant_prompt()

        self.assertIn("imapTrigger", prompt)
        self.assertIn("pollIntervalMinutes", prompt)
        self.assertIn("imap-credential-uuid", prompt)

    def test_includes_telegram_guidance(self) -> None:
        prompt = build_assistant_prompt()

        self.assertIn("telegramTrigger", prompt)
        self.assertIn('"type": "telegram"', prompt)
        self.assertIn("telegram-credential-uuid", prompt)

    def test_includes_websocket_guidance(self) -> None:
        prompt = build_assistant_prompt()

        self.assertIn("websocketTrigger", prompt)
        self.assertIn("websocketSend", prompt)
        self.assertIn("websocketTriggerEvents", prompt)
        self.assertIn("websocketMessage", prompt)

    def test_includes_amazon_s3_guidance(self) -> None:
        prompt = build_assistant_prompt()

        self.assertIn("### 32. s3 (Amazon S3 Operations)", prompt)
        self.assertIn('"type": "s3"', prompt)
        self.assertIn("s3Operation", prompt)
        self.assertIn("s3ContentType", prompt)
        self.assertIn("putObject", prompt)
        self.assertIn("createBucket", prompt)
        self.assertIn('"nodes": [', prompt)
        self.assertIn('"edges": [', prompt)
        self.assertIn('"label": "bucketRequest"', prompt)
        self.assertIn('"s3Bucket": "$bucketRequest.body.bucketName"', prompt)

    def test_includes_github_guidance(self) -> None:
        prompt = build_assistant_prompt()

        self.assertIn("### 35. github (GitHub REST Operations)", prompt)
        self.assertIn('"type": "github"', prompt)
        self.assertIn("githubOperation", prompt)
        self.assertIn("createIssue", prompt)
        self.assertIn("dispatchWorkflowAndWait", prompt)
        self.assertIn("githubWorkflowInputs", prompt)
        self.assertIn("githubFilePath", prompt)

    def test_includes_sentry_guidance(self) -> None:
        prompt = build_assistant_prompt()

        self.assertIn("### 34. sentry (Sentry REST Operations)", prompt)
        self.assertIn('"type": "sentry"', prompt)
        self.assertIn("sentryOperation", prompt)
        self.assertIn("listIssues", prompt)
        self.assertIn("createRelease", prompt)
        self.assertIn("sentryOrganizationSlug", prompt)

    def test_includes_linear_guidance(self) -> None:
        prompt = build_assistant_prompt()

        self.assertIn("### 33. linear (Linear Workspace and Issue Operations)", prompt)
        self.assertIn('"type": "linear"', prompt)
        self.assertIn("linearOperation", prompt)
        self.assertIn("linearTeamId", prompt)
        self.assertIn("linearAfter", prompt)
        self.assertIn("listWorkflowStates", prompt)
        self.assertIn("listTeamMembers", prompt)
        self.assertIn("createIssue", prompt)
        self.assertIn("createComment", prompt)
        self.assertIn("listComments", prompt)
        self.assertIn("updateComment", prompt)
        self.assertIn("deleteComment", prompt)
        self.assertIn("resolveComment", prompt)
        self.assertIn("linearCommentId", prompt)

    def test_includes_notion_guidance(self) -> None:
        prompt = build_assistant_prompt()

        self.assertIn("### 24B. notion", prompt)
        self.assertIn('"type": "notion"', prompt)
        self.assertIn("notionDataSourceId", prompt)
        self.assertIn("queryDataSource", prompt)
        self.assertIn("retrieveDataSource", prompt)
        self.assertIn("createDataSource", prompt)
        self.assertIn("updateDataSource", prompt)
        self.assertIn("createDatabase", prompt)
        self.assertIn("retrieveDatabase", prompt)
        self.assertIn("updateDatabase", prompt)

    def test_includes_filter_map_nested_reference_guidance(self) -> None:
        prompt = build_assistant_prompt()

        correct_filter = (
            "$extractData.commitList.filter("
            "\"item.date == $dateLoop.item and item.repo == 'dify'\""
            ").length"
        )
        wrong_filter = (
            "$extractData.commitList.filter("
            "\"item.date == dateLoop.item && item.repo == 'dify'\""
            ").length"
        )

        self.assertIn("Inside `.filter()` and `.map()` expression strings", prompt)
        self.assertIn(correct_filter, prompt)
        self.assertIn(wrong_filter, prompt)
        self.assertIn("Use Python-style boolean operators", prompt)
        self.assertIn("References to other nodes, loop context, or variables MUST keep `$`", prompt)
        self.assertNotIn("NEVER USE $ INSIDE PARENTHESES", prompt)
        self.assertNotIn("NO $ INSIDE PARENTHESES", prompt)


if __name__ == "__main__":
    unittest.main()
