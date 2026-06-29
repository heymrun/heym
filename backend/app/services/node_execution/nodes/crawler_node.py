from __future__ import annotations

from importlib import import_module

from app.services.node_execution.base import NodeExecutionContext


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the crawler node."""
    _workflow_executor = import_module("app.services.workflow_executor")
    get_http_client = _workflow_executor.get_http_client
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    credential_id = node_data.get("credentialId")
    if not credential_id:
        raise ValueError("Crawler node requires a FlareSolverr credential")

    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config

    flaresolverr_url = ""
    with SessionLocal() as db:
        cred = self._get_accessible_credential(db, credential_id)
        if cred:
            config = decrypt_config(cred.encrypted_config)
            flaresolverr_url = config.get("flaresolverr_url", "")

    if not flaresolverr_url:
        raise ValueError("FlareSolverr credential not found or missing URL")

    url_template = node_data.get("crawlerUrl", "$input.text")
    target_url = self.evaluate_message_template(url_template, inputs, node_id)
    if not target_url:
        raise ValueError("Crawler node requires a URL to crawl")

    wait_seconds = node_data.get("crawlerWaitSeconds", 0)
    max_timeout = node_data.get("crawlerMaxTimeout", 60000)

    request_body: dict = {
        "cmd": "request.get",
        "url": target_url,
        "maxTimeout": max_timeout,
    }
    if wait_seconds and int(wait_seconds) > 0:
        request_body["waitInSeconds"] = int(wait_seconds)

    http_client = get_http_client()
    response = http_client.post(
        flaresolverr_url,
        json=request_body,
        timeout=max(max_timeout / 1000 + 30, 120),
    )

    if response.status_code >= 400:
        raise ValueError(f"FlareSolverr error: {response.text}")

    try:
        response_json = response.json()
    except ValueError:
        raise ValueError(f"Invalid JSON response from FlareSolverr: {response.text}")

    solution = response_json.get("solution", {})
    html_content = solution.get("response", "")

    crawler_mode = node_data.get("crawlerMode", "basic")

    if crawler_mode == "extract":
        from bs4 import BeautifulSoup

        selectors = node_data.get("crawlerSelectors", [])
        extracted: dict = {}

        if selectors:
            soup = BeautifulSoup(html_content, "html.parser")

            for selector_config in selectors:
                selector_name = selector_config.get("name", "")
                css_selector = selector_config.get("selector", "")
                attributes = selector_config.get("attributes", [])

                if not selector_name or not css_selector:
                    continue

                elements = soup.select(css_selector)
                selector_results = []

                for element in elements:
                    raw_text = element.get_text(separator="\n", strip=True)
                    result_item: dict = {"text": raw_text}
                    for attr in attributes:
                        attr_value = element.get(attr)
                        if attr_value is not None:
                            result_item[attr] = attr_value
                    selector_results.append(result_item)

                extracted[selector_name] = selector_results

        output = {
            "html": html_content,
            "extracted": extracted,
            "url": target_url,
            "status": solution.get("status", ""),
        }
    else:
        output = {
            "html": html_content,
            "url": target_url,
            "status": solution.get("status", ""),
        }
    return output
