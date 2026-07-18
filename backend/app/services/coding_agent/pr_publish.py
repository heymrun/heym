"""Shared coding-agent git/GitHub helpers used by the Codex and OpenCode Go runners.

These are pure functions: the execution seam (a ``git_output`` callable, a ``GitHubService``
instance) is passed in by the caller. This lets both runners share the git-URL/owner-repo parsing,
commit-message shaping, and PR-screenshot upload logic while each runner keeps its own subprocess
seam (so their unit tests can mock the seam on the runner instance).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from app.services.github_service import GitHubService

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


def commit_title(pull_request_title: str, summary: str, *, fallback: str) -> str:
    """Prefer the dedicated PR title; else the first sentence of the summary; else ``fallback``."""
    title = re.sub(r"\s+", " ", str(pull_request_title or "")).strip()
    if title:
        return title
    normalized = re.sub(r"\s+", " ", str(summary or "")).strip()
    if not normalized:
        return fallback
    return re.split(r"(?<=[.!?])\s", normalized, maxsplit=1)[0]


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


def release_asset_name(path: Path, pr_number: int, index: int) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem).strip("-._") or "screenshot"
    suffix = path.suffix.lower() if path.suffix.lower() in PR_SCREENSHOT_SUFFIXES else ".png"
    if index == 0:
        return f"pr-{pr_number}-{stem}{suffix}"
    return f"pr-{pr_number}-{stem}-{index}{suffix}"


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
            return
        try:
            if path.stat().st_size > PR_SCREENSHOT_MAX_BYTES:
                return
        except OSError:
            return
        seen.add(path)
        candidates.append(resolved)

    artifact_dirs = [
        root / "frontend" / ".e2e-artifacts",
        root / ".e2e-artifacts",
    ]
    for artifact_dir in artifact_dirs:
        if artifact_dir.is_dir():
            for path in artifact_dir.rglob("*"):
                consider(path)

    for path in root.glob("*screenshot*"):
        consider(path)
    for path in root.glob("*/*screenshot*"):
        consider(path)

    candidates.sort(key=lambda item: item.as_posix())
    return candidates[:PR_SCREENSHOT_MAX_FILES]


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
    pr_number: int,
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
        asset_name = release_asset_name(shot, pr_number, index)
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
