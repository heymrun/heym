"""Generate Playwright Python code from step definitions."""

import json


def _expr_to_python(expr: str, default: str = '""') -> str:
    """Convert Heym expression like $userInput.body.url to Python that reads from inputs."""
    if not expr or not str(expr).strip():
        return default
    s = str(expr).strip()
    if not s.startswith("$"):
        return repr(s)
    path = s[1:].split(".")
    if not path:
        return default
    if len(path) == 1:
        return f"inputs.get({repr(path[0])}, {default})"
    result = f"inputs.get({repr(path[0])}, {{}})"
    for key in path[1:-1]:
        result = f"({result}).get({repr(key)}, {{}})"
    result = f"({result}).get({repr(path[-1])}, {default})"
    return result


def _step_timeout_kwarg(step: dict) -> str:
    """Return 'timeout=X' if step has timeout, else ''."""
    t = step.get("timeout")
    if t is not None:
        return f"timeout={int(t)}"
    return ""


def normalize_playwright_auth_state(raw: object) -> dict[str, object] | None:
    """Normalize user-provided auth state into a cookies or storageState payload."""
    value = raw
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(
                "Playwright auth state must be valid JSON, a cookies array, or a storageState object."
            ) from exc

    if value is None:
        return None

    if isinstance(value, list):
        if not value:
            return None
        if any(not isinstance(item, dict) for item in value):
            raise ValueError("Playwright auth cookies must be a list of objects.")
        return {"mode": "cookies", "cookies": value}

    if not isinstance(value, dict):
        raise ValueError(
            "Playwright auth state must resolve to a cookies array or a storageState object."
        )

    if not value:
        return None

    cookies = value.get("cookies")
    origins = value.get("origins")
    if cookies is None and origins is None:
        raise ValueError(
            "Playwright auth storageState must contain a 'cookies' array or an 'origins' array."
        )

    if cookies is not None:
        if not isinstance(cookies, list):
            raise ValueError("Playwright auth storageState 'cookies' must be a list.")
        if any(not isinstance(item, dict) for item in cookies):
            raise ValueError("Playwright auth storageState cookies must be objects.")

    if origins is not None:
        if not isinstance(origins, list):
            raise ValueError("Playwright auth storageState 'origins' must be a list.")
        if any(not isinstance(item, dict) for item in origins):
            raise ValueError("Playwright auth storageState origins must be objects.")

    if not cookies and not origins:
        return None

    return {"mode": "storageState", "storageState": value}


def _indent_lines(lines: list[str], spaces: int) -> list[str]:
    prefix = " " * spaces
    return [f"{prefix}{line}" if line else "" for line in lines]


def _generate_step_lines(
    step: dict,
    step_idx: int,
    save_steps_target: str | None = None,
) -> list[str]:
    """Generate Python lines for a single Playwright step without outer indentation."""
    lines: list[str] = []
    action = step.get("action", "navigate")
    selector = step.get("selector", "")
    url = step.get("url", "https://example.com")
    text = step.get("text", "")
    value = step.get("value", "")
    attribute = step.get("attribute", "")
    timeout = step.get("timeout")
    output_key = step.get("outputKey", "value")
    to_kw = _step_timeout_kwarg(step)

    if action == "navigate":
        url_val = _expr_to_python(url, '"https://example.com"')
        goto_args = f"{url_val}" + (f", {to_kw}" if to_kw else "")
        lines.append(f"page.goto({goto_args})")
    elif action == "click":
        sel_val = _expr_to_python(selector, '"button"')
        lines.append(f"_pw_click_loc = page.locator({sel_val})")
        if to_kw:
            lines.append(f"_pw_click_loc.first.wait_for(state='visible', {to_kw})")
        else:
            lines.append("_pw_click_loc.first.wait_for(state='visible')")
        lines.append("_pw_click_n = _pw_click_loc.count()")
        lines.append("for _pw_click_i in range(_pw_click_n):")
        if to_kw:
            lines.append(f"    _pw_click_loc.nth(_pw_click_i).click({to_kw})")
        else:
            lines.append("    _pw_click_loc.nth(_pw_click_i).click()")
    elif action == "type":
        sel_val = _expr_to_python(selector, '"input"')
        text_val = _expr_to_python(text, '""')
        lines.append(f"page.locator({sel_val}).fill('')")
        type_args = f"{text_val}, delay=50" + (f", {to_kw}" if to_kw else "")
        lines.append(f"page.locator({sel_val}).type({type_args})")
    elif action == "fill":
        sel_val = _expr_to_python(selector, '"input"')
        val = _expr_to_python(value, '""')
        fill_args = f"{val}" + (f", {to_kw}" if to_kw else "")
        lines.append(f"page.locator({sel_val}).fill({fill_args})")
    elif action == "wait":
        try:
            ms = max(0, int(timeout)) if timeout is not None else 4000
        except (ValueError, TypeError):
            ms = 4000
        lines.append(f"page.wait_for_timeout({ms})")
    elif action == "screenshot":
        key = output_key or "screenshot"
        shot_args = f"({to_kw})" if to_kw else "()"
        lines.append(f"screenshot = page.screenshot{shot_args}")
        lines.append(
            f'results[{repr(key)}] = base64.b64encode(screenshot).decode("utf-8") if isinstance(screenshot, bytes) else str(screenshot)'
        )
    elif action == "getText":
        key = output_key or "text"
        sel_val = _expr_to_python(selector, '"body"')
        if timeout is not None:
            lines.append(f"_loc = page.locator({sel_val}).first")
            lines.append(f"_loc.wait_for(state='visible', timeout={int(timeout)})")
            lines.append(f'results[{repr(key)}] = _loc.text_content() or ""')
        else:
            lines.append(
                f'results[{repr(key)}] = page.locator({sel_val}).first.text_content() or ""'
            )
    elif action == "getAttribute":
        key = output_key or "attr"
        attr = attribute or "href"
        sel_val = _expr_to_python(selector, '"a"')
        if timeout is not None:
            lines.append(f"_loc = page.locator({sel_val}).first")
            lines.append(f"_loc.wait_for(state='visible', timeout={int(timeout)})")
            lines.append("el = _loc")
        else:
            lines.append(f"el = page.locator({sel_val}).first")
        lines.append(f'results[{repr(key)}] = el.get_attribute({repr(attr)}) or ""')
    elif action == "getHTML":
        key = output_key or "html"
        sel_val = _expr_to_python(selector, '"body"')
        if timeout is not None:
            lines.append(f"_loc = page.locator({sel_val}).first")
            lines.append(f"_loc.wait_for(state='visible', timeout={int(timeout)})")
            lines.append(f'results[{repr(key)}] = _loc.evaluate("el => el.outerHTML") or ""')
        else:
            lines.append(
                f'results[{repr(key)}] = page.locator({sel_val}).first.evaluate("el => el.outerHTML") or ""'
            )
    elif action == "getVisibleTextOnPage":
        key = output_key or "visibleText"
        if timeout is not None:
            lines.append(f"page.wait_for_timeout({int(timeout)})")
        lines.append(
            f'results[{repr(key)}] = page.evaluate("() => document.body ? document.body.innerText : \'\'") or ""'
        )
    elif action == "hover":
        sel_val = _expr_to_python(selector, '"body"')
        args = f"({to_kw})" if to_kw else "()"
        lines.append(f"page.locator({sel_val}).first.hover{args}")
    elif action == "selectOption":
        sel_val = _expr_to_python(selector, '"select"')
        val = _expr_to_python(value, '""')
        opt_args = f"{val}" + (f", {to_kw}" if to_kw else "")
        lines.append(f"page.locator({sel_val}).select_option({opt_args})")
    elif action == "scrollDown":
        amount = int(step.get("amount", 300) or 300)
        wait_ms = int(timeout) if timeout is not None else 1000
        lines.append('_vp = page.viewport_size or {"width": 1280, "height": 720}')
        lines.append('page.mouse.move(_vp["width"] / 2, _vp["height"] / 2)')
        lines.append(f"page.mouse.wheel(0, {amount})")
        lines.append(f"page.wait_for_timeout({wait_ms})")
    elif action == "scrollUp":
        amount = int(step.get("amount", 300) or 300)
        wait_ms = int(timeout) if timeout is not None else 1000
        lines.append('_vp = page.viewport_size or {"width": 1280, "height": 720}')
        lines.append('page.mouse.move(_vp["width"] / 2, _vp["height"] / 2)')
        lines.append(f"page.mouse.wheel(0, -{amount})")
        lines.append(f"page.wait_for_timeout({wait_ms})")
    elif action == "aiStep":
        ai_instructions = _expr_to_python(step.get("instructions", ""), '""')
        ai_credential_id = _expr_to_python(step.get("credentialId", ""), '""')
        ai_model = _expr_to_python(step.get("model", ""), '""')
        ai_log = step.get("logStepsToConsole", False)
        ai_save = step.get("saveStepsForFuture", False)
        ai_auto_heal = step.get("autoHealMode", False)
        ai_screenshot = step.get("sendScreenshot", False)
        ai_timeout_ms = step.get("aiStepTimeout", 30000)
        ai_saved = step.get("savedSteps") or []
        try:
            ai_timeout_sec = max(5, min(300, int(ai_timeout_ms) // 1000))
        except (ValueError, TypeError):
            ai_timeout_sec = 30
        lines.extend(
            [
                "_html = page.content()",
                "_screenshot_b64 = None",
                f"if {ai_screenshot}:",
                "    _shot = page.screenshot()",
                "    _screenshot_b64 = base64.b64encode(_shot).decode('utf-8') if isinstance(_shot, bytes) else str(_shot)",
                "_body = {",
                "    'html': _html,",
                "    'instructions': " + ai_instructions + ",",
                "    'credentialId': " + ai_credential_id + ",",
                "    'model': " + ai_model + ",",
                "    'logStepsToConsole': " + str(ai_log) + ",",
                "    'saveStepsForFuture': " + str(ai_save) + ",",
                "    'savedSteps': " + repr(ai_saved) + ",",
                "    'screenshotBase64': _screenshot_b64,",
                "}",
                "_req = Request(",
                "    _heym_api_url.rstrip('/') + '/api/playwright/ai-step',",
                "    data=json.dumps(_body).encode('utf-8'),",
                "    headers={'Content-Type': 'application/json', 'X-Execution-Token': _heym_execution_token},",
                "    method='POST',",
                ")",
                f"with urlopen(_req, timeout={ai_timeout_sec}) as _resp:",
                "    _ai_result = json.loads(_resp.read().decode())",
                "_ai_steps = _ai_result.get('steps', [])",
                "_effective_steps = list(_ai_steps)",
                "_heal_timeout = 5000",
                "for _i, _s in enumerate(_ai_steps):",
                "    _a = _s.get('action', '')",
                "    _sel = _s.get('selector', '')",
                "    _step_done = False",
                "    if _a == 'wait':",
                "        page.wait_for_timeout(int(_s.get('timeout', 2000)) or 2000)",
                "        _step_done = True",
                "    elif _a == 'scrollDown':",
                "        _amt = int(_s.get('amount', 300)) or 300",
                "        _vp = page.viewport_size or {'width': 1280, 'height': 720}",
                "        page.mouse.move(_vp['width'] / 2, _vp['height'] / 2)",
                "        page.mouse.wheel(0, _amt)",
                "        page.wait_for_timeout(1000)",
                "        _step_done = True",
                "    elif _a == 'scrollUp':",
                "        _amt = int(_s.get('amount', 300)) or 300",
                "        _vp = page.viewport_size or {'width': 1280, 'height': 720}",
                "        page.mouse.move(_vp['width'] / 2, _vp['height'] / 2)",
                "        page.mouse.wheel(0, -_amt)",
                "        page.wait_for_timeout(1000)",
                "        _step_done = True",
                "    elif _a == 'navigate':",
                "        _nurl = str(_s.get('url', '') or '')",
                "        if not _nurl:",
                "            raise RuntimeError(f'AI step {_i} navigate: missing url')",
                "        page.goto(_nurl)",
                "        _step_done = True",
                "    elif _a == 'getText':",
                "        _gtk = _s.get('outputKey', 'text') or 'text'",
                "        _gtsel = str(_s.get('selector', '') or 'body')",
                "        _gttmo = _s.get('timeout')",
                "        if _gttmo is not None:",
                "            _gtloc = page.locator(_gtsel).first",
                "            _gtloc.wait_for(state='visible', timeout=int(_gttmo))",
                "            results[_gtk] = _gtloc.text_content() or ''",
                "        else:",
                "            results[_gtk] = page.locator(_gtsel).first.text_content() or ''",
                "        _step_done = True",
                "    elif _a == 'getAttribute':",
                "        _gak = _s.get('outputKey', 'attr') or 'attr'",
                "        _gasel = str(_s.get('selector', '') or '')",
                "        if not _gasel:",
                "            raise RuntimeError(f'AI step {_i} getAttribute: missing selector')",
                "        _gaattr = str(_s.get('attribute', '') or 'href')",
                "        _gatmo = _s.get('timeout')",
                "        if _gatmo is not None:",
                "            _galoc = page.locator(_gasel).first",
                "            _galoc.wait_for(state='visible', timeout=int(_gatmo))",
                "            _gael = _galoc",
                "        else:",
                "            _gael = page.locator(_gasel).first",
                "        results[_gak] = _gael.get_attribute(_gaattr) or ''",
                "        _step_done = True",
                "    elif _a == 'getHTML':",
                "        _ghk = _s.get('outputKey', 'html') or 'html'",
                "        _ghsel = str(_s.get('selector', '') or 'body')",
                "        _ghtmo = _s.get('timeout')",
                "        if _ghtmo is not None:",
                "            _ghloc = page.locator(_ghsel).first",
                "            _ghloc.wait_for(state='visible', timeout=int(_ghtmo))",
                "            results[_ghk] = _ghloc.evaluate('el => el.outerHTML') or ''",
                "        else:",
                "            results[_ghk] = page.locator(_ghsel).first.evaluate('el => el.outerHTML') or ''",
                "        _step_done = True",
                "    elif _a == 'getVisibleTextOnPage':",
                "        _gvtk = _s.get('outputKey', 'visibleText') or 'visibleText'",
                "        _gvto = _s.get('timeout')",
                "        if _gvto is not None:",
                "            page.wait_for_timeout(int(_gvto))",
                "        results[_gvtk] = page.evaluate(\"() => document.body ? document.body.innerText : ''\") or ''",
                "        _step_done = True",
                "    elif _a == 'screenshot':",
                "        _key = _s.get('outputKey', 'screenshot') or 'screenshot'",
                "        _shot = page.screenshot()",
                "        screenshot = _shot",
                "        results[_key] = base64.b64encode(_shot).decode('utf-8') if isinstance(_shot, bytes) else str(_shot)",
                "        _step_done = True",
                "    else:",
                "        for _attempt in range(2):",
                "            try:",
                "                if _a == 'click' and _sel:",
                "                    page.locator(_sel).first.click(timeout=_heal_timeout)",
                "                elif _a == 'type' and _sel:",
                "                    _t = _s.get('text', '')",
                "                    page.locator(_sel).first.fill('')",
                "                    page.locator(_sel).first.type(_t, delay=50, timeout=_heal_timeout)",
                "                elif _a == 'fill' and _sel:",
                "                    page.locator(_sel).first.fill(_s.get('value', ''), timeout=_heal_timeout)",
                "                elif _a == 'hover' and _sel:",
                "                    page.locator(_sel).first.hover(timeout=_heal_timeout)",
                "                elif _a == 'selectOption' and _sel:",
                "                    page.locator(_sel).first.select_option(_s.get('value', ''), timeout=_heal_timeout)",
                "                else:",
                "                    _step_done = True",
                "                    break",
                "                _step_done = True",
                "                break",
                "            except Exception:",
                f"                if _attempt == 1 and {ai_auto_heal}:",
                "                    _heal_html = page.content()",
                "                    _heal_shot = page.screenshot()",
                "                    _heal_shot_b64 = base64.b64encode(_heal_shot).decode('utf-8') if isinstance(_heal_shot, bytes) else str(_heal_shot)",
                "                    _heal_body = {",
                "                        'html': _heal_html,",
                "                        'failedStep': _s,",
                "                        'credentialId': " + ai_credential_id + ",",
                "                        'model': " + ai_model + ",",
                "                        'instructions': " + ai_instructions + ",",
                "                        'logStepsToConsole': " + str(ai_log) + ",",
                "                        'screenshotBase64': _heal_shot_b64,",
                "                    }",
                "                    _heal_req = Request(",
                "                        _heym_api_url.rstrip('/') + '/api/playwright/ai-step-heal',",
                "                        data=json.dumps(_heal_body).encode('utf-8'),",
                "                        headers={'Content-Type': 'application/json', 'X-Execution-Token': _heym_execution_token},",
                "                        method='POST',",
                "                    )",
                f"                    with urlopen(_heal_req, timeout={ai_timeout_sec}) as _heal_resp:",
                "                        _heal_result = json.loads(_heal_resp.read().decode())",
                "                    _heal_steps = _heal_result.get('steps', [])",
                "                    if _heal_steps:",
                "                        _hs = _heal_steps[0]",
                "                        _ha = _hs.get('action', '')",
                "                        _hsel = _hs.get('selector', '')",
                "                        if _ha == 'click' and _hsel:",
                "                            page.locator(_hsel).first.click(timeout=_heal_timeout)",
                "                        elif _ha == 'type' and _hsel:",
                "                            _ht = _hs.get('text', '')",
                "                            page.locator(_hsel).first.fill('')",
                "                            page.locator(_hsel).first.type(_ht, delay=50, timeout=_heal_timeout)",
                "                        elif _ha == 'fill' and _hsel:",
                "                            page.locator(_hsel).first.fill(_hs.get('value', ''), timeout=_heal_timeout)",
                "                        elif _ha == 'hover' and _hsel:",
                "                            page.locator(_hsel).first.hover(timeout=_heal_timeout)",
                "                        elif _ha == 'selectOption' and _hsel:",
                "                            page.locator(_hsel).first.select_option(_hs.get('value', ''), timeout=_heal_timeout)",
                "                        _effective_steps[_i] = _hs",
                "                        _step_done = True",
                "                        break",
                "                if _attempt == 1:",
                "                    raise",
                "    if not _step_done and _a not in (",
                "        'wait', 'scrollDown', 'scrollUp', 'screenshot', 'navigate',",
                "        'getText', 'getAttribute', 'getHTML', 'getVisibleTextOnPage',",
                "    ):",
                "        raise RuntimeError(f'AI step {_i} ({_a}) failed and auto heal disabled')",
            ]
        )
        if save_steps_target:
            lines.extend(
                [
                    f"if {ai_save}:",
                    f"    {save_steps_target}[{step_idx}] = _effective_steps",
                ]
            )

    lines.append("")
    return lines


def generate_playwright_code(
    steps: list[dict],
    capture_network: bool = False,
    auth_enabled: bool = False,
    auth_state: dict[str, object] | None = None,
    auth_check_selector: str = "",
    auth_check_timeout: int = 5000,
    auth_fallback_steps: list[dict] | None = None,
) -> str:
    """Convert PlaywrightStep list to executable Python code."""
    fallback_steps = auth_fallback_steps or []
    main_steps = steps or []
    has_main_ai_steps = any(step.get("action") == "aiStep" for step in main_steps)
    has_fallback_ai_steps = any(step.get("action") == "aiStep" for step in fallback_steps)
    has_ai_steps = has_main_ai_steps or has_fallback_ai_steps
    collect_cookies = capture_network or auth_enabled

    lines = [
        "import base64",
        "import json",
        "from urllib.request import Request, urlopen",
        "from playwright.sync_api import sync_playwright",
        "",
        "with sync_playwright() as p:",
        "    browser = p.chromium.launch(headless=headless)",
    ]

    if auth_enabled and auth_state and auth_state.get("mode") == "storageState":
        lines.append(
            f"    context = browser.new_context(storage_state={repr(auth_state['storageState'])})"
        )
    else:
        lines.append("    context = browser.new_context()")
        if auth_enabled and auth_state and auth_state.get("mode") == "cookies":
            lines.append(f"    context.add_cookies({repr(auth_state['cookies'])})")

    lines.extend(
        [
            "    page = context.new_page()",
            "    page.set_default_timeout(timeout_ms)",
            "    results = {}",
            "    screenshot = None",
            "",
        ]
    )

    if has_ai_steps:
        lines.append("    _ai_saved_steps = {}")
        if has_fallback_ai_steps:
            lines.append("    _ai_saved_fallback_steps = {}")
        lines.append("")

    if capture_network:
        lines.extend(
            [
                "    _captured_responses = []",
                "    _captured_cookies = {}",
                "",
                "    def _handle_response(response):",
                "        try:",
                "            hdrs = dict(response.headers)",
                "            for h in response.headers_array():",
                "                if h.get('name', '').lower() == 'set-cookie':",
                "                    pair = h['value'].split(';')[0]",
                "                    if '=' in pair:",
                "                        n, _, v = pair.partition('=')",
                "                        _captured_cookies[n.strip()] = v.strip()",
                '            content_type = hdrs.get("content-type", "")',
                '            if "application/json" not in content_type:',
                "                return",
                "            try:",
                "                body = response.json()",
                "            except Exception:",
                "                body = None",
                "            _captured_responses.insert(0, {",
                '                "url": response.url,',
                '                "status": response.status,',
                '                "headers": hdrs,',
                '                "body": body,',
                "            })",
                "            if len(_captured_responses) > 200:",
                "                _captured_responses.pop()",
                "        except Exception:",
                "            pass",
                "",
                '    page.on("response", _handle_response)',
                "",
            ]
        )

    if auth_enabled and main_steps:
        lines.extend(_indent_lines(_generate_step_lines(main_steps[0], 0, "_ai_saved_steps"), 4))
        lines.extend(
            [
                "    _auth_ok = False",
                "    try:",
                f"        page.locator({repr(auth_check_selector)}).first.wait_for(state='visible', timeout={int(auth_check_timeout)})",
                "        _auth_ok = True",
                "    except Exception:",
                "        _auth_ok = False",
                "",
            ]
        )

        if fallback_steps:
            lines.append("    if not _auth_ok:")
            for step_idx, step in enumerate(fallback_steps):
                lines.extend(
                    _indent_lines(
                        _generate_step_lines(step, step_idx, "_ai_saved_fallback_steps"),
                        8,
                    )
                )
            lines.extend(
                [
                    "        try:",
                    f"            page.locator({repr(auth_check_selector)}).first.wait_for(state='visible', timeout={int(auth_check_timeout)})",
                    "            _auth_ok = True",
                    "        except Exception:",
                    "            _auth_ok = False",
                    "",
                ]
            )

        lines.extend(
            [
                "    if not _auth_ok:",
                "        raise RuntimeError(",
                "            'Playwright auth bootstrap failed: authenticated selector was not found after cookie restore and fallback steps.'",
                "        )",
                "",
            ]
        )

        for step_idx, step in enumerate(main_steps[1:], start=1):
            lines.extend(_indent_lines(_generate_step_lines(step, step_idx, "_ai_saved_steps"), 4))
    else:
        for step_idx, step in enumerate(main_steps):
            lines.extend(_indent_lines(_generate_step_lines(step, step_idx, "_ai_saved_steps"), 4))

    if collect_cookies:
        lines.extend(
            [
                "    _ctx_cookies = context.cookies()",
                "    _cookies = [{k: v for k, v in c.items() if v is not None} for c in _ctx_cookies]",
            ]
        )
        if capture_network:
            lines.extend(
                [
                    "    for _cn, _cv in _captured_cookies.items():",
                    "        if not any(c.get('name') == _cn for c in _cookies):",
                    '            _cookies.append({"name": _cn, "value": _cv, "source": "header"})',
                ]
            )
        lines.extend(
            [
                "    _cookies = _cookies[:200]",
                "",
            ]
        )

    if capture_network:
        lines.extend(
            [
                "    try:",
                '        _localStorage = page.evaluate("() => { const o = {}; for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); o[k] = localStorage.getItem(k); } return o; }")',
                "    except Exception:",
                "        _localStorage = {}",
                "    try:",
                '        _sessionStorage = page.evaluate("() => { const o = {}; for (let i = 0; i < sessionStorage.length; i++) { const k = sessionStorage.key(i); o[k] = sessionStorage.getItem(k); } return o; }")',
                "    except Exception:",
                "        _sessionStorage = {}",
                "",
            ]
        )

    lines.append("    browser.close()")
    lines.append("")

    if capture_network:
        lines.append(
            'output = {"status": "ok", "results": results, "networkRequests": _captured_responses, "cookies": _cookies, "localStorage": _localStorage, "sessionStorage": _sessionStorage}'
        )
    elif collect_cookies:
        lines.append('output = {"status": "ok", "results": results, "cookies": _cookies}')
    else:
        lines.append('output = {"status": "ok", "results": results}')

    lines.extend(
        [
            "if screenshot is not None:",
            '    output["screenshot"] = base64.b64encode(screenshot).decode("utf-8") if isinstance(screenshot, bytes) else str(screenshot)',
        ]
    )
    if has_fallback_ai_steps:
        lines.extend(
            [
                "if _ai_saved_steps or _ai_saved_fallback_steps:",
                "    _save_steps = {}",
                "    if _ai_saved_steps:",
                '        _save_steps["main"] = _ai_saved_steps',
                "    if _ai_saved_fallback_steps:",
                '        _save_steps["fallback"] = _ai_saved_fallback_steps',
                '    output["saveSteps"] = _save_steps',
            ]
        )
    elif has_main_ai_steps:
        lines.append("if _ai_saved_steps:")
        lines.append('    output["saveSteps"] = _ai_saved_steps')
    lines.extend(["print(json.dumps(output))"])

    return "\n".join(lines)
