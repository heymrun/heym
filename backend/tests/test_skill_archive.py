"""Zip attachments: a SKILL.md becomes a skill bundle, anything else stays context."""

import base64
import io
import unittest
import zipfile

from app.services.skill_archive import decode_zip_payload, prompt_for_zip, read_zip


def _zip(files: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


class SkillArchiveTests(unittest.TestCase):
    def test_a_skill_zip_keeps_markdown_and_python_and_skips_macos_metadata(self) -> None:
        raw = _zip(
            {
                "helper/SKILL.md": "---\nname: invoice-helper\n---\nRead the invoice.",
                "helper/main.py": "def run():\n    return 1\n",
                "helper/notes.md": "extra",
                "__MACOSX/helper/._SKILL.md": "junk",
                ".DS_Store": "junk",
                "helper/logo.png": b"\x89PNG\x00\x00",
            }
        )

        reading = read_zip(raw)

        self.assertEqual(len(reading.skills), 1)
        skill = reading.skills[0]
        self.assertEqual(skill.name, "invoice-helper")
        self.assertIn("Read the invoice.", skill.content)
        self.assertEqual(
            {item.path: item.content for item in skill.files},
            {"main.py": "def run():\n    return 1\n", "notes.md": "extra"},
        )
        self.assertTrue(any("logo.png" in note for note in reading.notes))

    def test_a_zip_without_skill_markdown_is_context_only(self) -> None:
        reading = read_zip(_zip({"readme.txt": "hello", "src/app.py": "print(1)\n"}))

        self.assertEqual(reading.skills, ())
        self.assertEqual([item.path for item in reading.text_files], ["readme.txt", "src/app.py"])
        self.assertIn("no SKILL.md", prompt_for_zip("notes.zip", reading))

    def test_a_skill_prompt_tells_the_model_not_to_paste_the_files(self) -> None:
        reading = read_zip(_zip({"SKILL.md": "---\nname: tidy\n---\nTidy the text."}))

        text = prompt_for_zip("tidy.zip", reading)

        self.assertIn("apply_skill", text)
        self.assertIn("tidy", text)
        self.assertIn("Do not paste", text)

    def test_decode_accepts_a_data_url_and_rejects_plain_text(self) -> None:
        raw = _zip({"SKILL.md": "---\nname: tidy\n---\n"})
        encoded = "data:application/zip;base64," + base64.b64encode(raw).decode()

        self.assertEqual(decode_zip_payload(encoded), raw)
        self.assertIsNone(decode_zip_payload("hello"))


if __name__ == "__main__":
    unittest.main()
