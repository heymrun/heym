"""
Doc Index Service for Heym platform documentation.

Provides keyword search over docs content. Returns full markdown files.
No embedding or vector store - simple text matching.
"""

import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_DEFAULT_DOCS_DIR = _PROJECT_ROOT / "frontend" / "src" / "docs" / "content"

TOP_K = 5


def _get_docs_dir(docs_dir_override: str | None) -> Path:
    """Resolve docs directory path."""
    if docs_dir_override and docs_dir_override.strip():
        return Path(docs_dir_override.strip()).resolve()
    return _DEFAULT_DOCS_DIR


def _extract_title(content: str) -> str:
    """Extract H1 title from markdown content."""
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _load_docs(docs_dir: Path) -> list[dict[str, Any]]:
    """Load all markdown docs with full content."""
    docs: list[dict[str, Any]] = []
    if not docs_dir.exists():
        logger.warning("Docs directory does not exist: %s", docs_dir)
        return docs

    for md_path in sorted(docs_dir.rglob("*.md")):
        try:
            raw = md_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning("Failed to read %s: %s", md_path, e)
            continue

        rel = md_path.relative_to(docs_dir)
        category = rel.parent.as_posix()
        slug = md_path.stem
        path = f"/docs/{category}/{slug}"
        title = _extract_title(raw)

        docs.append(
            {
                "path": path,
                "title": title or slug,
                "content": raw,
                "search_text": f"{title} {slug} {category} {raw}".lower(),
            }
        )

    return docs


def _keyword_score(query: str, doc: dict[str, Any]) -> int:
    """Score doc by number of query terms found (case-insensitive)."""
    terms = [t.lower() for t in query.split() if len(t) > 1]
    if not terms:
        return 0
    search_text = doc.get("search_text", "")
    score = sum(1 for t in terms if t in search_text)
    return score


class DocIndexService:
    """Keyword-based documentation search. Returns full MD content."""

    _instance: "DocIndexService | None" = None

    def __init__(self, docs_dir: Path | None = None) -> None:
        self._docs_dir = docs_dir or _DEFAULT_DOCS_DIR
        self._docs: list[dict[str, Any]] = []
        self._loaded = False

    @classmethod
    def get_instance(cls, docs_dir_override: str | None = None) -> "DocIndexService":
        """Get singleton instance."""
        if cls._instance is None:
            from app.config import settings

            override = (
                docs_dir_override
                if docs_dir_override is not None
                else getattr(settings, "docs_dir", "")
            )
            docs_path = _get_docs_dir(override)
            cls._instance = cls(docs_path)
        return cls._instance

    def _ensure_loaded(self) -> None:
        """Load docs on first search."""
        if self._loaded:
            return
        self._docs = _load_docs(self._docs_dir)
        self._loaded = True
        logger.info("Doc index loaded: %d docs from %s", len(self._docs), self._docs_dir)

    def search(
        self,
        query: str,
        top_k: int = TOP_K,
    ) -> list[dict[str, Any]]:
        """
        Search documentation by keyword. Returns full markdown content.

        Returns list of {title, path, content} for up to top_k distinct docs.
        """
        if not query or not query.strip():
            return []

        self._ensure_loaded()

        if not self._docs:
            return []

        scored = [(doc, _keyword_score(query.strip(), doc)) for doc in self._docs]
        scored = [(d, s) for d, s in scored if s > 0]
        scored.sort(key=lambda x: x[1], reverse=True)

        seen_paths: set[str] = set()
        results: list[dict[str, Any]] = []
        for doc, _ in scored:
            path = doc["path"]
            if path in seen_paths:
                continue
            seen_paths.add(path)
            results.append(
                {
                    "title": doc["title"],
                    "path": path,
                    "content": doc["content"],
                }
            )
            if len(results) >= top_k:
                break

        return results
