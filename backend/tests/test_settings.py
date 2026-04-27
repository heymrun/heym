"""Tests for environment-derived application settings."""

import unittest

from app.config import Settings


class TestSettingsDatabaseUrl(unittest.TestCase):
    def test_database_url_is_built_from_postgres_fields_when_blank(self) -> None:
        settings = Settings(
            _env_file=None,
            encryption_key="0" * 64,
            database_url="",
            postgres_host="db",
            postgres_port=5432,
            postgres_user="heym",
            postgres_password="secret",
            postgres_db="workflow",
        )

        self.assertEqual(
            settings.database_url,
            "postgresql+asyncpg://heym:secret@db:5432/workflow",
        )

    def test_explicit_database_url_takes_precedence(self) -> None:
        settings = Settings(
            _env_file=None,
            encryption_key="0" * 64,
            database_url="postgresql+asyncpg://explicit:secret@custom:6544/app",
            postgres_host="db",
            postgres_port=5432,
            postgres_user="heym",
            postgres_password="secret",
            postgres_db="workflow",
        )

        self.assertEqual(
            settings.database_url,
            "postgresql+asyncpg://explicit:secret@custom:6544/app",
        )
