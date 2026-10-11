"""Tests for the 137_add_smtp_from_key data migration over encrypted SMTP configs."""

import importlib.util
import unittest
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa

from app.services.encryption import decrypt_config, encrypt_config

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "137_add_smtp_from_key.py"
)


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smtp_from_migration", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SmtpFromMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.migration = _load_migration()
        self.engine = sa.create_engine("sqlite://")
        with self.engine.begin() as conn:
            conn.execute(
                sa.text(
                    "CREATE TABLE credentials "
                    "(id TEXT PRIMARY KEY, type TEXT NOT NULL, encrypted_config TEXT NOT NULL)"
                )
            )

    def tearDown(self) -> None:
        self.engine.dispose()

    def _insert(self, row_id: str, cred_type: str, ciphertext: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                sa.text("INSERT INTO credentials VALUES (:id, :type, :config)"),
                {"id": row_id, "type": cred_type, "config": ciphertext},
            )

    def _ciphertext(self, row_id: str) -> str:
        with self.engine.connect() as conn:
            return conn.execute(
                sa.text("SELECT encrypted_config FROM credentials WHERE id = :id"),
                {"id": row_id},
            ).scalar_one()

    def _upgrade(self) -> None:
        with self.engine.begin() as conn:
            self.migration.rewrite_smtp_configs(conn, self.migration.add_smtp_from)

    def _downgrade(self) -> None:
        with self.engine.begin() as conn:
            self.migration.rewrite_smtp_configs(conn, self.migration.remove_smtp_from)

    def _smtp_config(self, **extra: str) -> dict:
        return {
            "smtp_server": "smtp.example.com",
            "smtp_port": "587",
            "smtp_email": "login@example.com",
            "smtp_password": "secret",
            **extra,
        }

    def test_smtp_config_without_smtp_from_gains_blank_value(self) -> None:
        self._insert("a", "smtp", encrypt_config(self._smtp_config()))

        self._upgrade()

        self.assertEqual(decrypt_config(self._ciphertext("a")), self._smtp_config(smtp_from=""))

    def test_existing_smtp_from_is_kept(self) -> None:
        original = encrypt_config(self._smtp_config(smtp_from="team@example.com"))
        self._insert("a", "smtp", original)

        self._upgrade()

        self.assertEqual(self._ciphertext("a"), original)
        self.assertEqual(decrypt_config(self._ciphertext("a"))["smtp_from"], "team@example.com")

    def test_non_smtp_row_is_untouched(self) -> None:
        openai_cipher = encrypt_config({"api_key": "sk-test"})
        self._insert("o", "openai", openai_cipher)
        self._insert("bad", "bearer", "not-a-fernet-token")
        self._insert("s", "smtp", encrypt_config(self._smtp_config()))

        self._upgrade()
        self._downgrade()

        self.assertEqual(self._ciphertext("o"), openai_cipher)
        self.assertEqual(self._ciphertext("bad"), "not-a-fernet-token")

    def test_undecryptable_smtp_row_fails_the_migration(self) -> None:
        good_cipher = encrypt_config(self._smtp_config())
        self._insert("good", "smtp", good_cipher)
        self._insert("bad", "smtp", "not-a-fernet-token")

        with self.assertRaises(RuntimeError) as ctx:
            self._upgrade()

        self.assertIn("bad", str(ctx.exception))
        self.assertEqual(self._ciphertext("good"), good_cipher)

    def test_downgrade_removes_smtp_from(self) -> None:
        self._insert("a", "smtp", encrypt_config(self._smtp_config(smtp_from="team@example.com")))
        self._insert("b", "smtp", encrypt_config(self._smtp_config()))

        self._upgrade()
        self._downgrade()

        self.assertEqual(decrypt_config(self._ciphertext("a")), self._smtp_config())
        self.assertEqual(decrypt_config(self._ciphertext("b")), self._smtp_config())


if __name__ == "__main__":
    unittest.main()
