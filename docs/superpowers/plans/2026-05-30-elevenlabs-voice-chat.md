# ElevenLabs Voice for Chat (TTS + STT) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add ElevenLabs-powered text-to-speech (per-message read-aloud) and a hands-free interactive voice mode (Scribe STT + multilingual TTS) to the internal `/chat` tab, configured via a new ElevenLabs credential type selected in the User Settings dialog.

**Architecture:** Backend proxy, turn-based REST. The browser records audio with `MediaRecorder` + client-side VAD, posts it to the backend which calls ElevenLabs (key stays server-side, mirroring `decrypt_config` + `httpx` usage in chats.py), and plays returned `audio/mpeg`. Voice is a user preference; the interactive overlay reuses the existing chat conversation.

**Tech Stack:** FastAPI + SQLAlchemy 2.0 async + Pydantic + httpx + Alembic (backend); Vue 3 `<script setup>` + Pinia + TypeScript strict + Tailwind (frontend); ElevenLabs `/v1/voices`, `/v1/text-to-speech/{voice_id}` (`eleven_multilingual_v2`), `/v1/speech-to-text` (`scribe_v1`).

**Repo conventions:** Work on `main` (no worktrees). Backend uses TDD with `unittest.IsolatedAsyncioTestCase` + `AsyncMock`/`patch`, run via `cd backend && uv run pytest`. Frontend has no test runner — verify with `cd frontend && bun run typecheck && bun run lint` (and `bun run build` for the large component). Run `./check.sh` before any push. Never commit secrets or Turkish text in code/comments.

---

## File Structure

**Backend (create):**
- `backend/app/services/elevenlabs_service.py` — async httpx wrapper for the three ElevenLabs calls.
- `backend/app/api/voice.py` — `/api/voice` router (voices / tts / stt) + request/response models + credential resolver.
- `backend/alembic/versions/072_add_elevenlabs_credential_type.py` — enum value migration.
- `backend/alembic/versions/073_add_user_tts_preferences.py` — `users` columns migration.
- `backend/tests/test_elevenlabs_service.py`, `backend/tests/test_voice_api.py`, `backend/tests/test_credential_elevenlabs.py`, `backend/tests/test_user_tts_preferences.py`.

**Backend (modify):**
- `backend/app/models/schemas.py` — `CredentialType.elevenlabs`, `CredentialConfigElevenLabs`, union member, `UserUpdate`/`UserResponse` tts fields.
- `backend/app/db/models.py` — `User.tts_credential_id`, `User.tts_voice_id`.
- `backend/app/api/credentials.py` — validate + mask for `elevenlabs`.
- `backend/app/api/auth.py` — `update_me` handles tts fields with validation.
- `backend/app/main.py` — register voice router.

**Frontend (create):**
- `frontend/src/composables/useTextToSpeech.ts` — shared audio playback.
- `frontend/src/composables/useInteractiveVoice.ts` — mic/VAD/STT/TTS state machine.
- `frontend/src/stores/voice.ts` — Pinia bridge to open Voice settings from anywhere.
- `frontend/src/components/Chat/InteractiveVoiceMode.vue` — full-screen voice overlay.

**Frontend (modify):**
- `frontend/src/types/credential.ts` — `elevenlabs` type/config/labels.
- `frontend/src/types/auth.ts` — `tts_credential_id`/`tts_voice_id` on `User` + `UserUpdateRequest`.
- `frontend/src/services/api.ts` — `voiceApi`.
- `frontend/src/components/Credentials/CredentialDialog.vue` — `presetType` prop + elevenlabs field.
- `frontend/src/components/Layout/UserSettingsDialog.vue` — Voice tab + `initialTab` prop.
- `frontend/src/components/Layout/AppHeader.vue` — open settings on Voice tab via store.
- `frontend/src/components/Chat/ChatConversation.vue` — per-message read-aloud button + interactive-mode entry button + overlay mount.

---

## Task 1: Backend — `elevenlabs` credential type

**Files:**
- Modify: `backend/app/models/schemas.py` (enum at line 439; config models near 460)
- Modify: `backend/app/api/credentials.py` (`get_masked_value` ~line 57; `validate_credential_config` ~line 674)
- Test: `backend/tests/test_credential_elevenlabs.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_credential_elevenlabs.py
import unittest

from fastapi import HTTPException

from app.api.credentials import get_masked_value, validate_credential_config
from app.db.models import CredentialType


class ElevenLabsCredentialTests(unittest.TestCase):
    def test_validate_requires_api_key(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            validate_credential_config(CredentialType.elevenlabs, {})
        self.assertEqual(ctx.exception.status_code, 400)

    def test_validate_passes_with_api_key(self) -> None:
        validate_credential_config(CredentialType.elevenlabs, {"api_key": "sk_test_123"})

    def test_masked_value_hides_api_key(self) -> None:
        masked = get_masked_value(CredentialType.elevenlabs, {"api_key": "sk_test_1234567890"})
        self.assertIsNotNone(masked)
        self.assertNotEqual(masked, "sk_test_1234567890")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_credential_elevenlabs.py -v`
Expected: FAIL — `AttributeError: elevenlabs` (enum member missing).

- [ ] **Step 3: Add the enum member and config model in `schemas.py`**

In `class CredentialType` (after `bigquery = "bigquery"` at line 457) add:

```python
    elevenlabs = "elevenlabs"
```

After `class CredentialConfigGoogle` (~line 464) add:

```python
class CredentialConfigElevenLabs(BaseModel):
    api_key: str
```

Find the `CredentialConfig` union (the `CredentialConfig = CredentialConfigOpenAI | ...` alias) and add `| CredentialConfigElevenLabs` to it.

- [ ] **Step 4: Add validate + mask branches in `credentials.py`**

In `get_masked_value`, extend the openai branch condition (line 57) to include elevenlabs:

```python
    elif credential_type in (
        CredentialType.openai,
        CredentialType.google,
        CredentialType.custom,
        CredentialType.elevenlabs,
    ):
        api_key = config.get("api_key", "")
        return mask_api_key(api_key)
```

In `validate_credential_config`, add a branch (after the `custom` branch, before `header`):

```python
    elif credential_type == CredentialType.elevenlabs:
        if "api_key" not in config or not config["api_key"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ElevenLabs credential requires api_key",
            )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_credential_elevenlabs.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Format, lint, commit**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/models/schemas.py backend/app/api/credentials.py backend/tests/test_credential_elevenlabs.py
git commit -m "feat(voice): add elevenlabs credential type"
```

---

## Task 2: Backend — DB columns + migrations for TTS preferences

**Files:**
- Modify: `backend/app/db/models.py` (`User` class, after `mcp_api_key` at line 70)
- Create: `backend/alembic/versions/072_add_elevenlabs_credential_type.py`
- Create: `backend/alembic/versions/073_add_user_tts_preferences.py`

- [ ] **Step 1: Add columns to the `User` model**

In `class User` (`backend/app/db/models.py`), after the `mcp_api_key` column (line 68-70), add:

```python
    tts_credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("credentials.id", ondelete="SET NULL"),
        nullable=True,
    )
    tts_voice_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

- [ ] **Step 2: Create the enum migration (072)**

```python
# backend/alembic/versions/072_add_elevenlabs_credential_type.py
"""add elevenlabs credential type

Revision ID: 072
Revises: 071
Create Date: 2026-05-30
"""

from alembic import op

revision: str = "072"
down_revision: str | None = "071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE credential_type ADD VALUE IF NOT EXISTS 'elevenlabs'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values; downgrade is a no-op.
    pass
```

- [ ] **Step 3: Create the user-columns migration (073)**

```python
# backend/alembic/versions/073_add_user_tts_preferences.py
"""add user tts preferences

Revision ID: 073
Revises: 072
Create Date: 2026-05-30
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "073"
down_revision: str | None = "072"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("tts_credential_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("users", sa.Column("tts_voice_id", sa.String(length=64), nullable=True))
    op.create_foreign_key(
        "fk_users_tts_credential_id",
        "users",
        "credentials",
        ["tts_credential_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_tts_credential_id", "users", type_="foreignkey")
    op.drop_column("users", "tts_voice_id")
    op.drop_column("users", "tts_credential_id")
```

- [ ] **Step 4: Apply migrations**

Run: `cd backend && uv run alembic upgrade head`
Expected: completes without error; `alembic current` shows `073`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/models.py backend/alembic/versions/072_add_elevenlabs_credential_type.py backend/alembic/versions/073_add_user_tts_preferences.py
git commit -m "feat(voice): add user tts preference columns + migrations"
```

---

## Task 3: Backend — expose TTS preferences on `/api/auth/me`

**Files:**
- Modify: `backend/app/models/schemas.py` (`UserUpdate` line 51, `UserResponse` line 56)
- Modify: `backend/app/api/auth.py` (`update_me` line 216)
- Test: `backend/tests/test_user_tts_preferences.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_user_tts_preferences.py
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.auth import update_me
from app.db.models import CredentialType
from app.models.schemas import UserUpdate


class UserTtsPreferencesTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_me_sets_tts_fields_for_valid_elevenlabs_credential(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        cred_id = uuid.uuid4()
        credential = MagicMock()
        credential.type = CredentialType.elevenlabs
        db = AsyncMock()

        with (
            patch("app.api.auth.get_accessible_credential", AsyncMock(return_value=credential)),
            patch("app.api.auth.UserResponse") as resp,
        ):
            resp.model_validate.return_value = "ok"
            data = UserUpdate(tts_credential_id=cred_id, tts_voice_id="voice_abc")
            await update_me(data, current_user=user, db=db)

        self.assertEqual(user.tts_credential_id, cred_id)
        self.assertEqual(user.tts_voice_id, "voice_abc")

    async def test_update_me_rejects_non_elevenlabs_credential(self) -> None:
        user = MagicMock()
        user.id = uuid.uuid4()
        credential = MagicMock()
        credential.type = CredentialType.openai
        db = AsyncMock()

        with patch("app.api.auth.get_accessible_credential", AsyncMock(return_value=credential)):
            data = UserUpdate(tts_credential_id=uuid.uuid4())
            with self.assertRaises(HTTPException) as ctx:
                await update_me(data, current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 400)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_user_tts_preferences.py -v`
Expected: FAIL — `UserUpdate` has no `tts_credential_id` field / `update_me` ignores it.

- [ ] **Step 3: Add fields to the schemas**

In `schemas.py`, `class UserUpdate` (line 51) — add (keep existing fields):

```python
class UserUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    user_rules: str | None = Field(None, max_length=4000)
    tts_credential_id: uuid.UUID | None = None
    tts_voice_id: str | None = Field(None, max_length=64)
```

In `class UserResponse` (line 56) — add the two fields before `created_at`:

```python
    tts_credential_id: uuid.UUID | None = None
    tts_voice_id: str | None = None
```

- [ ] **Step 4: Handle the fields in `update_me`**

In `backend/app/api/auth.py`, add the import near the top (with the other service imports):

```python
from app.db.models import CredentialType
from app.services.credential_access import get_accessible_credential
```

Replace the body of `update_me` (after the `user_rules` block, before `await db.flush()`):

```python
    if user_data.tts_credential_id is not None:
        credential = await get_accessible_credential(db, user_data.tts_credential_id, current_user.id)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Credential not found",
            )
        if credential.type != CredentialType.elevenlabs:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TTS credential must be an ElevenLabs credential",
            )
        current_user.tts_credential_id = user_data.tts_credential_id
    if user_data.tts_voice_id is not None:
        current_user.tts_voice_id = user_data.tts_voice_id or None
```

(Confirm `HTTPException` and `status` are already imported in `auth.py`; they are used elsewhere in the file.)

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_user_tts_preferences.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Format, lint, commit**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/models/schemas.py backend/app/api/auth.py backend/tests/test_user_tts_preferences.py
git commit -m "feat(voice): expose tts preferences on /auth/me with validation"
```

---

## Task 4: Backend — `elevenlabs_service.py`

**Files:**
- Create: `backend/app/services/elevenlabs_service.py`
- Test: `backend/tests/test_elevenlabs_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_elevenlabs_service.py
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.elevenlabs_service import (
    ElevenLabsError,
    list_voices,
    speech_to_text,
    text_to_speech,
)


def _fake_client(*, json_data=None, content=None, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.content = content

    def raise_for_status() -> None:
        if status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("err", request=MagicMock(), response=response)

    response.raise_for_status.side_effect = raise_for_status

    client = AsyncMock()
    client.get.return_value = response
    client.post.return_value = response
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx, client


class ElevenLabsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_voices_maps_id_and_name(self) -> None:
        ctx, _ = _fake_client(
            json_data={"voices": [{"voice_id": "v1", "name": "Rachel", "extra": 1}]}
        )
        with patch("app.services.elevenlabs_service.httpx.AsyncClient", return_value=ctx):
            voices = await list_voices("sk_key")
        self.assertEqual(voices, [{"voice_id": "v1", "name": "Rachel"}])

    async def test_text_to_speech_returns_bytes(self) -> None:
        ctx, client = _fake_client(content=b"AUDIO")
        with patch("app.services.elevenlabs_service.httpx.AsyncClient", return_value=ctx):
            audio = await text_to_speech("sk_key", "hello", "v1")
        self.assertEqual(audio, b"AUDIO")
        self.assertIn("/v1/text-to-speech/v1", client.post.call_args.args[0])

    async def test_speech_to_text_returns_text_and_language(self) -> None:
        ctx, _ = _fake_client(json_data={"text": "merhaba", "language_code": "tr"})
        with patch("app.services.elevenlabs_service.httpx.AsyncClient", return_value=ctx):
            result = await speech_to_text("sk_key", b"AUDIO", "a.webm", "audio/webm")
        self.assertEqual(result, {"text": "merhaba", "language_code": "tr"})

    async def test_upstream_error_raises_elevenlabs_error(self) -> None:
        ctx, _ = _fake_client(json_data={"voices": []}, status_code=401)
        with patch("app.services.elevenlabs_service.httpx.AsyncClient", return_value=ctx):
            with self.assertRaises(ElevenLabsError):
                await list_voices("sk_bad")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_elevenlabs_service.py -v`
Expected: FAIL — module `app.services.elevenlabs_service` does not exist.

- [ ] **Step 3: Implement the service**

```python
# backend/app/services/elevenlabs_service.py
"""Async client helpers for the ElevenLabs API (voices, TTS, STT)."""

import httpx

_BASE_URL = "https://api.elevenlabs.io"
_TTS_MODEL_ID = "eleven_multilingual_v2"
_STT_MODEL_ID = "scribe_v1"
_TIMEOUT = httpx.Timeout(60.0)


class ElevenLabsError(Exception):
    """Raised when an ElevenLabs API call fails."""


def _headers(api_key: str) -> dict[str, str]:
    return {"xi-api-key": api_key}


async def list_voices(api_key: str) -> list[dict[str, str]]:
    """Return the account's voices as ``[{voice_id, name}]``."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(f"{_BASE_URL}/v1/voices", headers=_headers(api_key))
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise ElevenLabsError(f"Failed to list voices: {exc}") from exc
    return [
        {"voice_id": v["voice_id"], "name": v.get("name", "")}
        for v in data.get("voices", [])
    ]


async def text_to_speech(
    api_key: str, text: str, voice_id: str, model_id: str = _TTS_MODEL_ID
) -> bytes:
    """Synthesize ``text`` with ``voice_id`` and return MP3 bytes."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{_BASE_URL}/v1/text-to-speech/{voice_id}",
                headers={**_headers(api_key), "Accept": "audio/mpeg"},
                json={"text": text, "model_id": model_id},
            )
            response.raise_for_status()
            return response.content
    except httpx.HTTPError as exc:
        raise ElevenLabsError(f"Failed to synthesize speech: {exc}") from exc


async def speech_to_text(
    api_key: str, audio: bytes, filename: str, content_type: str
) -> dict[str, str]:
    """Transcribe ``audio`` with Scribe; returns ``{text, language_code}``."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(
                f"{_BASE_URL}/v1/speech-to-text",
                headers=_headers(api_key),
                data={"model_id": _STT_MODEL_ID},
                files={"file": (filename, audio, content_type)},
            )
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPError as exc:
        raise ElevenLabsError(f"Failed to transcribe audio: {exc}") from exc
    return {
        "text": data.get("text", ""),
        "language_code": data.get("language_code", ""),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_elevenlabs_service.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Format, lint, commit**

```bash
cd backend && uv run ruff format . && uv run ruff check .
git add backend/app/services/elevenlabs_service.py backend/tests/test_elevenlabs_service.py
git commit -m "feat(voice): add elevenlabs async service (voices/tts/stt)"
```

---

## Task 5: Backend — `/api/voice` router

**Files:**
- Create: `backend/app/api/voice.py`
- Modify: `backend/app/main.py` (register router, near line 233)
- Test: `backend/tests/test_voice_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_voice_api.py
import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from app.api.voice import TtsRequest, _resolve_credential, synthesize, transcribe
from app.db.models import CredentialType


def _user(cred_id=None, voice_id="user_voice"):
    user = MagicMock()
    user.id = uuid.uuid4()
    user.tts_credential_id = cred_id
    user.tts_voice_id = voice_id
    return user


def _credential(ctype=CredentialType.elevenlabs):
    credential = MagicMock()
    credential.id = uuid.uuid4()
    credential.type = ctype
    credential.encrypted_config = "enc"
    return credential


class VoiceApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_credential_uses_user_default(self) -> None:
        cred_id = uuid.uuid4()
        user = _user(cred_id=cred_id)
        credential = _credential()
        db = AsyncMock()
        with (
            patch("app.api.voice.get_accessible_credential", AsyncMock(return_value=credential)),
            patch("app.api.voice.decrypt_config", return_value={"api_key": "sk"}),
        ):
            api_key, _ = await _resolve_credential(db, user, None)
        self.assertEqual(api_key, "sk")

    async def test_resolve_credential_404_when_none_selected(self) -> None:
        user = _user(cred_id=None)
        db = AsyncMock()
        with self.assertRaises(HTTPException) as ctx:
            await _resolve_credential(db, user, None)
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_resolve_credential_rejects_wrong_type(self) -> None:
        user = _user(cred_id=uuid.uuid4())
        db = AsyncMock()
        with patch(
            "app.api.voice.get_accessible_credential",
            AsyncMock(return_value=_credential(CredentialType.openai)),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await _resolve_credential(db, user, None)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_synthesize_returns_audio(self) -> None:
        user = _user(cred_id=uuid.uuid4(), voice_id="v1")
        db = AsyncMock()
        with (
            patch("app.api.voice._resolve_credential", AsyncMock(return_value=("sk", _credential()))),
            patch("app.api.voice.text_to_speech", AsyncMock(return_value=b"AUDIO")),
        ):
            response = await synthesize(TtsRequest(text="hi"), current_user=user, db=db)
        self.assertEqual(response.body, b"AUDIO")
        self.assertEqual(response.media_type, "audio/mpeg")

    async def test_synthesize_400_when_no_voice(self) -> None:
        user = _user(cred_id=uuid.uuid4(), voice_id=None)
        db = AsyncMock()
        with patch(
            "app.api.voice._resolve_credential", AsyncMock(return_value=("sk", _credential()))
        ):
            with self.assertRaises(HTTPException) as ctx:
                await synthesize(TtsRequest(text="hi"), current_user=user, db=db)
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_transcribe_returns_text(self) -> None:
        user = _user(cred_id=uuid.uuid4())
        db = AsyncMock()
        upload = MagicMock()
        upload.filename = "a.webm"
        upload.content_type = "audio/webm"
        upload.read = AsyncMock(return_value=b"AUDIO")
        with (
            patch("app.api.voice._resolve_credential", AsyncMock(return_value=("sk", _credential()))),
            patch(
                "app.api.voice.speech_to_text",
                AsyncMock(return_value={"text": "hello", "language_code": "en"}),
            ),
        ):
            result = await transcribe(file=upload, credential_id=None, current_user=user, db=db)
        self.assertEqual(result, {"text": "hello", "language_code": "en"})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_voice_api.py -v`
Expected: FAIL — module `app.api.voice` does not exist.

- [ ] **Step 3: Implement the router**

```python
# backend/app/api/voice.py
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.models import Credential, CredentialType, User
from app.db.session import get_db
from app.services.credential_access import get_accessible_credential
from app.services.elevenlabs_service import (
    ElevenLabsError,
    list_voices,
    speech_to_text,
    text_to_speech,
)
from app.services.encryption import decrypt_config

router = APIRouter()


class VoiceInfo(BaseModel):
    voice_id: str
    name: str


class TtsRequest(BaseModel):
    text: str
    voice_id: str | None = None
    credential_id: uuid.UUID | None = None


class SttResponse(BaseModel):
    text: str
    language_code: str


async def _resolve_credential(
    db: AsyncSession, user: User, credential_id: uuid.UUID | None
) -> tuple[str, Credential]:
    """Return (api_key, credential) for the request override or the user default."""
    target_id = credential_id or user.tts_credential_id
    if target_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No ElevenLabs credential selected",
        )
    credential = await get_accessible_credential(db, target_id, user.id)
    if credential is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    if credential.type != CredentialType.elevenlabs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential must be an ElevenLabs credential",
        )
    config = decrypt_config(credential.encrypted_config)
    return config["api_key"], credential


@router.get("/voices", response_model=list[VoiceInfo])
async def get_voices(
    credential_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VoiceInfo]:
    api_key, _ = await _resolve_credential(db, current_user, credential_id)
    try:
        voices = await list_voices(api_key)
    except ElevenLabsError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return [VoiceInfo(**v) for v in voices]


@router.post("/tts")
async def synthesize(
    body: TtsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="text is required")
    api_key, _ = await _resolve_credential(db, current_user, body.credential_id)
    voice_id = body.voice_id or current_user.tts_voice_id
    if not voice_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No voice selected")
    try:
        audio = await text_to_speech(api_key, text, voice_id)
    except ElevenLabsError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return Response(content=audio, media_type="audio/mpeg")


@router.post("/stt", response_model=SttResponse)
async def transcribe(
    file: UploadFile = File(...),
    credential_id: uuid.UUID | None = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    api_key, _ = await _resolve_credential(db, current_user, credential_id)
    audio = await file.read()
    try:
        return await speech_to_text(
            api_key, audio, file.filename or "audio.webm", file.content_type or "audio/webm"
        )
    except ElevenLabsError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
```

- [ ] **Step 4: Register the router in `main.py`**

After the chats router line (`app.include_router(chats.router, prefix="/api/chats", ...)`, line 233), add the import to the existing `from app.api import (...)` block (`voice`) and:

```python
app.include_router(voice.router, prefix="/api/voice", tags=["Voice"])
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_voice_api.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Format, lint, full backend suite, commit**

```bash
cd backend && uv run ruff format . && uv run ruff check . && uv run pytest tests/test_voice_api.py tests/test_elevenlabs_service.py tests/test_credential_elevenlabs.py tests/test_user_tts_preferences.py -q
git add backend/app/api/voice.py backend/app/main.py backend/tests/test_voice_api.py
git commit -m "feat(voice): add /api/voice router (voices/tts/stt)"
```

---

## Task 6: Frontend — credential type + CredentialDialog elevenlabs field

**Files:**
- Modify: `frontend/src/types/credential.ts`
- Modify: `frontend/src/components/Credentials/CredentialDialog.vue`

- [ ] **Step 1: Add the type in `credential.ts`**

Add `| "elevenlabs"` to the `CredentialType` union. Add the config interface near the other configs:

```typescript
export interface CredentialConfigElevenLabs {
  api_key: string;
}
```

Add `| CredentialConfigElevenLabs` to the `CredentialConfig` union. Add entries to both label maps:

```typescript
// in CREDENTIAL_TYPE_LABELS
  elevenlabs: "ElevenLabs (Voice)",
// in CREDENTIAL_TYPE_DESCRIPTIONS
  elevenlabs: "Text-to-speech and speech-to-text for chat voice features",
```

- [ ] **Step 2: Add `presetType` prop + elevenlabs field in `CredentialDialog.vue`**

Extend `Props` (line 22):

```typescript
interface Props {
  open: boolean;
  credential?: Credential | null;
  presetType?: CredentialType;
}
```

In the `watch(() => props.open, ...)` open handler, in the create (non-editing) branch where it sets `type.value = "openai"` (line 164), use the preset:

```typescript
        type.value = props.presetType ?? "openai";
```

Add `elevenlabs` to `typeOptions` (after the openai entry, line 90):

```typescript
  { value: "elevenlabs", label: CREDENTIAL_TYPE_LABELS.elevenlabs },
```

Extend the API-key field `v-if` (line 640) to include elevenlabs:

```vue
        v-if="type === 'openai' || type === 'google' || type === 'elevenlabs'"
```

Extend the validity computed (line 219):

```typescript
  if (type.value === "openai" || type.value === "google" || type.value === "elevenlabs") {
    return !!apiKey.value.trim() || isEditing.value;
```

Extend the config builder (line 283 area) — add a branch returning the api_key:

```typescript
  if (type.value === "openai" || type.value === "elevenlabs") {
    return { api_key: apiKey.value };
  }
```

(Merge with the existing openai branch so both map to `{ api_key }`.)

- [ ] **Step 3: Verify**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS (no errors).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/credential.ts frontend/src/components/Credentials/CredentialDialog.vue
git commit -m "feat(voice): add elevenlabs credential type to frontend dialog"
```

---

## Task 7: Frontend — auth types + voiceApi service

**Files:**
- Modify: `frontend/src/types/auth.ts`
- Modify: `frontend/src/services/api.ts`

- [ ] **Step 1: Extend the `User` and `UserUpdateRequest` types**

In `frontend/src/types/auth.ts`:

```typescript
export interface User {
  id: string;
  email: string;
  name: string;
  user_rules: string | null;
  tts_credential_id: string | null;
  tts_voice_id: string | null;
  created_at: string;
}

export interface UserUpdateRequest {
  name?: string;
  user_rules?: string;
  tts_credential_id?: string | null;
  tts_voice_id?: string | null;
}
```

- [ ] **Step 2: Add `voiceApi` and its types in `api.ts`**

Near the top type exports (or alongside `credentialsApi`) add the result types and the service. Place `voiceApi` right after the `credentialsApi` export block:

```typescript
export interface VoiceInfo {
  voice_id: string;
  name: string;
}

export interface SttResult {
  text: string;
  language_code: string;
}

export const voiceApi = {
  listVoices: async (credentialId?: string): Promise<VoiceInfo[]> => {
    const response = await api.get<VoiceInfo[]>("/voice/voices", {
      params: credentialId ? { credential_id: credentialId } : undefined,
    });
    return response.data;
  },
  tts: async (
    text: string,
    opts?: { voiceId?: string; credentialId?: string },
  ): Promise<Blob> => {
    const response = await api.post(
      "/voice/tts",
      { text, voice_id: opts?.voiceId, credential_id: opts?.credentialId },
      { responseType: "blob" },
    );
    return response.data as Blob;
  },
  stt: async (blob: Blob): Promise<SttResult> => {
    const formData = new FormData();
    formData.append("file", blob, "audio.webm");
    const response = await api.post<SttResult>("/voice/stt", formData, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return response.data;
  },
};
```

- [ ] **Step 3: Verify**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/auth.ts frontend/src/services/api.ts
git commit -m "feat(voice): add voiceApi + tts user fields to frontend types"
```

---

## Task 8: Frontend — `useTextToSpeech` composable + `voice` store

**Files:**
- Create: `frontend/src/composables/useTextToSpeech.ts`
- Create: `frontend/src/stores/voice.ts`

- [ ] **Step 1: Implement `useTextToSpeech.ts`**

```typescript
import { computed, ref, type ComputedRef, type Ref } from "vue";

import { voiceApi } from "@/services/api";
import { useAuthStore } from "@/stores/auth";

const audio = typeof Audio !== "undefined" ? new Audio() : null;
const playingId = ref<string | null>(null);
let currentUrl: string | null = null;

if (audio) {
  audio.addEventListener("ended", () => {
    playingId.value = null;
    if (currentUrl) {
      URL.revokeObjectURL(currentUrl);
      currentUrl = null;
    }
  });
}

function stop(): void {
  if (audio) {
    audio.pause();
    audio.currentTime = 0;
  }
  if (currentUrl) {
    URL.revokeObjectURL(currentUrl);
    currentUrl = null;
  }
  playingId.value = null;
}

interface UseTextToSpeech {
  playingId: Ref<string | null>;
  isConfigured: ComputedRef<boolean>;
  speak: (id: string, text: string) => Promise<void>;
  stop: () => void;
}

export function useTextToSpeech(): UseTextToSpeech {
  const authStore = useAuthStore();
  const isConfigured = computed(
    () => !!authStore.user?.tts_credential_id && !!authStore.user?.tts_voice_id,
  );

  async function speak(id: string, text: string): Promise<void> {
    if (!audio) return;
    if (playingId.value === id) {
      stop();
      return;
    }
    stop();
    const trimmed = text.trim();
    if (!trimmed) return;
    const blob = await voiceApi.tts(trimmed);
    currentUrl = URL.createObjectURL(blob);
    audio.src = currentUrl;
    playingId.value = id;
    await audio.play();
  }

  return { playingId, isConfigured, speak, stop };
}
```

- [ ] **Step 2: Implement the `voice` store**

```typescript
// frontend/src/stores/voice.ts
import { defineStore } from "pinia";
import { ref } from "vue";

export const useVoiceStore = defineStore("voice", () => {
  // Incremented to ask the app shell to open User Settings on the Voice tab.
  const openVoiceSettingsSignal = ref(0);

  function requestVoiceSettings(): void {
    openVoiceSettingsSignal.value += 1;
  }

  return { openVoiceSettingsSignal, requestVoiceSettings };
});
```

- [ ] **Step 3: Verify**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/composables/useTextToSpeech.ts frontend/src/stores/voice.ts
git commit -m "feat(voice): add useTextToSpeech composable + voice store"
```

---

## Task 9: Frontend — Voice tab in UserSettingsDialog + AppHeader wiring

**Files:**
- Modify: `frontend/src/components/Layout/UserSettingsDialog.vue`
- Modify: `frontend/src/components/Layout/AppHeader.vue`

- [ ] **Step 1: Add the Voice tab to `UserSettingsDialog.vue`**

Add an `initialTab` prop and extend the tab union. In `<script setup>`:

```typescript
import { computed, ref, watch } from "vue";

import CredentialDialog from "@/components/Credentials/CredentialDialog.vue";
import Select from "@/components/ui/Select.vue";
import { credentialsApi, voiceApi, type VoiceInfo } from "@/services/api";
import type { CredentialListItem } from "@/types/credential";
import type { Credential } from "@/types/credential";

const props = defineProps<{
  open: boolean;
  initialTab?: "profile" | "security" | "voice";
}>();

const activeTab = ref<"profile" | "security" | "voice">("profile");

const elevenlabsCredentials = ref<CredentialListItem[]>([]);
const voices = ref<VoiceInfo[]>([]);
const selectedTtsCredentialId = ref<string>("");
const selectedVoiceId = ref<string>("");
const loadingVoices = ref(false);
const voiceError = ref<string | null>(null);
const savingVoice = ref(false);
const showAddCredential = ref(false);

const credentialOptions = computed(() => [
  { value: "", label: "Select a credential" },
  ...elevenlabsCredentials.value.map((c) => ({ value: c.id, label: c.name })),
]);
const voiceOptions = computed(() => [
  { value: "", label: "Select a voice" },
  ...voices.value.map((v) => ({ value: v.voice_id, label: v.name })),
]);

async function loadElevenLabsCredentials(): Promise<void> {
  elevenlabsCredentials.value = await credentialsApi.listByType("elevenlabs");
}

async function loadVoices(): Promise<void> {
  if (!selectedTtsCredentialId.value) {
    voices.value = [];
    return;
  }
  loadingVoices.value = true;
  voiceError.value = null;
  try {
    voices.value = await voiceApi.listVoices(selectedTtsCredentialId.value);
  } catch {
    voiceError.value = "Could not load voices. Check the credential.";
    voices.value = [];
  } finally {
    loadingVoices.value = false;
  }
}

watch(selectedTtsCredentialId, () => {
  void loadVoices();
});

function onCredentialAdded(credential: Credential): void {
  showAddCredential.value = false;
  void loadElevenLabsCredentials().then(() => {
    selectedTtsCredentialId.value = credential.id;
  });
}

async function handleSaveVoice(): Promise<void> {
  savingVoice.value = true;
  try {
    await authStore.updateUser({
      tts_credential_id: selectedTtsCredentialId.value || null,
      tts_voice_id: selectedVoiceId.value || null,
    });
    emit("close");
  } finally {
    savingVoice.value = false;
  }
}
```

Extend the existing open-`watch` so it initializes the Voice tab state (add to the body where it sets `name.value` etc.):

```typescript
      activeTab.value = props.initialTab ?? "profile";
      selectedTtsCredentialId.value = authStore.user.tts_credential_id ?? "";
      selectedVoiceId.value = authStore.user.tts_voice_id ?? "";
      void loadElevenLabsCredentials().then(loadVoices);
```

In the `<template>`, add a third tab button after the Security button:

```vue
        <button
          type="button"
          class="px-3 py-2 text-sm font-medium transition-colors border-b-2 -mb-px"
          :class="activeTab === 'voice' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'"
          @click="activeTab = 'voice'"
        >
          Voice
        </button>
```

Add the Voice panel after the security `<form>` (still inside the `space-y-5` wrapper):

```vue
      <div
        v-if="activeTab === 'voice'"
        class="space-y-5"
      >
        <div class="space-y-2">
          <Label>ElevenLabs Credential</Label>
          <p class="text-xs text-muted-foreground">
            Used to read messages aloud and power interactive voice mode in chat.
          </p>
          <Select
            v-model="selectedTtsCredentialId"
            :options="credentialOptions"
          />
          <Button
            variant="outline"
            type="button"
            class="mt-1"
            @click="showAddCredential = true"
          >
            Add credential
          </Button>
        </div>

        <div class="space-y-2">
          <Label>Voice</Label>
          <Select
            v-model="selectedVoiceId"
            :options="voiceOptions"
            :disabled="!selectedTtsCredentialId || loadingVoices"
          />
          <p
            v-if="voiceError"
            class="text-xs text-destructive"
          >
            {{ voiceError }}
          </p>
        </div>

        <div class="flex justify-end gap-3 pt-2">
          <Button
            variant="outline"
            type="button"
            @click="emit('close')"
          >
            Cancel
          </Button>
          <Button
            type="button"
            :loading="savingVoice"
            :disabled="!selectedTtsCredentialId || !selectedVoiceId"
            @click="handleSaveVoice"
          >
            Save Voice Settings
          </Button>
        </div>
      </div>

      <CredentialDialog
        :open="showAddCredential"
        preset-type="elevenlabs"
        @close="showAddCredential = false"
        @saved="onCredentialAdded"
      />
```

- [ ] **Step 2: Wire AppHeader to open the Voice tab**

In `frontend/src/components/Layout/AppHeader.vue` `<script setup>`, add:

```typescript
import { ref, watch } from "vue";
import { useVoiceStore } from "@/stores/voice";

const voiceStore = useVoiceStore();
const settingsInitialTab = ref<"profile" | "security" | "voice">("profile");

watch(
  () => voiceStore.openVoiceSettingsSignal,
  () => {
    settingsInitialTab.value = "voice";
    showSettingsDialog.value = true;
  },
);
```

(Reset to `profile` when the user opens settings via the menu — in the existing `@click="showSettingsDialog = true; pushOverlayState()"` handler at line 105, also set `settingsInitialTab = 'profile'`.)

Update the `<UserSettingsDialog>` usage (line 163) to pass the tab:

```vue
    <UserSettingsDialog
      :open="showSettingsDialog"
      :initial-tab="settingsInitialTab"
      @close="showSettingsDialog = false"
    />
```

- [ ] **Step 3: Verify**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS. Manually confirm `Select` and `CredentialListItem` import paths resolve (Select is at `@/components/ui/Select.vue`).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Layout/UserSettingsDialog.vue frontend/src/components/Layout/AppHeader.vue
git commit -m "feat(voice): add Voice tab to user settings + open-from-chat wiring"
```

---

## Task 10: Frontend — per-message read-aloud button in ChatConversation

**Files:**
- Modify: `frontend/src/components/Chat/ChatConversation.vue` (icon imports line ~5-12; copy button block line 903-918)

- [ ] **Step 1: Add imports and composable usage in `<script setup>`**

Add to the `lucide-vue-next` import list: `Volume2`, `Square`, `AudioLines`. Add:

```typescript
import { useTextToSpeech } from "@/composables/useTextToSpeech";
import { useVoiceStore } from "@/stores/voice";

const tts = useTextToSpeech();
const voiceStore = useVoiceStore();

function plainTextFromMarkdown(markdown: string): string {
  const div = document.createElement("div");
  div.innerHTML = renderMarkdown(markdown);
  return (div.textContent || div.innerText || "").trim();
}

async function readMessageAloud(msg: Message): Promise<void> {
  if (!tts.isConfigured.value) {
    voiceStore.requestVoiceSettings();
    return;
  }
  try {
    await tts.speak(msg.id, plainTextFromMarkdown(msg.content));
  } catch {
    // playback/synthesis failure is non-fatal; button simply resets
    tts.stop();
  }
}
```

(`renderMarkdown` already exists in this file and is used at line 933.)

- [ ] **Step 2: Add the read-aloud button next to Copy in the template**

Immediately after the existing copy `<button>` (closes at line 918), add a sibling button. Adjust its `right-*` so the two sit side by side (copy stays at `right-1.5`; place read-aloud at `right-9`):

```vue
            <button
              type="button"
              class="absolute right-9 top-1.5 flex h-7 w-7 items-center justify-center rounded-lg text-current opacity-60 transition-opacity hover:bg-black/10 sm:opacity-0 sm:group-hover/message:opacity-70 hover:opacity-100"
              :title="tts.playingId.value === msg.id ? 'Stop' : 'Read aloud'"
              :aria-label="tts.playingId.value === msg.id ? 'Stop reading' : 'Read message aloud'"
              @click="readMessageAloud(msg)"
            >
              <Square
                v-if="tts.playingId.value === msg.id"
                class="w-3.5 h-3.5"
              />
              <Volume2
                v-else
                class="w-3.5 h-3.5"
              />
            </button>
```

This button is inside the shared `v-for="msg in messages"` bubble, so it renders for **both** user and assistant roles (matching the copy button). The bubble already has `pr-10`; widen to `pr-[4.5rem]` on the message container `:class` (line 896, the `'group/message relative rounded-2xl px-4 py-2.5 pr-10 ...'` string) so two buttons fit:

```
'group/message relative rounded-2xl px-4 py-2.5 pr-[4.25rem] text-sm leading-relaxed break-words',
```

- [ ] **Step 3: Verify**

Run: `cd frontend && bun run typecheck && bun run lint`
Expected: PASS. Manually: a speaker icon appears left of the copy icon on hover for both sides; clicking with no voice configured opens User Settings → Voice tab; with voice configured it plays and toggles to a stop square.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/Chat/ChatConversation.vue
git commit -m "feat(voice): add per-message read-aloud button in chat"
```

---

## Task 11: Frontend — interactive voice mode (composable + overlay + entry button)

**Files:**
- Create: `frontend/src/composables/useInteractiveVoice.ts`
- Create: `frontend/src/components/Chat/InteractiveVoiceMode.vue`
- Modify: `frontend/src/components/Chat/ChatConversation.vue`

- [ ] **Step 1: Implement `useInteractiveVoice.ts`**

State machine with mic capture, client-side VAD (Web Audio RMS + silence timeout), STT, and a `mute` flag. It does NOT own sending or TTS — the component drives those — keeping this composable testable as a pure recorder.

```typescript
import { ref, type Ref } from "vue";

import { voiceApi } from "@/services/api";

export type VoiceState = "idle" | "listening" | "transcribing" | "thinking" | "speaking";

const SILENCE_MS = 1200;
const SPEECH_RMS = 0.025;

interface UseInteractiveVoice {
  state: Ref<VoiceState>;
  muted: Ref<boolean>;
  error: Ref<string | null>;
  start: () => Promise<void>;
  stopListening: () => void;
  toggleMute: () => void;
  setState: (s: VoiceState) => void;
  teardown: () => void;
}

export function useInteractiveVoice(onUtterance: (text: string) => void): UseInteractiveVoice {
  const state = ref<VoiceState>("idle");
  const muted = ref(false);
  const error = ref<string | null>(null);

  let stream: MediaStream | null = null;
  let audioCtx: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let recorder: MediaRecorder | null = null;
  let chunks: Blob[] = [];
  let rafId: number | null = null;
  let silenceTimer: number | null = null;
  let speechStarted = false;

  function setState(s: VoiceState): void {
    state.value = s;
  }

  function rms(buffer: Float32Array): number {
    let sum = 0;
    for (let i = 0; i < buffer.length; i += 1) sum += buffer[i] * buffer[i];
    return Math.sqrt(sum / buffer.length);
  }

  function beginRecording(): void {
    if (!stream) return;
    chunks = [];
    speechStarted = false;
    recorder = new MediaRecorder(stream);
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: recorder?.mimeType || "audio/webm" });
      if (speechStarted && blob.size > 0) {
        void transcribe(blob);
      } else if (!muted.value) {
        beginRecording();
        monitor();
      }
    };
    recorder.start();
  }

  async function transcribe(blob: Blob): Promise<void> {
    setState("transcribing");
    try {
      const result = await voiceApi.stt(blob);
      const text = result.text.trim();
      if (text) {
        onUtterance(text);
      } else if (!muted.value) {
        listen();
      }
    } catch {
      error.value = "Transcription failed.";
      if (!muted.value) listen();
    }
  }

  function monitor(): void {
    if (!analyser) return;
    const data = new Float32Array(analyser.fftSize);
    const tick = (): void => {
      if (!analyser || muted.value || recorder?.state !== "recording") return;
      analyser.getFloatTimeDomainData(data);
      const level = rms(data);
      if (level > SPEECH_RMS) {
        speechStarted = true;
        if (silenceTimer) {
          window.clearTimeout(silenceTimer);
          silenceTimer = null;
        }
      } else if (speechStarted && silenceTimer === null) {
        silenceTimer = window.setTimeout(() => {
          if (recorder?.state === "recording") recorder.stop();
        }, SILENCE_MS);
      }
      rafId = window.requestAnimationFrame(tick);
    };
    rafId = window.requestAnimationFrame(tick);
  }

  function listen(): void {
    if (muted.value) return;
    setState("listening");
    beginRecording();
    monitor();
  }

  async function start(): Promise<void> {
    error.value = null;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") {
      error.value = "Voice input is not supported in this browser.";
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      error.value = "Microphone permission denied.";
      return;
    }
    audioCtx = new AudioContext();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    audioCtx.createMediaStreamSource(stream).connect(analyser);
    listen();
  }

  function stopListening(): void {
    if (silenceTimer) {
      window.clearTimeout(silenceTimer);
      silenceTimer = null;
    }
    if (rafId) {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
    if (recorder?.state === "recording") {
      recorder.onstop = null;
      recorder.stop();
    }
  }

  function toggleMute(): void {
    muted.value = !muted.value;
    if (muted.value) {
      stopListening();
      setState("idle");
    } else {
      listen();
    }
  }

  function teardown(): void {
    stopListening();
    stream?.getTracks().forEach((t) => t.stop());
    void audioCtx?.close();
    stream = null;
    audioCtx = null;
    analyser = null;
    recorder = null;
    setState("idle");
  }

  return { state, muted, error, start, stopListening, toggleMute, setState, teardown };
}
```

- [ ] **Step 2: Implement `InteractiveVoiceMode.vue`**

Receives the conversation messages, a streaming flag, and an `onSend` callback. Watches for the assistant reply to finish, then plays TTS and resumes listening. Theme-aware via Tailwind tokens; responsive; orb reflects state; mute + close controls.

```vue
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { Mic, MicOff, X } from "lucide-vue-next";

import type { Message } from "@/types/chat";
import { useInteractiveVoice, type VoiceState } from "@/composables/useInteractiveVoice";
import { useTextToSpeech } from "@/composables/useTextToSpeech";

const props = defineProps<{
  open: boolean;
  messages: Message[];
  isStreaming: boolean;
  onSend: (text: string) => Promise<void> | void;
}>();

const emit = defineEmits<{ close: [] }>();

const tts = useTextToSpeech();
const lastUserText = ref("");
const lastAssistantText = ref("");
let spokenForMessageId: string | null = null;

const voice = useInteractiveVoice((text: string) => {
  lastUserText.value = text;
  voice.setState("thinking");
  void props.onSend(text);
});

const stateLabel: Record<VoiceState, string> = {
  idle: "Paused",
  listening: "Listening…",
  transcribing: "Transcribing…",
  thinking: "Thinking…",
  speaking: "Speaking…",
};

// When the assistant finishes streaming a new reply, speak it then resume listening.
watch(
  () => props.isStreaming,
  async (streaming, wasStreaming) => {
    if (wasStreaming && !streaming && props.open) {
      const last = props.messages[props.messages.length - 1];
      if (last && last.role === "assistant" && last.id !== spokenForMessageId) {
        spokenForMessageId = last.id;
        lastAssistantText.value = last.content;
        voice.setState("speaking");
        try {
          await tts.speak(`iv-${last.id}`, stripMarkdown(last.content));
        } catch {
          /* ignore */
        }
        await waitForPlaybackEnd();
        if (props.open && !voice.muted.value) voice.start();
      }
    }
  },
);

function stripMarkdown(text: string): string {
  const div = document.createElement("div");
  div.textContent = text;
  return (div.textContent || "").trim();
}

function waitForPlaybackEnd(): Promise<void> {
  return new Promise((resolve) => {
    const id = window.setInterval(() => {
      if (tts.playingId.value === null) {
        window.clearInterval(id);
        resolve();
      }
    }, 150);
  });
}

watch(
  () => props.open,
  async (open) => {
    if (open) {
      lastUserText.value = "";
      lastAssistantText.value = "";
      spokenForMessageId = null;
      await voice.start();
    } else {
      voice.teardown();
      tts.stop();
    }
  },
);

function close(): void {
  voice.teardown();
  tts.stop();
  emit("close");
}

onBeforeUnmount(() => {
  voice.teardown();
  tts.stop();
});
</script>

<template>
  <div
    v-if="open"
    class="fixed inset-0 z-50 flex flex-col items-center justify-between bg-background/95 backdrop-blur-md px-6 py-10 sm:py-16"
  >
    <button
      type="button"
      class="absolute right-4 top-4 flex h-10 w-10 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground"
      aria-label="Close voice mode"
      @click="close"
    >
      <X class="h-5 w-5" />
    </button>

    <div class="flex flex-1 flex-col items-center justify-center gap-8">
      <div
        class="relative flex h-40 w-40 items-center justify-center rounded-full bg-primary/10 sm:h-52 sm:w-52"
        :class="{
          'animate-pulse': voice.state.value === 'listening' || voice.state.value === 'speaking',
        }"
      >
        <div
          class="h-24 w-24 rounded-full bg-primary/30 transition-transform duration-300 sm:h-32 sm:w-32"
          :class="{
            'scale-110': voice.state.value === 'speaking',
            'scale-90': voice.state.value === 'idle',
          }"
        />
      </div>
      <p class="text-sm font-medium text-muted-foreground">
        {{ stateLabel[voice.state.value] }}
      </p>
      <p
        v-if="lastUserText"
        class="max-w-md text-center text-sm text-foreground/80"
      >
        “{{ lastUserText }}”
      </p>
      <p
        v-if="voice.error.value"
        class="text-xs text-destructive"
      >
        {{ voice.error.value }}
      </p>
    </div>

    <div class="flex items-center gap-6">
      <button
        type="button"
        class="flex h-16 w-16 items-center justify-center rounded-full border border-border transition-colors"
        :class="voice.muted.value ? 'bg-muted text-muted-foreground' : 'bg-primary text-primary-foreground'"
        :aria-label="voice.muted.value ? 'Unmute microphone' : 'Mute microphone'"
        @click="voice.toggleMute()"
      >
        <MicOff
          v-if="voice.muted.value"
          class="h-6 w-6"
        />
        <Mic
          v-else
          class="h-6 w-6"
        />
      </button>
    </div>
  </div>
</template>
```

- [ ] **Step 3: Wire the entry button + overlay into `ChatConversation.vue`**

In `<script setup>`, add `AudioLines` to the lucide import (done in Task 10) and:

```typescript
import InteractiveVoiceMode from "@/components/Chat/InteractiveVoiceMode.vue";

const interactiveVoiceOpen = ref(false);

function openInteractiveVoice(): void {
  if (!tts.isConfigured.value) {
    voiceStore.requestVoiceSettings();
    return;
  }
  interactiveVoiceOpen.value = true;
}

async function sendVoiceText(text: string): Promise<void> {
  if (!selectedCredentialId.value || !selectedModel.value) return;
  await chatStore.sendMessage(props.conversationId, text, selectedCredentialId.value, selectedModel.value);
}
```

In the input bar (`<div class="chat-input-area ...">`, line 1158), add an entry button next to the existing dictation mic / Send control:

```vue
        <button
          type="button"
          class="flex h-9 w-9 items-center justify-center rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground"
          title="Interactive voice mode"
          aria-label="Open interactive voice mode"
          @click="openInteractiveVoice"
        >
          <AudioLines class="h-5 w-5" />
        </button>
```

Mount the overlay at the root of the component template (sibling of the outermost chat container):

```vue
    <InteractiveVoiceMode
      :open="interactiveVoiceOpen"
      :messages="messages"
      :is-streaming="isThisConvStreaming"
      :on-send="sendVoiceText"
      @close="interactiveVoiceOpen = false"
    />
```

(`messages` and `isThisConvStreaming` are existing reactive values in this component — see line 170/883.)

- [ ] **Step 4: Verify**

Run: `cd frontend && bun run typecheck && bun run lint && bun run build`
Expected: PASS (build included because this adds a substantial component). Manual smoke test: clicking the waveform button with voice unconfigured opens settings; configured opens the overlay, requests mic permission, listens, transcribes on silence, sends, speaks the reply, and resumes; mute pauses; X closes and releases the mic.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/useInteractiveVoice.ts frontend/src/components/Chat/InteractiveVoiceMode.vue frontend/src/components/Chat/ChatConversation.vue
git commit -m "feat(voice): add interactive hands-free voice mode to chat"
```

---

## Task 12: Docs + full verification

**Files:**
- Docs via the `heym-documentation` skill (new credential type, Voice settings, interactive voice mode).

- [ ] **Step 1: Update feature documentation**

Invoke the `heym-documentation` skill and add/extend docs covering: the ElevenLabs credential type, the User Settings → Voice tab, per-message read-aloud, and interactive voice mode (scope: `/chat` only).

- [ ] **Step 2: Run the full project check**

Run: `./check.sh`
Expected: backend `ruff format`/`ruff check` clean, frontend lint + typecheck clean, backend test suite green (includes the four new test files).

- [ ] **Step 3: Apply migrations on a clean DB to confirm ordering**

Run: `cd backend && uv run alembic upgrade head`
Expected: `072` then `073` apply cleanly.

- [ ] **Step 4: Commit any doc/format changes**

```bash
git add -A
git commit -m "docs(voice): document elevenlabs chat voice features"
```

---

## Self-Review

**Spec coverage:**
- Spec §1 per-message read-aloud (both roles) → Task 10.
- Spec §2 interactive mode (mobile/web/light/dark, hands-free, mute) → Task 11.
- Spec §3 credential under credentials → Tasks 1, 6.
- Spec §4 credential selected from User profile dialog → Task 9.
- Spec §5 not-configured → opens dialog to relevant field → Tasks 8 (`voice` store), 9 (`initialTab`), 10/11 (trigger).
- Spec §6 Add credential button in the dialog → Task 9.
- STT = ElevenLabs Scribe, TTS = multilingual, backend proxy, user-stored voice → Tasks 4, 5, 2, 3.
- Tests (required) → Tasks 1, 3, 4, 5.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; frontend steps verify via typecheck/lint/build (repo has no frontend test runner).

**Type consistency:** `_resolve_credential` returns `(api_key, credential)` and is used consistently in Task 5 handlers and tests. `voiceApi.tts/stt/listVoices`, `VoiceInfo`, `SttResult`, `useTextToSpeech().{playingId,isConfigured,speak,stop}`, `useInteractiveVoice(onUtterance).{state,muted,error,start,stopListening,toggleMute,setState,teardown}`, and `useVoiceStore().{openVoiceSettingsSignal,requestVoiceSettings}` are referenced with matching names across tasks. User fields `tts_credential_id`/`tts_voice_id` are consistent across backend schema, frontend types, store, and composable.
