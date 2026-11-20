"""Zip attachments: a SKILL.md becomes a skill bundle, anything else stays context."""

import base64
import io
import struct
import unittest
import zipfile

from app.services.skill_archive import decode_zip_payload, prompt_for_zip, read_zip


def _zip(files: dict[str, str | bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return buffer.getvalue()


def _damaged(raw: bytes, member: str) -> bytes:
    """`raw` with one byte of `member`'s stored data flipped, so its CRC no longer matches."""
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        info = archive.getinfo(member)
    name_len, extra_len = struct.unpack_from("<HH", raw, info.header_offset + 26)
    out = bytearray(raw)
    out[info.header_offset + 30 + name_len + extra_len + 2] ^= 0xFF
    return bytes(out)


class SkillArchiveTests(unittest.TestCase):
    def test_a_skill_zip_keeps_every_file_and_skips_macos_metadata(self) -> None:
        raw = _zip(
            {
                "helper/SKILL.md": "---\nname: invoice-helper\n---\nRead the invoice.",
                "helper/main.py": "def run():\n    return 1\n",
                "helper/notes.md": "extra",
                "helper/templates/rates.csv": "code,rate\nA,1\n",
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
            {item.path: (item.encoding, item.content) for item in skill.files},
            {
                "main.py": ("text", "def run():\n    return 1\n"),
                "notes.md": ("text", "extra"),
                "templates/rates.csv": ("text", "code,rate\nA,1\n"),
                "logo.png": ("base64", base64.b64encode(b"\x89PNG\x00\x00").decode()),
            },
        )
        self.assertEqual(reading.notes, ())

    def test_a_binary_file_outside_every_skill_folder_is_skipped(self) -> None:
        reading = read_zip(
            _zip({"helper/SKILL.md": "---\nname: tidy\n---\n", "cover.png": b"\x89PNG\x00"})
        )

        self.assertEqual(reading.skills[0].files, ())
        self.assertTrue(any("cover.png" in note for note in reading.notes))

    def test_the_prompt_lists_assets_by_path_and_never_shows_base64(self) -> None:
        png = b"\x89PNG\x00" * 40
        reading = read_zip(_zip({"h/SKILL.md": "---\nname: tidy\n---\nTidy.", "h/logo.png": png}))

        text = prompt_for_zip("tidy.zip", reading)

        self.assertIn("logo.png", text)
        self.assertNotIn(base64.b64encode(png).decode()[:24], text)

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

    def test_a_password_protected_member_becomes_a_note(self) -> None:
        raw = bytearray(
            _zip({"greeter/SKILL.md": "---\nname: greeter\n---\n", "greeter/notes.txt": "café"})
        )
        # Set general purpose bit 0 (encrypted) on every local and central header, as a
        # password-protecting zip tool does.
        for signature, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
            index = raw.find(signature)
            while index >= 0:
                flags = struct.unpack_from("<H", raw, index + flag_offset)[0]
                struct.pack_into("<H", raw, index + flag_offset, flags | 0x1)
                index = raw.find(signature, index + 4)

        reading = read_zip(bytes(raw))

        self.assertEqual(reading.skills, ())
        self.assertIn("Skipped greeter/SKILL.md: the file is password-protected.", reading.notes)
        self.assertIn("password-protected", prompt_for_zip("greeter.zip", reading))

    def test_a_damaged_member_becomes_a_note_and_the_rest_is_read(self) -> None:
        raw = _damaged(
            _zip({"broken.txt": "Bonjour from Zürich", "tidy/SKILL.md": "---\nname: tidy\n---\n"}),
            "broken.txt",
        )

        reading = read_zip(raw)

        self.assertIn(
            "Skipped broken.txt: the file is damaged or could not be unpacked.", reading.notes
        )
        self.assertEqual([skill.name for skill in reading.skills], ["tidy"])

    def test_a_skill_with_a_damaged_member_is_left_out_and_read_as_context(self) -> None:
        # Saving the skill without main.py would replace the stored skill and drop its main.py.
        raw = _damaged(
            _zip(
                {
                    "greeter/main.py": "def run():\n    return 'Bonjour'\n",
                    "greeter/SKILL.md": "---\nname: greeter\n---\nSay Bonjour.",
                    "greeter/notes.md": "Greet in French.",
                    "tidy/SKILL.md": "---\nname: tidy\n---\nTidy the text.",
                }
            ),
            "greeter/main.py",
        )

        reading = read_zip(raw)

        self.assertEqual([skill.name for skill in reading.skills], ["tidy"])
        self.assertIn(
            "Skipped greeter/main.py: the file is damaged or could not be unpacked.",
            reading.notes,
        )
        self.assertIn(
            "Did not read skill greeter: greeter/main.py could not be read.", reading.notes
        )
        self.assertEqual(
            sorted(item.path for item in reading.text_files),
            ["greeter/SKILL.md", "greeter/notes.md"],
        )
        prompt = prompt_for_zip("skills.zip", reading)
        self.assertIn("Skill tidy.", prompt)
        self.assertNotIn("Skill greeter.", prompt)
        self.assertIn("Say Bonjour.", prompt)

    def test_a_skill_with_a_password_protected_member_is_left_out(self) -> None:
        raw = bytearray(
            _zip({"greeter/SKILL.md": "---\nname: greeter\n---\n", "greeter/main.py": "x = 1\n"})
        )
        with zipfile.ZipFile(io.BytesIO(bytes(raw))) as archive:
            info = archive.getinfo("greeter/main.py")
        # Set general purpose bit 0 (encrypted) on main.py's local and central headers only.
        local_flags = struct.unpack_from("<H", raw, info.header_offset + 6)[0]
        struct.pack_into("<H", raw, info.header_offset + 6, local_flags | 0x1)
        central = raw.find(b"PK\x01\x02")
        while central >= 0:
            name_len = struct.unpack_from("<H", raw, central + 28)[0]
            if raw[central + 46 : central + 46 + name_len] == b"greeter/main.py":
                flags = struct.unpack_from("<H", raw, central + 8)[0]
                struct.pack_into("<H", raw, central + 8, flags | 0x1)
            central = raw.find(b"PK\x01\x02", central + 4)

        reading = read_zip(bytes(raw))

        self.assertEqual(reading.skills, ())
        self.assertIn("Skipped greeter/main.py: the file is password-protected.", reading.notes)
        self.assertIn(
            "Did not read skill greeter: greeter/main.py could not be read.", reading.notes
        )


if __name__ == "__main__":
    unittest.main()
