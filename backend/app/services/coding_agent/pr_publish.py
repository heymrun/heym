"""Shared coding-agent git/GitHub helpers used by the Codex and OpenCode Go runners.

These are pure functions: the execution seam (a ``git_output`` callable, a ``GitHubService``
instance) is passed in by the caller. This lets both runners share the git-URL/owner-repo parsing,
commit-message shaping, and PR-screenshot upload logic while each runner keeps its own subprocess
seam (so their unit tests can mock the seam on the runner instance).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from app.services.github_service import GitHubService

logger = logging.getLogger(__name__)

# --- PR screenshot constants (shared) ---
PR_SCREENSHOT_SUFFIXES: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
PR_SCREENSHOT_MAX_FILES = 5
PR_SCREENSHOT_MAX_BYTES = 5 * 1024 * 1024
PR_SCREENSHOT_CONTENT_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

# Prompt clause shared by every coding-agent runner: the task prompt is private input, so it must
# never be echoed into anything Heym publishes to GitHub (PR title, PR body, commit message).
PR_CONTENT_POLICY = (
    "Critical pull request policy: the task prompt is PRIVATE. Never quote, paraphrase, summarize, "
    "transform, or reference the task instructions, your reasoning, logs, or tool output in the "
    "pull request title, the pull request description, or the commit message. Only two things may "
    "be published to GitHub: a `## Change Summary` section describing what the code change does, "
    "and a `## Screenshots` section when applicable. Derive the title from the change summary "
    "alone. Never add sections such as `## Task`, `## Prompt`, `## Instructions`, or "
    "`## Original Request`."
)

# Section headings that restate the private task prompt instead of describing the change.
_PROMPT_ECHO_HEADINGS: frozenset[str] = frozenset(
    {
        "task",
        "tasks",
        "task prompt",
        "task description",
        "task details",
        "original task",
        "original request",
        "original prompt",
        "prompt",
        "instructions",
        "instruction",
        "request",
        "user request",
        "user prompt",
        "user instructions",
    }
)
_HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
# Below this length a paragraph is too generic for a verbatim prompt match to mean anything.
_MIN_PROMPT_ECHO_CHARS = 24


def clone_url_with_token(repository_url: str, github_config: dict) -> str:
    """Embed a GitHub token into an https clone URL (as ``x-access-token``)."""
    token = str(github_config.get("api_key") or "").strip()
    if not token:
        return repository_url
    parsed = urlparse(repository_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return repository_url
    if "@" in parsed.netloc:
        return repository_url
    netloc = f"x-access-token:{quote(token, safe='')}@{parsed.netloc}"
    return urlunparse(parsed._replace(netloc=netloc))


def parse_github_owner_repo(repository_url: str) -> tuple[str, str]:
    parsed = urlparse(repository_url)
    path = parsed.path.removesuffix(".git").strip("/")
    parts = [part for part in path.split("/") if part]
    if len(parts) < 2:
        raise ValueError("Repository URL must include owner and repository")
    return parts[-2], parts[-1]


def mask_sensitive(text: str, values: list[object]) -> str:
    masked = text
    for value in values:
        secret = str(value or "")
        if secret:
            masked = masked.replace(secret, "[masked]")
    return masked


def git_identity_args(name: str, email: str) -> list[str]:
    """Return ``git -c`` args so commit/rebase works without a local gitconfig.

    Dockerized coding-agent workspaces run as root with no ``user.name`` /
    ``user.email``. Commits and ``git pull --rebase`` both need an identity;
    pass these args on those commands instead of mutating repo config.
    """
    return ["-c", f"user.name={name}", "-c", f"user.email={email}"]


# Placeholder agent closings that must never become a GitHub PR/commit subject.
_MEANINGLESS_TITLE_RE = re.compile(
    r"^(?:"
    r"done|ok|okay|fixed|completed|finished|ready|success|all done|lgtm|wip|"
    r"changes?(?:\s+are)?\s+done|task(?:\s+is)?\s+complete(?:d)?"
    r")[.!]?\s*$",
    re.IGNORECASE,
)
_PR_TITLE_LINE_RE = re.compile(r"(?im)^\s*PR_TITLE:\s*(.+?)\s*$")

# Running commentary an agent emits *between* steps ("Both pass. Let me do a final review:").
# It reads like prose but describes the agent's own process, not the change, so publishing it
# leaks reasoning. Matched as a prefix, since narration announces itself in the opening clause.
_INTERJECTIONS = r"ok(?:ay)?|perfect|great|excellent|good|alright|nice|awesome|cool|now"
_NARRATION_PREFIX_RE = re.compile(
    rf"^(?:(?:{_INTERJECTIONS})[,!.]?\s+)*"
    r"(?:"
    r"let(?:'|’)?s\b|let me\b|"
    r"i(?:'|’)?(?:ll|m|ve)\b|i (?:will|am|have|need|should|can)\b|"
    r"next[,:]?\s+i\b|first[,:]\s|"
    r"(?:both|all|everything|they|it|the|tests?|checks?|specs?)\s+"
    r"(?:(?:tests?|checks?|specs?|suites?|builds?)\s+)?(?:now\s+)?"
    r"(?:pass(?:es|ed)?|look|looks|works?|worked|is correct|are correct|is right)\b"
    r")",
    re.IGNORECASE,
)
# "Good, …" / "Perfect! …" — an interjection about the agent's own progress, not a change.
_INTERJECTION_OPENER_RE = re.compile(rf"^(?:{_INTERJECTIONS})\s*[,!.]", re.IGNORECASE)
_CHANGE_SUMMARY_HEADING = "change summary"


def normalize_title_candidate(text: str) -> str:
    """Collapse whitespace and strip a leading ``PR_TITLE:`` label if present."""
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    cleaned = re.sub(r"^PR_TITLE:\s*", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.strip("\"'`")


def is_agent_narration(text: str) -> bool:
    """True when the text is the agent narrating its own process rather than the change.

    Three signals, all observed on real agent pull requests: a step announcement
    ("Let me…", "I'll…"), an interjection about its own progress ("Good, …"), and a trailing
    colon, which introduces the next step and never ends a change description.
    """
    collapsed = _collapse(text)
    if not collapsed:
        return False
    if collapsed.endswith(":"):
        return True
    if _INTERJECTION_OPENER_RE.match(collapsed) is not None:
        return True
    return _NARRATION_PREFIX_RE.match(collapsed) is not None


def is_meaningful_commit_title(title: str) -> bool:
    """Return False for empty/short/placeholder/narration titles such as ``Done.``."""
    normalized = normalize_title_candidate(title)
    if len(normalized) < 8:
        return False
    if _MEANINGLESS_TITLE_RE.match(normalized) is not None:
        return False
    return not is_agent_narration(normalized)


def extract_change_summary_section(text: str) -> str:
    """Return the body of the last ``## Change Summary`` section, or ``""`` when absent.

    The runner prompts ask agents to put the publishable description under this heading, so
    honouring it keeps step-by-step narration around it out of the pull request.
    """
    kept: list[str] = []
    section_level = 0
    for line in str(text or "").splitlines():
        match = _HEADING_RE.match(line)
        if match is not None:
            level = len(match.group(1))
            if _normalize_heading(match.group(2)) == _CHANGE_SUMMARY_HEADING:
                section_level = level
                kept = []
                continue
            if section_level and level <= section_level:
                section_level = 0
        if section_level:
            kept.append(line)
    return "\n".join(kept).strip()


def extract_pr_title_line(summary: str) -> tuple[str, str]:
    """Parse a trailing ``PR_TITLE: …`` line from an agent summary.

    Returns ``(title, summary_without_title_line)``. When no line is present the
    original summary is returned unchanged and the title is empty.
    """
    text = str(summary or "")
    match = None
    for candidate in _PR_TITLE_LINE_RE.finditer(text):
        match = candidate
    if match is None:
        return "", text
    title = normalize_title_candidate(match.group(1))
    cleaned = (text[: match.start()] + text[match.end() :]).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return title, cleaned


def commit_title(pull_request_title: str, summary: str, *, fallback: str) -> str:
    """Prefer a meaningful dedicated PR title; else a summary sentence; else ``fallback``.

    Skips placeholder subjects such as ``Done.`` that coding agents often emit as
    the first sentence of an otherwise useful summary.
    """
    extracted_title, summary_without_title = extract_pr_title_line(summary)
    candidates: list[str] = [
        normalize_title_candidate(pull_request_title),
        extracted_title,
    ]
    normalized = re.sub(r"\s+", " ", str(summary_without_title or "")).strip()
    if normalized:
        candidates.extend(re.split(r"(?<=[.!?])\s+", normalized))
    for candidate in candidates:
        if is_meaningful_commit_title(candidate):
            return normalize_title_candidate(candidate)
    return fallback


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _normalize_heading(text: str) -> str:
    """Lowercase a markdown heading and drop emphasis/punctuation so it can be matched."""
    cleaned = _collapse(text).strip("*_`").strip()
    return cleaned.rstrip(":.").strip().lower()


def strip_prompt_echo_sections(body: str) -> str:
    """Drop markdown sections whose heading restates the private task prompt.

    A prompt-echo heading removes everything until the next heading of the same or a
    higher level, so nested subsections of the echoed block go with it.
    """
    kept: list[str] = []
    skip_level = 0
    for line in str(body or "").splitlines():
        match = _HEADING_RE.match(line)
        if match is not None:
            level = len(match.group(1))
            if skip_level and level <= skip_level:
                skip_level = 0
            if _normalize_heading(match.group(2)) in _PROMPT_ECHO_HEADINGS:
                skip_level = level
                continue
        if skip_level:
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def strip_prompt_echo_blocks(body: str, task_prompt: str) -> str:
    """Drop paragraphs that are verbatim copies of (part of) the task prompt."""
    prompt = _collapse(task_prompt).lower()
    text = str(body or "").strip()
    if len(prompt) < _MIN_PROMPT_ECHO_CHARS or not text:
        return text
    kept: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        normalized = _collapse(block).lower()
        if len(normalized) >= _MIN_PROMPT_ECHO_CHARS and normalized in prompt:
            continue
        if block.strip():
            kept.append(block.strip())
    return "\n\n".join(kept).strip()


def publishable_summary(summary: str, *, placeholder: str = "") -> str:
    """The agent's description of the change, or ``""`` when it only narrated its own process.

    Runners keep the raw ``summary`` on the node output so a run stays debuggable in Heym; this
    narrower value is the only one allowed into a commit message or pull request.
    """
    text = str(summary or "").strip()
    if not text or (placeholder and text == placeholder):
        return ""
    return "" if is_agent_narration(text) else text


def changed_files_body(changed_files: list[str], *, agent: str, limit: int = 20) -> str:
    """Last-resort PR body: the diff's own file list, which is always safe to publish."""
    if not changed_files:
        return ""
    shown = changed_files[:limit]
    lines = [f"- `{path}`" for path in shown]
    remaining = len(changed_files) - len(shown)
    if remaining > 0:
        lines.append(f"- …and {remaining} more file(s)")
    listing = "\n".join(lines)
    return (
        "## Change Summary\n\n"
        f"{agent} did not return a change summary. Files changed in this pull request:\n\n"
        f"{listing}"
    )


def redact_task_prompt(body: str, task_prompt: str) -> str:
    """Remove task-prompt echoes from text that is about to be published to GitHub.

    Backstop for ``PR_CONTENT_POLICY``: prompts are guidance, this is enforcement. Only the
    agent's own description of the change (and screenshots) survives.
    """
    return strip_prompt_echo_blocks(strip_prompt_echo_sections(body), task_prompt)


def commit_body(summary: str, validation: str) -> str:
    """Full commit body so the message is not lost when the subject is truncated."""
    parts: list[str] = []
    summary_text = str(summary or "").strip()
    if summary_text:
        parts.append(summary_text)
    validation_text = str(validation or "").strip()
    if validation_text:
        parts.append(f"Validation:\n{validation_text}")
    return "\n\n".join(parts)


def pr_number_from_url(url: str) -> int | None:
    match = re.search(r"/pull/(\d+)(?:/|$)", str(url or ""))
    if not match:
        return None
    return int(match.group(1))


def resolve_update_existing_pr_branch(
    gh: GitHubService,
    owner: str,
    repo: str,
    *,
    base_branch: str,
    configured_branch: str,
) -> str:
    """Head branch to reuse for ``update_existing_pr`` so a re-run updates *this task's* existing
    open pull request instead of opening a new one.

    Every candidate has to be tied back to ``configured_branch``. An earlier version adopted the
    token account's most-recently-updated open PR whenever the branch did not match, which made
    concurrent board cards land on whichever pull request happened to be touched last: one agent
    pushed its alerts work onto an unrelated dialog PR. Resolution order:

    * an open PR whose head already equals ``configured_branch`` wins (explicit targeting);
    * a branch that names a pull request (``reuse-branch-from-pr-401``) resolves to that PR's head;
    * an open PR whose head carries the same task slug, ignoring the agent prefix, is adopted, so
      the same card re-run through a different agent keeps one pull request;
    * otherwise ``configured_branch`` is returned unchanged (a fresh PR is created downstream).

    Adoption is limited to the token account's own pull requests. Best-effort: any GitHub error
    falls back to ``configured_branch`` (never raises).
    """
    try:
        pulls = gh.list_pull_requests(owner, repo, state="open", per_page=100)
    except Exception:  # noqa: BLE001 - discovery is best-effort; fall back to the configured branch
        return configured_branch

    to_base = [pr for pr in pulls if _pr_base_ref(pr) == base_branch]
    for pull in to_base:
        if _pr_head_ref(pull) == configured_branch:
            return configured_branch

    author = _authenticated_login(gh)
    candidates = [pull for pull in to_base if _pr_author_login(pull) == author] if author else []

    referenced = _referenced_pr_number(configured_branch)
    if referenced is not None:
        for pull in candidates:
            if pull.get("number") == referenced:
                return _pr_head_ref(pull) or configured_branch

    slug = _branch_task_slug(configured_branch)
    if slug:
        matching = [pull for pull in candidates if _branch_task_slug(_pr_head_ref(pull)) == slug]
        if matching:
            target = max(matching, key=lambda pull: str(pull.get("updated_at") or ""))
            return _pr_head_ref(target) or configured_branch

    return configured_branch


def _referenced_pr_number(branch: str) -> int | None:
    """PR number a placeholder branch such as ``reuse-branch-from-pr-401`` points at."""
    match = re.search(r"(?:^|[-_/])pr[-_]?(\d+)(?:$|[-_/])", str(branch or ""), re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _branch_task_slug(branch: str) -> str:
    """``opencode/alerts-dialog-improvements`` and ``codex/alerts_dialog_improvements`` share a
    slug, so one card keeps one pull request across agents. Unrelated tasks never collide."""
    tail = str(branch or "").strip().strip("/").split("/")[-1].lower()
    return re.sub(r"[^a-z0-9]+", "-", tail).strip("-")


def _pr_head_ref(pull: dict) -> str:
    return str((pull.get("head") or {}).get("ref") or "")


def _pr_base_ref(pull: dict) -> str:
    return str((pull.get("base") or {}).get("ref") or "")


def _pr_author_login(pull: dict) -> str:
    return str((pull.get("user") or {}).get("login") or "")


def _authenticated_login(gh: GitHubService) -> str:
    try:
        user = gh.get_authenticated_user()
    except Exception:  # noqa: BLE001 - some tokens can't read /user; fall back to count-based scope
        return ""
    return str((user or {}).get("login") or "").strip()


# --- finishing pass / screenshot completeness (shared) ---
# A coding agent sometimes ends its turn mid-task (e.g. "…Now let me take a screenshot"), so the
# run finalizes before the screenshot is captured and with only narration for a summary. When that
# happens the runner does ONE more pass with this preamble, in the same workspace, to finish.
FINISHING_PASS_PREAMBLE = (
    "You ended your previous turn before finishing. The repository already contains your "
    "in-progress changes on disk — do NOT redo or re-plan that work, and make no further code "
    "changes except what is strictly required to capture a screenshot. Complete any step you "
    "announced but did not perform: for a UI/frontend change, capture at least one PNG screenshot "
    "of the result under a gitignored path such as `frontend/.e2e-artifacts/` (Heym attaches it to "
    "the pull request; do not commit the image). Then return your final report describing what "
    "changed. Never end by announcing a further step (for example 'Now let me take a screenshot')."
)

# Frontend/visual files a reviewer would expect a screenshot for.
_UI_VISUAL_SUFFIXES: frozenset[str] = frozenset(
    {".vue", ".tsx", ".jsx", ".svelte", ".css", ".scss", ".sass", ".less", ".html"}
)
_UI_SCRIPT_SUFFIXES: frozenset[str] = frozenset({".ts", ".js"})
_UI_PATH_HINTS: tuple[str, ...] = (
    "frontend/",
    "/components/",
    "/views/",
    "/pages/",
    "src/components/",
    "src/views/",
)
_MISSING_SCREENSHOT_NOTE = (
    "> ⚠️ This pull request changes UI/frontend files, but the coding agent did not "
    "capture a screenshot. Add one manually if a visual review is needed."
)


def changed_files_touch_ui(changed_files: list[str]) -> bool:
    """True when the diff touches frontend/visual files a reviewer would expect a screenshot for."""
    for raw in changed_files or []:
        path = str(raw or "").strip().replace("\\", "/").lower()
        name = path.rsplit("/", 1)[-1]
        suffix = path[path.rfind(".") :] if "." in name else ""
        if suffix in _UI_VISUAL_SUFFIXES:
            return True
        if suffix in _UI_SCRIPT_SUFFIXES and any(hint in path for hint in _UI_PATH_HINTS):
            return True
    return False


def needs_finishing_pass(
    *,
    will_publish: bool,
    changed_files: list[str],
    publish_summary: str,
    ui_change: bool,
    has_screenshots: bool,
) -> bool:
    """Whether to run one more agent pass before publishing.

    Trigger when there is work to publish but the agent left no publishable summary (it stopped
    mid-report), or a UI change shipped without a screenshot (it stopped before capturing one).
    """
    if not will_publish or not changed_files:
        return False
    if not str(publish_summary or "").strip():
        return True
    return bool(ui_change) and not bool(has_screenshots)


def note_missing_ui_screenshot(body: str) -> str:
    """Append a visible ``## Screenshots`` note when a UI change shipped without a screenshot.

    No-op when the body already has a Screenshots section (screenshots were attached).
    """
    text = (body or "").strip()
    if re.search(r"(?im)^\s*##\s+screenshots?\b", text):
        return text + ("\n" if text else "")
    section = f"## Screenshots\n\n{_MISSING_SCREENSHOT_NOTE}"
    return (f"{text}\n\n{section}" if text else section) + "\n"


def sanitize_asset_slug(head: str) -> str:
    """Sanitize a branch/head ref into a stable release-asset prefix.

    Keyed on the branch (not the PR number) so screenshots can be uploaded and embedded *before*
    the pull request exists — the PR then opens already containing them — and so re-runs on the
    same branch replace the same-named asset instead of piling up duplicates.
    """
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(head or "")).strip("-._")
    return slug or "pr"


def release_asset_name(path: Path, slug: str, index: int) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-._") or "screenshot"
    suffix = path.suffix.lower() if path.suffix.lower() in PR_SCREENSHOT_SUFFIXES else ".png"
    clean_slug = sanitize_asset_slug(slug)
    if index == 0:
        return f"{clean_slug}-{stem}{suffix}"
    return f"{clean_slug}-{stem}-{index}{suffix}"


def inject_screenshot_markdown(body: str, images: list[tuple[str, str]]) -> str:
    section = "## Screenshots\n\n" + "\n\n".join(f"![{name}]({url})" for name, url in images)
    text = (body or "").strip()
    if not text:
        return section + "\n"
    pattern = re.compile(r"## Screenshots?\b.*?(?=\n## |\Z)", re.IGNORECASE | re.DOTALL)
    if pattern.search(text):
        return pattern.sub(section + "\n\n", text).rstrip() + "\n"
    return text + "\n\n" + section + "\n"


def discover_pr_screenshots(
    workspace: Path, git_output: Callable[[list[str], Path], str]
) -> list[Path]:
    """Find local UI screenshots left on disk (gitignored / untracked only)."""
    root = workspace.resolve()
    logger.debug("Discovering PR screenshots under %s", root)
    tracked = {
        line.strip().replace("\\", "/")
        for line in git_output(["git", "ls-files"], workspace).splitlines()
        if line.strip()
    }
    candidates: list[Path] = []
    seen: set[Path] = set()

    def consider(path: Path) -> None:
        if not path.is_file() or path in seen:
            return
        suffix = path.suffix.lower()
        if suffix not in PR_SCREENSHOT_SUFFIXES:
            return
        try:
            resolved = path.resolve()
            relative = resolved.relative_to(root).as_posix()
        except ValueError:
            return
        if relative in tracked:
            logger.debug("Skipping tracked screenshot: %s", relative)
            return
        try:
            size = path.stat().st_size
            if size > PR_SCREENSHOT_MAX_BYTES:
                logger.debug("Skipping oversized screenshot: %s (%d bytes)", relative, size)
                return
        except OSError:
            return
        logger.debug("Found screenshot: %s", relative)
        seen.add(path)
        candidates.append(resolved)

    artifact_dirs = [
        root / "frontend" / ".e2e-artifacts",
        root / ".e2e-artifacts",
        root / "screenshots",
        root / "frontend" / "screenshots",
        root / "e2e" / "screenshots",
        root / "test" / "screenshots",
        root / "tests" / "screenshots",
        root / "artifacts",
        root / "frontend" / "artifacts",
    ]
    for artifact_dir in artifact_dirs:
        if artifact_dir.is_dir():
            logger.debug("Scanning screenshot directory: %s", artifact_dir)
            for path in artifact_dir.rglob("*"):
                consider(path)

    # Case-insensitive search for files and directories whose names contain "screenshot".
    # Limit depth to avoid expensive full repository traversal.
    for depth in range(1, 5):
        pattern = "/".join(["*"] * depth)
        for path in root.glob(pattern):
            if "screenshot" in path.name.lower():
                consider(path)

    candidates.sort(key=lambda item: item.as_posix())
    selected = candidates[:PR_SCREENSHOT_MAX_FILES]
    logger.info(
        "Discovered %d PR screenshot candidate(s) in %s (returning %d)",
        len(candidates),
        root,
        len(selected),
    )
    return selected


def ensure_pr_screenshot_release(
    gh: GitHubService,
    owner: str,
    repo: str,
    target_commitish: str,
    *,
    release_tag: str,
    release_name: str,
    release_body: str,
) -> dict:
    """Return the shared screenshot bucket release, creating it once if missing."""
    try:
        return gh.get_release_by_tag(owner, repo, release_tag)
    except ValueError:
        return gh.create_release(
            owner,
            repo,
            release_tag,
            name=release_name,
            body=release_body,
            target_commitish=target_commitish or None,
            draft=False,
            prerelease=True,
        )


def upload_and_inject_screenshots(
    gh: GitHubService,
    *,
    screenshots: list[Path],
    owner: str,
    repo: str,
    base_branch: str,
    asset_slug: str,
    base_body: str,
    release_tag: str,
    release_name: str,
    release_body: str,
) -> str | None:
    """Upload screenshots as release assets and return a PR body with them embedded (or None)."""
    if not screenshots:
        return None
    release = ensure_pr_screenshot_release(
        gh,
        owner,
        repo,
        base_branch,
        release_tag=release_tag,
        release_name=release_name,
        release_body=release_body,
    )
    release_id = int(release["id"])
    upload_url = str(release.get("upload_url") or "") or None
    existing_assets = {
        str(asset.get("name") or ""): int(asset["id"])
        for asset in (release.get("assets") or [])
        if isinstance(asset, dict) and asset.get("id") is not None
    }
    uploaded: list[tuple[str, str]] = []
    for index, shot in enumerate(screenshots):
        asset_name = release_asset_name(shot, asset_slug, index)
        existing_id = existing_assets.get(asset_name)
        if existing_id is not None:
            gh.delete_release_asset(owner, repo, existing_id)
        content_type = PR_SCREENSHOT_CONTENT_TYPES.get(
            shot.suffix.lower(), "application/octet-stream"
        )
        asset = gh.upload_release_asset(
            owner,
            repo,
            release_id,
            str(shot),
            name=asset_name,
            content_type=content_type,
            upload_url=upload_url,
        )
        download = str(asset.get("browser_download_url") or "").strip()
        if download:
            uploaded.append((asset_name, download))
    if not uploaded:
        return None
    return inject_screenshot_markdown(base_body, uploaded)
