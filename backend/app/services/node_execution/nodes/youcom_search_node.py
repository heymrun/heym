"""You.com web search node for Heym workflows."""

from __future__ import annotations

import os
from importlib import import_module
from typing import Any

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> dict[str, Any]:
    """Execute the You.com search node.
    
    Searches the web using the You.com Search API and returns structured results.
    Falls back to keyless tier when no API key is provided.
    
    Node inputs:
        query (str): Search query
        count (int, optional): Number of results (default: 10, max: 20)
        safesearch (str, optional): Safe search level: off, moderate, strict (default: moderate)
        
    Environment:
        YDC_API_KEY (optional): You.com API key for higher quotas and enhanced features
        
    Returns:
        dict containing:
            results: List of search results with title, url, snippet
            query: Original search query
            count: Number of results returned
            has_api_key: Whether API key was used
    """
    ssrf_guard = import_module("app.services.ssrf_guard")
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data
    
    # Get search parameters from inputs and node_data
    query = inputs.get("query") or node_data.get("query", "")
    if not query:
        raise ValueError("You.com search node requires a search query")
    
    # Evaluate template if needed
    query = self.evaluate_message_template(query, inputs, node_id)
    
    count = inputs.get("count") or node_data.get("count", 10)
    count = min(max(int(count), 1), 20)  # Clamp between 1 and 20
    
    safesearch = inputs.get("safesearch") or node_data.get("safesearch", "moderate")
    if safesearch not in ["off", "moderate", "strict"]:
        safesearch = "moderate"
    
    # Check for API key
    api_key = os.getenv("YDC_API_KEY")
    has_api_key = bool(api_key)
    
    # Prepare request
    headers = {
        "User-Agent": "youdotcom-integration/heymrun-heym"
    }
    
    if has_api_key:
        # Use authenticated API endpoint
        url = "https://ydc-index.io/v1/search"
        headers["Authorization"] = f"Bearer {api_key}"
        params = {
            "query": query,
            "num_web_results": count,
            "safesearch": safesearch
        }
    else:
        # Use keyless endpoint (100 free searches/day per IP)
        url = "https://api.you.com/v1/agents/search"  
        params = {
            "query": query,
            "count": count,
            "safesearch": safesearch
        }
    
    # Build request URL with query parameters
    param_str = "&".join(f"{k}={v}" for k, v in params.items())
    full_url = f"{url}?{param_str}"
    
    # Apply SSRF guard
    ssrf_guard.guard_http_url(full_url)
    
    try:
        # Make HTTP request
        http_client = ssrf_guard.get_guarded_http_client()
        response = http_client.get(full_url, headers=headers, timeout=15.0)
        
        if response.status_code == 401:
            if has_api_key:
                raise ValueError("You.com API key is invalid or expired")
            else:
                raise ValueError("You.com keyless endpoint returned unauthorized")
                
        elif response.status_code == 402:
            if has_api_key:
                raise ValueError("You.com API quota exceeded. Please check your plan.")
            else:
                raise ValueError("You.com free quota exceeded (100 searches/day per IP). Consider adding YDC_API_KEY for higher limits.")
                
        elif response.status_code == 429:
            raise ValueError("You.com search rate limited. Please try again later.")
            
        elif response.status_code >= 400:
            raise ValueError(f"You.com search failed with status {response.status_code}")
            
        # Parse response
        try:
            data = response.json()
        except ValueError as e:
            raise ValueError(f"Invalid JSON response from You.com: {e}")
        
        # Extract results based on API response format
        if has_api_key:
            # Authenticated API format
            web_results = data.get("hits", [])
            results = []
            for hit in web_results[:count]:
                results.append({
                    "title": hit.get("title", ""),
                    "url": hit.get("url", ""),
                    "snippet": hit.get("snippets", [""])[0] if hit.get("snippets") else ""
                })
        else:
            # Keyless API format
            web_results = data.get("results", {}).get("web", [])
            results = []
            for result in web_results[:count]:
                results.append({
                    "title": result.get("name", ""),
                    "url": result.get("url", ""),
                    "snippet": result.get("description", "")
                })
        
        return {
            "results": results,
            "query": query,
            "count": len(results),
            "has_api_key": has_api_key,
            "total_results": len(web_results),
            "status": "success"
        }
        
    except Exception as e:
        # Return error information for workflow debugging
        error_msg = str(e)
        if "quota exceeded" in error_msg.lower():
            suggestion = "Consider adding YDC_API_KEY environment variable for higher quotas" if not has_api_key else "Check your You.com plan limits"
        elif "rate limit" in error_msg.lower():
            suggestion = "Wait a few minutes before retrying"
        elif "unauthorized" in error_msg.lower() or "invalid" in error_msg.lower():
            suggestion = "Check your YDC_API_KEY environment variable"
        else:
            suggestion = "Check network connectivity and query parameters"
            
        return {
            "results": [],
            "query": query,
            "count": 0,
            "has_api_key": has_api_key,
            "status": "error",
            "error": error_msg,
            "suggestion": suggestion
        }