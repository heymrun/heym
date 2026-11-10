"""Unit tests for DocIndexService (keyword search over docs markdown)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services.doc_index import (
    _DEFAULT_DOCS_DIR,
    DocIndexService,
    _extract_title,
    _get_docs_dir,
    _keyword_score,
    _load_docs,
    logger,
)


def _write_md(root: Path, rel_path: str, content: str) -> Path:
    path = root / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


class GetDocsDirTests(unittest.TestCase):
    def test_override_is_used_when_provided(self) -> None:
        result = _get_docs_dir(" /some/path ")
        self.assertEqual(result, Path("/some/path").resolve())

    def test_none_falls_back_to_default(self) -> None:
        self.assertEqual(_get_docs_dir(None), _DEFAULT_DOCS_DIR)

    def test_blank_override_falls_back_to_default(self) -> None:
        self.assertEqual(_get_docs_dir(""), _DEFAULT_DOCS_DIR)
        self.assertEqual(_get_docs_dir("   "), _DEFAULT_DOCS_DIR)


class ExtractTitleTests(unittest.TestCase):
    def test_extracts_h1_at_start(self) -> None:
        self.assertEqual(_extract_title("# Title\nbody"), "Title")

    def test_no_space_after_hash_does_not_match(self) -> None:
        self.assertEqual(_extract_title("#Title\nbody"), "")

    def test_h1_found_on_a_later_line(self) -> None:
        content = "intro text\n# Real Title\nmore text"
        self.assertEqual(_extract_title(content), "Real Title")

    def test_no_title_returns_empty_string(self) -> None:
        self.assertEqual(_extract_title("just body text, no heading"), "")

    def test_title_whitespace_is_stripped(self) -> None:
        content = "#   Title with extra spaces   \nbody"
        self.assertEqual(_extract_title(content), "Title with extra spaces")


class LoadDocsTests(unittest.TestCase):
    def test_nonexistent_directory_returns_empty_list(self) -> None:
        missing = Path("/does/not/exist/for/sure")
        with patch.object(logger, "warning") as mock_warning:
            docs = _load_docs(missing)
        self.assertEqual(docs, [])
        mock_warning.assert_called_once()

    def test_empty_directory_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(_load_docs(Path(tmp)), [])

    def test_loads_a_real_markdown_file_with_correct_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_md(tmp_path, "hello.md", "# Hello\nSome body text.")

            docs = _load_docs(tmp_path)

        self.assertEqual(len(docs), 1)
        doc = docs[0]
        self.assertEqual(doc["path"], "/docs/./hello")
        self.assertEqual(doc["title"], "Hello")
        self.assertEqual(doc["content"], "# Hello\nSome body text.")
        self.assertIn("hello", doc["search_text"])
        self.assertIn("some body text", doc["search_text"])
        self.assertEqual(doc["search_text"], doc["search_text"].lower())

    def test_category_reflects_nested_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_md(tmp_path, "guides/x.md", "# Guide X\nbody")

            docs = _load_docs(tmp_path)

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["path"], "/docs/guides/x")

    def test_missing_title_falls_back_to_filename_stem(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_md(tmp_path, "my-doc.md", "no heading here, just text")

            docs = _load_docs(tmp_path)

        self.assertEqual(docs[0]["title"], "my-doc")

    def test_results_are_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_md(tmp_path, "zebra.md", "# Zebra\nbody")
            _write_md(tmp_path, "alpha.md", "# Alpha\nbody")

            docs = _load_docs(tmp_path)

        self.assertEqual([d["title"] for d in docs], ["Alpha", "Zebra"])

    def test_unreadable_file_is_skipped_others_still_load(self) -> None:
        real_read_text = Path.read_text

        def fake_read_text(self: Path, *args: object, **kwargs: object) -> str:
            if self.name == "bad.md":
                raise OSError("simulated unreadable file")
            return real_read_text(self, *args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_md(tmp_path, "bad.md", "# Bad\nbody")
            _write_md(tmp_path, "good.md", "# Good\nbody")

            with patch.object(Path, "read_text", fake_read_text):
                with patch.object(logger, "warning") as mock_warning:
                    docs = _load_docs(tmp_path)

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0]["title"], "Good")
        mock_warning.assert_called_once()


class KeywordScoreTests(unittest.TestCase):
    def test_counts_matching_terms(self) -> None:
        doc = {"search_text": "python testing guide"}
        self.assertEqual(_keyword_score("python testing", doc), 2)

    def test_single_character_terms_are_ignored(self) -> None:
        doc = {"search_text": "a cat sat"}
        self.assertEqual(_keyword_score("a", doc), 0)

    def test_empty_query_scores_zero(self) -> None:
        doc = {"search_text": "anything at all"}
        self.assertEqual(_keyword_score("   ", doc), 0)

    def test_matching_is_case_insensitive(self) -> None:
        doc = {"search_text": "python testing guide"}
        self.assertEqual(_keyword_score("PYTHON", doc), 1)

    def test_duplicate_query_terms_count_more_than_once(self) -> None:
        doc = {"search_text": "python testing guide"}
        self.assertEqual(_keyword_score("python python", doc), 2)

    def test_short_identifiers_do_not_match_inside_encoded_data(self) -> None:
        self.assertEqual(_keyword_score("L1", {"search_text": "abcl1xyz"}), 0)

    def test_query_punctuation_does_not_hide_a_title_match(self) -> None:
        self.assertGreater(_keyword_score("(L0)", {"search_text": "playbook (l0)"}), 0)


class DocIndexServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        # Class-level singleton - every test needs a clean slate, or an earlier
        # test's get_instance() call leaks into a later one.
        DocIndexService._instance = None

    def tearDown(self) -> None:
        DocIndexService._instance = None

    def test_empty_or_whitespace_query_returns_empty_list(self) -> None:
        service = DocIndexService(docs_dir=Path("/does/not/exist"))
        self.assertEqual(service.search(""), [])
        self.assertEqual(service.search("   "), [])

    def test_no_docs_returns_empty_list(self) -> None:
        service = DocIndexService(docs_dir=Path("/does/not/exist"))
        self.assertEqual(service.search("anything"), [])

    def test_results_are_ranked_by_score_descending(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_md(tmp_path, "weak.md", "# Weak\npython mentioned once")
            _write_md(tmp_path, "strong.md", "# Strong\npython python python")

            service = DocIndexService(docs_dir=tmp_path)
            results = service.search("python")

        self.assertEqual([r["title"] for r in results], ["Strong", "Weak"])

    def test_zero_score_docs_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_md(tmp_path, "match.md", "# Match\npython guide")
            _write_md(tmp_path, "nomatch.md", "# NoMatch\nunrelated content")

            service = DocIndexService(docs_dir=tmp_path)
            results = service.search("python")

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Match")

    def test_top_k_limits_result_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            for i in range(3):
                _write_md(tmp_path, f"doc{i}.md", f"# Doc {i}\npython guide")

            service = DocIndexService(docs_dir=tmp_path)
            results = service.search("python", top_k=2)

        self.assertEqual(len(results), 2)

    def test_duplicate_paths_are_deduplicated(self) -> None:
        service = DocIndexService(docs_dir=Path("/does/not/exist"))
        service._docs = [
            {"path": "/docs/x", "title": "First", "content": "a", "search_text": "python first"},
            {"path": "/docs/x", "title": "Second", "content": "b", "search_text": "python second"},
        ]
        service._loaded = True

        results = service.search("python")

        self.assertEqual(len(results), 1)

    def test_second_search_does_not_reload_from_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            _write_md(tmp_path, "doc.md", "# Doc\npython guide")

            service = DocIndexService(docs_dir=tmp_path)
            with patch("app.services.doc_index._load_docs", wraps=_load_docs) as mock_load:
                service.search("python")
                service.search("python")

        mock_load.assert_called_once()

    def test_get_instance_returns_the_same_object(self) -> None:
        first = DocIndexService.get_instance(docs_dir_override="/tmp")
        second = DocIndexService.get_instance(docs_dir_override="/tmp")
        self.assertIs(first, second)

    def test_title_match_ranks_above_a_general_reference(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_md(root, "reference/features.md", "# Features\nL0 severity incident support")
            _write_md(root, "reference/playbook.md", "# Incident Playbook (L0)\nTriage steps")
            results = DocIndexService(root).search("L0 severity incident support")

        self.assertEqual(results[0]["path"], "/docs/reference/playbook")

    def test_large_results_preserve_relevant_text_and_citations_within_json_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(5):
                _write_md(
                    root,
                    f"reference/runbook-{index}.md",
                    f"# Runbook {index}\n\n"
                    + "General background.\n\n" * 3000
                    + f"## Database recovery\n\nRecovery evidence {index}: restore the snapshot.\n\n"
                    + "Other background.\n\n" * 3000,
                )
            results = DocIndexService(root).search("database recovery", max_chars=80_000)

        self.assertLessEqual(len(json.dumps({"results": results})), 80_000)
        self.assertEqual(len(results), 5)
        for index, result in enumerate(results):
            self.assertEqual(result["path"], f"/docs/reference/runbook-{index}")
            self.assertIn(f"Recovery evidence {index}: restore the snapshot.", result["content"])
            self.assertTrue(result["excerpted"])

    def test_json_budget_accounts_for_unicode_and_escaped_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(5):
                _write_md(
                    root, f"guide-{index}.md", "# Guide\n\n" + '\u00e9 "guide" \\ \n' * 10_000
                )
            results = DocIndexService(root).search("guide", max_chars=80_000)

        self.assertLessEqual(len(json.dumps({"results": results})), 80_000)
        self.assertTrue(all(result["content"] for result in results))

    def test_container_docs_override_loads_the_same_content_as_local_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "app" / "docs"
            _write_md(root, "reference/playbook.md", "# Incident Playbook (L0)\nTriage steps")
            with patch("app.config.settings.docs_dir", str(root)):
                service = DocIndexService.get_instance()
                results = service.search("L0")

        self.assertEqual(results[0]["content"], "# Incident Playbook (L0)\nTriage steps")
        self.assertEqual(results[0]["path"], "/docs/reference/playbook")


if __name__ == "__main__":
    unittest.main()
