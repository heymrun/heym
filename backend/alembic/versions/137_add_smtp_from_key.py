"""add the optional smtp_from key to SMTP credential configs

SMTP settings live inside the credential's encrypted_config, so this is a data
migration rather than a new column. Every SMTP config gains `smtp_from: ""`
(blank means the visible From header stays `smtp_email`); a value that is
already there is kept. Other credential types are not read or written.

The migration decrypts with the application's Fernet key (ENCRYPTION_KEY). A
row that cannot be decrypted fails the migration instead of being skipped, so a
wrong key never leaves the table half-migrated.

Revision ID: 137_add_smtp_from_key
Revises: 136_add_chat_skill_write
Create Date: 2026-10-11 00:00:00.000000

"""

from collections.abc import Callable
from typing import Sequence, Union

import sqlalchemy as sa
from cryptography.fernet import InvalidToken
from sqlalchemy.engine import Connection

from alembic import op
from app.services.encryption import decrypt_config, encrypt_config

revision: str = "137_add_smtp_from_key"
down_revision: Union[str, None] = "136_add_chat_skill_write"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def rewrite_smtp_configs(conn: Connection, transform: Callable[[dict], bool]) -> None:
    """Apply ``transform`` to every SMTP config; write back the ones it reports changed."""
    rows = conn.execute(
        sa.text("SELECT id, encrypted_config FROM credentials WHERE type = 'smtp'")
    ).fetchall()
    for row_id, ciphertext in rows:
        try:
            config = decrypt_config(ciphertext)
        except (InvalidToken, ValueError) as exc:
            raise RuntimeError(
                f"Cannot decrypt SMTP credential {row_id}; check ENCRYPTION_KEY"
            ) from exc
        if not isinstance(config, dict):
            raise RuntimeError(f"SMTP credential {row_id} does not hold a JSON object")
        if transform(config):
            conn.execute(
                sa.text("UPDATE credentials SET encrypted_config = :config WHERE id = :row_id"),
                {"config": encrypt_config(config), "row_id": row_id},
            )


def add_smtp_from(config: dict) -> bool:
    """Set ``smtp_from`` to "" when absent; never overwrite an existing value."""
    if "smtp_from" in config:
        return False
    config["smtp_from"] = ""
    return True


def remove_smtp_from(config: dict) -> bool:
    """Drop ``smtp_from`` when present."""
    if "smtp_from" not in config:
        return False
    del config["smtp_from"]
    return True


def upgrade() -> None:
    rewrite_smtp_configs(op.get_bind(), add_smtp_from)


def downgrade() -> None:
    rewrite_smtp_configs(op.get_bind(), remove_smtp_from)
