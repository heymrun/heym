from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.services import ssrf_guard
from app.services.node_execution.base import NodeExecutionContext

if TYPE_CHECKING:
    from bs4 import Tag


def _extract_element(element: Tag, attributes: list[str]) -> dict[str, Any]:
    raw_text = element.get_text(separator="\n", strip=True)
    result_item: dict[str, Any] = {"text": raw_text}
    for attr in attributes:
        attr_value = element.get(attr)
        if attr_value is not None:
            result_item[attr] = attr_value
    return result_item


def _extract_selectors(
    html_content: str, selectors: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    if not selectors:
        return {}

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, "html.parser")
    extracted: dict[str, list[dict[str, Any]]] = {}

    for selector_config in selectors:
        selector_name = selector_config.get("name", "")
        css_selector = selector_config.get("selector", "")
        if not selector_name or not css_selector:
            continue

        attributes = selector_config.get("attributes", [])
        extracted[selector_name] = [
            _extract_element(element, attributes) for element in soup.select(css_selector)
        ]

    return extracted


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the crawler node."""
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
    target_url = self.evaluate_nonempty_message_template(url_template, inputs, node_id).strip()
    if not target_url:
        raise ValueError("Crawler node requires a URL to crawl")

    wait_seconds = node_data.get("crawlerWaitSeconds", 0)
    max_timeout = node_data.get("crawlerMaxTimeout", 60000)

    request_body: dict[str, Any] = {
        "cmd": "request.get",
        "url": target_url,
        "maxTimeout": max_timeout,
    }
    if wait_seconds and int(wait_seconds) > 0:
        request_body["waitInSeconds"] = int(wait_seconds)

    # Metadata-only: FlareSolverr normally runs on a private address. The crawl
    # target it resolves for itself is a separate hop, not guarded here.
    ssrf_guard.guard_carrier_url(flaresolverr_url, "FlareSolverr credential URL")
    http_client = ssrf_guard.get_guarded_carrier_http_client()
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
        selectors = node_data.get("crawlerSelectors", [])
        return {
            "html": html_content,
            "extracted": _extract_selectors(html_content, selectors),
            "url": target_url,
            "status": solution.get("status", ""),
        }

    return {
        "html": html_content,
        "url": target_url,
        "status": solution.get("status", ""),
    }
