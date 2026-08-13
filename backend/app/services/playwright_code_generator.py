"""Generate Playwright Python code from step definitions."""

import inspect
import json
from urllib.error import HTTPError
from urllib.request import urlopen


def http_error_message(status_code: int, reason: str, body: str) -> str:
    """Turn an HTTP error body into a user-facing message.

    urllib's HTTPError string is typically ``HTTP Error 502: Bad Gateway``. FastAPI
    (and most LLM proxies) put the useful text in the JSON body ``detail``/``message``.
    """
    detail = (body or "").strip()
    if detail:
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            raw = parsed.get("detail", parsed.get("message", parsed.get("error")))
            if isinstance(raw, dict):
                message = raw.get("message")
                detail = str(message) if message else json.dumps(raw)
            elif raw is not None:
                detail = str(raw)
    return f"HTTP {status_code}: {detail or reason}"


def _heym_urlopen_json(req: object, timeout: float) -> object:
    """urlopen wrapper that surfaces the response body instead of a bare status phrase."""
    try:
        with urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as err:
        body = ""
        try:
            body = err.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        raise RuntimeError(http_error_message(err.code, str(err.reason), body)) from None


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


def _as_py_bool_literal(value: object) -> str:
    """Coerce a step field to the literal ``"True"`` or ``"False"``.

    Boolean-intended step fields (checkboxes) are interpolated directly into generated
    Python. Without coercion an attacker-controlled string such as
    ``(__import__("os").system("id"), False)[1]`` would be injected verbatim, turning the
    step-based path into code execution. This always returns a safe boolean literal.
    """
    if isinstance(value, str):
        return "True" if value.strip().lower() in ("true", "1", "yes", "on") else "False"
    return "True" if bool(value) else "False"


STEALTH_INIT_SCRIPT = r"""(() => {
  const nativeWebdriver = Object.getOwnPropertyDescriptor(Navigator.prototype, 'webdriver');
  if (nativeWebdriver && nativeWebdriver.get) {
    Object.defineProperty(Navigator.prototype, 'webdriver', {
      configurable: true,
      enumerable: nativeWebdriver.enumerable,
      get: new Proxy(nativeWebdriver.get, { apply: () => false }),
    });
  } else {
    Object.defineProperty(Navigator.prototype, 'webdriver', {
      configurable: true,
      enumerable: true,
      get: function () { return false; },
    });
  }

  window.chrome = window.chrome || {};
  window.chrome.runtime = window.chrome.runtime || {
    connect: function () {},
    sendMessage: function () {},
    id: undefined,
  };
  window.chrome.csi = window.chrome.csi || function () { return {}; };
  window.chrome.loadTimes = window.chrome.loadTimes || function () { return {}; };
  window.chrome.app = window.chrome.app || {
    isInstalled: false,
    InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
    RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' },
  };

  const ua = String(navigator.userAgent || '').replace(/HeadlessChrome/g, 'Chrome');
  const appVersion = ua.replace(/^Mozilla\//, '');
  Object.defineProperty(navigator, 'userAgent', { get: () => ua, configurable: true });
  Object.defineProperty(navigator, 'appVersion', { get: () => appVersion, configurable: true });
  Object.defineProperty(navigator, 'languages', { get: () => Object.freeze(['en-US', 'en']), configurable: true });

  const chromeMajor = (ua.match(/Chrome\/(\d+)/) || [])[1] || '145';
  const chromeFull = (ua.match(/Chrome\/([\d.]+)/) || [])[1] || chromeMajor;
  const brands = [
    { brand: 'Not/A)Brand', version: '8' },
    { brand: 'Chromium', version: chromeMajor },
    { brand: 'Google Chrome', version: chromeMajor },
  ];
  if (navigator.userAgentData) {
    try {
      Object.defineProperty(navigator.userAgentData, 'brands', { get: () => brands, configurable: true });
      const originalHighEntropy = navigator.userAgentData.getHighEntropyValues.bind(navigator.userAgentData);
      navigator.userAgentData.getHighEntropyValues = async (hints) => {
        const values = await originalHighEntropy(hints);
        values.brands = brands;
        values.fullVersionList = brands.map((b) => ({
          brand: b.brand,
          version: b.brand === 'Not/A)Brand' ? '10.0.0.0' : chromeFull,
        }));
        return values;
      };
    } catch (e) {}
  }

  const pdfEntries = [
    { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
    { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
    { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
    { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
    { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
  ];
  const pluginArray = Object.create(PluginArray.prototype);
  const mimeArray = Object.create(MimeTypeArray.prototype);
  const plugins = [];
  const mimes = [];
  pdfEntries.forEach((entry, index) => {
    const plugin = Object.create(Plugin.prototype);
    const mime = Object.create(MimeType.prototype);
    Object.defineProperties(mime, {
      type: { enumerable: true, value: 'application/pdf' },
      suffixes: { enumerable: true, value: 'pdf' },
      description: { enumerable: true, value: entry.description },
      enabledPlugin: { enumerable: true, get: () => plugin },
    });
    Object.defineProperties(plugin, {
      name: { enumerable: true, value: entry.name },
      filename: { enumerable: true, value: entry.filename },
      description: { enumerable: true, value: entry.description },
      length: { value: 1 },
      0: { enumerable: true, value: mime },
    });
    plugin.item = function (i) { return i === 0 ? mime : null; };
    plugin.namedItem = function (type) { return type === 'application/pdf' ? mime : null; };
    plugins.push(plugin);
    if (index === 0) mimes.push(mime);
    Object.defineProperty(pluginArray, index, { enumerable: true, value: plugin });
    Object.defineProperty(pluginArray, entry.name, { value: plugin });
  });
  Object.defineProperty(pluginArray, 'length', { value: plugins.length });
  pluginArray.item = function (i) { return this[i] || null; };
  pluginArray.namedItem = function (name) { return plugins.find((p) => p.name === name) || null; };
  pluginArray.refresh = function () {};
  Object.defineProperty(mimeArray, 0, { enumerable: true, value: mimes[0] });
  Object.defineProperty(mimeArray, 'application/pdf', { value: mimes[0] });
  Object.defineProperty(mimeArray, 'length', { value: 1 });
  mimeArray.item = function (i) { return this[i] || null; };
  mimeArray.namedItem = function (type) { return type === 'application/pdf' ? mimes[0] : null; };
  Object.defineProperty(navigator, 'plugins', { get: () => pluginArray, configurable: true });
  Object.defineProperty(navigator, 'mimeTypes', { get: () => mimeArray, configurable: true });

  try {
    Object.defineProperty(Notification, 'permission', { get: () => 'default', configurable: true });
  } catch (e) {}
  const originalQuery = window.navigator.permissions && window.navigator.permissions.query;
  if (originalQuery) {
    window.navigator.permissions.query = function (parameters) {
      if (parameters && parameters.name === 'notifications') {
        return Promise.resolve({ state: 'prompt', onchange: null, name: 'notifications' });
      }
      return originalQuery.call(window.navigator.permissions, parameters);
    };
  }

  const softwareGpu = /swiftshader|llvmpipe|softpipe|lavapipe/i;
  const linuxArm = /Linux/.test(ua) && /aarch64|arm64/i.test(ua);
  const linuxWebglVendor = linuxArm ? 'Google Inc. (ARM)' : 'Google Inc. (Intel)';
  const linuxWebglRenderer = linuxArm
    ? 'ANGLE (ARM, Mali-G78 MC14, OpenGL ES 3.2)'
    : 'ANGLE (Intel, Mesa Intel(R) Graphics (RPL-U), OpenGL 4.6)';
  const replaceSoftwareRenderer = (ctxProto) => {
    if (!ctxProto || !ctxProto.getParameter) return;
    const original = ctxProto.getParameter;
    ctxProto.getParameter = function (param) {
      const value = original.call(this, param);
      if (param !== 0x9245 && param !== 0x9246) return value;
      const renderer = String(original.call(this, 0x9246) || value || '');
      if (!softwareGpu.test(renderer) && !softwareGpu.test(String(value || ''))) return value;
      return param === 0x9245 ? linuxWebglVendor : linuxWebglRenderer;
    };
  };
  if (typeof WebGLRenderingContext !== 'undefined') replaceSoftwareRenderer(WebGLRenderingContext.prototype);
  if (typeof WebGL2RenderingContext !== 'undefined') replaceSoftwareRenderer(WebGL2RenderingContext.prototype);

  try {
    const originalDebug = console.debug.bind(console);
    console.debug = function (...args) {
      if (args.length === 1 && args[0] instanceof Error) return;
      return originalDebug(...args);
    };
  } catch (e) {}

  const originalCreateElement = Document.prototype.createElement;
  Document.prototype.createElement = function () {
    const el = originalCreateElement.apply(this, arguments);
    if (el && el.tagName === 'IFRAME') {
      el.addEventListener('load', () => {
        try {
          if (el.contentWindow && !el.contentWindow.chrome) {
            el.contentWindow.chrome = window.chrome;
          }
        } catch (err) {}
      });
    }
    return el;
  };
})();"""


def _stealth_user_agent(browser: object) -> str:
    """Build a Chrome UA matching the launched browser version without HeadlessChrome."""
    import platform

    ver = str(getattr(browser, "version", "") or "145.0.0.0")
    system = platform.system()
    if system == "Darwin":
        os_token = "(Macintosh; Intel Mac OS X 10_15_7)"
    elif system == "Windows":
        os_token = "(Windows NT 10.0; Win64; x64)"
    else:
        linux_arch = "aarch64" if platform.machine().lower() in {"arm64", "aarch64"} else "x86_64"
        os_token = f"(X11; Linux {linux_arch})"
    return (
        f"Mozilla/5.0 {os_token} AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{ver} Safari/537.36"
    )


def _stealth_chromium_launch_kwargs(headless: object) -> dict:
    """Launch Chromium without automation flags; use a host GPU only when one exists.

    Production Playwright runs in a Linux Docker sandbox with no display and no GPU.
    Do not request Metal/D3D, ignore ``--disable-gpu``, or flip ``headless=False`` there.
    """
    import platform

    args = [
        "--disable-blink-features=AutomationControlled",
        "--exclude-switches=enable-automation",
    ]
    ignore_default_args = ["--enable-automation"]
    system = platform.system()
    if system == "Linux":
        args.append("--no-sandbox")
        return {
            "headless": bool(headless),
            "args": args,
            "ignore_default_args": ignore_default_args,
        }

    args.extend(
        [
            "--enable-gpu",
            "--ignore-gpu-blocklist",
            "--use-gl=angle",
        ]
    )
    if system == "Darwin":
        args.append("--use-angle=metal")
    elif system == "Windows":
        args.append("--use-angle=d3d11")
    ignore_default_args.append("--disable-gpu")
    if headless:
        args.append("--headless=new")
    return {
        "headless": False,
        "args": args,
        "ignore_default_args": ignore_default_args,
    }


def _apply_stealth_user_agent_override(page: object, browser: object) -> None:
    """Keep Chrome's frozen UA while Client Hints report the host OS and CPU."""
    import platform

    ua = _stealth_user_agent(browser)
    ver = str(getattr(browser, "version", "") or "145.0.0.0")
    major = ver.split(".")[0]
    machine = platform.machine().lower()
    architecture = "arm" if machine in {"arm64", "aarch64"} else "x86"
    system = platform.system()
    if system == "Darwin":
        platform_name = "macOS"
        navigator_platform = "MacIntel"
        platform_version = platform.mac_ver()[0] or "15.6.1"
        if platform_version.count(".") == 1:
            platform_version = f"{platform_version}.0"
    elif system == "Windows":
        platform_name = "Windows"
        navigator_platform = "Win32"
        platform_version = "19.0.0"
    else:
        linux_arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
        platform_name = "Linux"
        navigator_platform = f"Linux {linux_arch}"
        platform_version = "6.8.0"

    brands = [
        {"brand": "Not/A)Brand", "version": "8"},
        {"brand": "Chromium", "version": major},
        {"brand": "Google Chrome", "version": major},
    ]
    session = page.context.new_cdp_session(page)
    session.send(
        "Emulation.setUserAgentOverride",
        {
            "userAgent": ua,
            "acceptLanguage": "en-US,en",
            "platform": navigator_platform,
            "userAgentMetadata": {
                "brands": brands,
                "fullVersionList": [
                    {"brand": "Not/A)Brand", "version": "10.0.0.0"},
                    {"brand": "Chromium", "version": ver},
                    {"brand": "Google Chrome", "version": ver},
                ],
                "fullVersion": ver,
                "platform": platform_name,
                "platformVersion": platform_version,
                "architecture": architecture,
                "model": "",
                "mobile": False,
                "bitness": "64",
                "wow64": False,
            },
        },
    )


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
        ai_log = _as_py_bool_literal(step.get("logStepsToConsole", False))
        ai_save = _as_py_bool_literal(step.get("saveStepsForFuture", False))
        ai_auto_heal = _as_py_bool_literal(step.get("autoHealMode", False))
        ai_screenshot = _as_py_bool_literal(step.get("sendScreenshot", False))
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
                f"_ai_result = _heym_urlopen_json(_req, {ai_timeout_sec})",
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
                f"                    _heal_result = _heym_urlopen_json(_heal_req, {ai_timeout_sec})",
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
    stealth: object = False,
) -> str:
    """Convert PlaywrightStep list to executable Python code."""
    fallback_steps = auth_fallback_steps or []
    main_steps = steps or []
    has_main_ai_steps = any(step.get("action") == "aiStep" for step in main_steps)
    has_fallback_ai_steps = any(step.get("action") == "aiStep" for step in fallback_steps)
    has_ai_steps = has_main_ai_steps or has_fallback_ai_steps
    collect_cookies = capture_network or auth_enabled
    stealth_enabled = _as_py_bool_literal(stealth) == "True"

    lines = [
        "import base64",
        "import json",
        "from urllib.error import HTTPError",
        "from urllib.request import Request, urlopen",
        "from playwright.sync_api import sync_playwright",
        "",
    ]
    if has_ai_steps:
        lines.extend(
            [
                inspect.getsource(http_error_message).strip(),
                "",
                inspect.getsource(_heym_urlopen_json).strip(),
                "",
            ]
        )
    if stealth_enabled:
        lines.extend(
            [
                inspect.getsource(_stealth_user_agent).strip(),
                "",
                inspect.getsource(_stealth_chromium_launch_kwargs).strip(),
                "",
                inspect.getsource(_apply_stealth_user_agent_override).strip(),
                "",
            ]
        )
    lines.append("with sync_playwright() as p:")
    if stealth_enabled:
        lines.append("    browser = p.chromium.launch(**_stealth_chromium_launch_kwargs(headless))")
    else:
        lines.append("    browser = p.chromium.launch(headless=headless)")

    context_args: list[str] = []
    if stealth_enabled:
        context_args.append("user_agent=_stealth_user_agent(browser)")
        context_args.append('locale="en-US"')
        context_args.append('viewport={"width": 1280, "height": 720}')
    if auth_enabled and auth_state and auth_state.get("mode") == "storageState":
        context_args.append(f"storage_state={repr(auth_state['storageState'])}")
    if context_args:
        lines.append(f"    context = browser.new_context({', '.join(context_args)})")
    else:
        lines.append("    context = browser.new_context()")
    if auth_enabled and auth_state and auth_state.get("mode") == "cookies":
        lines.append(f"    context.add_cookies({repr(auth_state['cookies'])})")
    if stealth_enabled:
        lines.append(f"    context.add_init_script({repr(STEALTH_INIT_SCRIPT)})")

    lines.append("    page = context.new_page()")
    if stealth_enabled:
        lines.append("    _apply_stealth_user_agent_override(page, browser)")
    lines.extend(
        [
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
