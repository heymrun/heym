import unittest

from app.services.workflow_executor import WorkflowExecutor


class GitHubCredentialMcpResolutionTests(unittest.TestCase):
    def test_resolve_mcp_connection_injects_github_token_from_credentials_context(self) -> None:
        executor = WorkflowExecutor(
            nodes=[],
            edges=[],
            test_mode=True,
            credentials_context={"MyGitHubToken": "github_pat_123"},
        )

        resolved = executor._resolve_mcp_connection(
            {
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "@modelcontextprotocol/server-github"],
                "env": {
                    "GITHUB_PERSONAL_ACCESS_TOKEN": "$credentials.MyGitHubToken",
                },
            },
            {},
            None,
        )

        self.assertEqual(
            resolved["env"]["GITHUB_PERSONAL_ACCESS_TOKEN"],
            "github_pat_123",
        )


if __name__ == "__main__":
    unittest.main()
