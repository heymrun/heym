"""Test the You.com search node."""

import pytest
from unittest.mock import Mock, patch
from app.services.node_execution.base import NodeExecutionContext
from app.services.node_execution.nodes import youcom_search_node


class MockResponse:
    def __init__(self, json_data, status_code=200):
        self.json_data = json_data
        self.status_code = status_code
        
    def json(self):
        return self.json_data


class TestYoucomSearchNode:
    def setup_method(self):
        self.executor = Mock()
        self.executor.evaluate_message_template = Mock(side_effect=lambda x, *args: x)
        
    def create_context(self, inputs=None, node_data=None):
        return NodeExecutionContext(
            executor=self.executor,
            node_id="test-node",
            inputs=inputs or {},
            allow_branch_skip=False,
            start_time=0.0,
            node={},
            node_type="youcomSearch",
            node_data=node_data or {},
            node_label="test"
        )

    @patch("os.getenv")
    @patch("app.services.node_execution.nodes.youcom_search_node.import_module")
    def test_keyless_search_success(self, mock_import, mock_getenv):
        # Setup
        mock_getenv.return_value = None  # No API key
        
        # Mock HTTP client and response
        mock_ssrf_guard = Mock()
        mock_http_client = Mock()
        mock_response = MockResponse({
            "results": {
                "web": [
                    {
                        "name": "Test Title",
                        "url": "https://example.com",
                        "description": "Test description"
                    }
                ]
            }
        })
        mock_http_client.get.return_value = mock_response
        mock_ssrf_guard.get_guarded_http_client.return_value = mock_http_client
        mock_import.return_value = mock_ssrf_guard
        
        ctx = self.create_context(
            inputs={"query": "test query"},
            node_data={"count": 5}
        )
        
        # Execute
        result = youcom_search_node.execute(ctx)
        
        # Verify
        assert result["status"] == "success"
        assert result["query"] == "test query"
        assert result["count"] == 1
        assert result["has_api_key"] is False
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Test Title"
        assert result["results"][0]["url"] == "https://example.com"
        assert result["results"][0]["snippet"] == "Test description"

    @patch("os.getenv")
    @patch("app.services.node_execution.nodes.youcom_search_node.import_module")
    def test_authenticated_search_success(self, mock_import, mock_getenv):
        # Setup
        mock_getenv.return_value = "test-api-key"
        
        # Mock HTTP client and response
        mock_ssrf_guard = Mock()
        mock_http_client = Mock()
        mock_response = MockResponse({
            "hits": [
                {
                    "title": "Auth Test Title",
                    "url": "https://example.com/auth",
                    "snippets": ["Auth test snippet"]
                }
            ]
        })
        mock_http_client.get.return_value = mock_response
        mock_ssrf_guard.get_guarded_http_client.return_value = mock_http_client
        mock_import.return_value = mock_ssrf_guard
        
        ctx = self.create_context(
            inputs={"query": "auth test query"},
            node_data={"count": 10}
        )
        
        # Execute
        result = youcom_search_node.execute(ctx)
        
        # Verify
        assert result["status"] == "success"
        assert result["query"] == "auth test query"
        assert result["count"] == 1
        assert result["has_api_key"] is True
        assert len(result["results"]) == 1
        assert result["results"][0]["title"] == "Auth Test Title"

    @patch("os.getenv")
    @patch("app.services.node_execution.nodes.youcom_search_node.import_module")
    def test_quota_exceeded_error(self, mock_import, mock_getenv):
        # Setup
        mock_getenv.return_value = None  # No API key
        
        # Mock HTTP client and 402 response
        mock_ssrf_guard = Mock()
        mock_http_client = Mock()
        mock_response = MockResponse({}, 402)
        mock_http_client.get.return_value = mock_response
        mock_ssrf_guard.get_guarded_http_client.return_value = mock_http_client
        mock_import.return_value = mock_ssrf_guard
        
        ctx = self.create_context(inputs={"query": "test query"})
        
        # Execute
        result = youcom_search_node.execute(ctx)
        
        # Verify error handling
        assert result["status"] == "error"
        assert result["count"] == 0
        assert "quota exceeded" in result["error"].lower()
        assert "YDC_API_KEY" in result["suggestion"]

    def test_missing_query_error(self):
        ctx = self.create_context(inputs={}, node_data={})
        
        with pytest.raises(ValueError, match="requires a search query"):
            youcom_search_node.execute(ctx)

    @patch("os.getenv")
    @patch("app.services.node_execution.nodes.youcom_search_node.import_module")
    def test_network_error_handling(self, mock_import, mock_getenv):
        # Setup
        mock_getenv.return_value = None
        
        # Mock HTTP client that raises exception
        mock_ssrf_guard = Mock()
        mock_http_client = Mock()
        mock_http_client.get.side_effect = Exception("Network error")
        mock_ssrf_guard.get_guarded_http_client.return_value = mock_http_client
        mock_import.return_value = mock_ssrf_guard
        
        ctx = self.create_context(inputs={"query": "test query"})
        
        # Execute
        result = youcom_search_node.execute(ctx)
        
        # Verify error handling
        assert result["status"] == "error"
        assert result["count"] == 0
        assert "Network error" in result["error"]
        assert "network connectivity" in result["suggestion"].lower()