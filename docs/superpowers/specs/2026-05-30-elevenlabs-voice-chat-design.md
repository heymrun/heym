# ElevenLabs Voice for Chat (TTS + STT) — Design

**Date:** 2026-05-30
**Scope:** `/chat` tab only ([ChatConversation.vue](../../../frontend/src/components/Chat/ChatConversation.vue)). The public Chat Portal ([ChatPortalView.vue](../../../frontend/src/views/ChatPortalView.vue)) is explicitly out of scope.

## Goal

Add ElevenLabs-powered voice to the internal chat:

1. **Per-message read-aloud** button next to the existing Copy button, on **both** user and assistant messages.
2. **Interactive voice mode** — a full-screen, theme-aware (light/dark), mobile + web responsive overlay (ChatGPT voice-mode feel) with hands-free turn-taking and a mic mute control.
3. ElevenLabs added as a new **credential type**.
4. The TTS credential is selected from the **User profile** dialog (UserSettingsDialog).
5. Users who have not set up voice yet: pressing the read-aloud / interactive button opens the User Settings dialog directly on the Voice section.
6. That Voice section also contains an **Add credential** button.

## Decisions (approved)

- **Architecture:** Backend proxy, turn-based REST (not WebSocket streaming). The API key never reaches the browser. Follows the existing `get_accessible_credential` + `decrypt_config` + `httpx` pattern (mirrors [chats.py](../../../backend/app/api/chats.py)).
- **STT:** ElevenLabs **Scribe** (`scribe_v1`), not the browser Web Speech API. Scribe auto-detects the spoken language (TR/EN and 99 others), works in every browser via `MediaRecorder`, and needs no language toggle.
- **TTS output language:** automatic — `eleven_multilingual_v2` detects the text language, and the LLM already replies in the user's language, so TR input → TR voice, EN input → EN voice.
- **Turn-taking:** hands-free / automatic. Client-side VAD (Web Audio `AnalyserNode` RMS + silence timeout) detects end of utterance. A **mute** button pauses listening; an **X** exits the mode.
- **Voice/model storage:** voice is a **user preference** (voice picker), not stored in the credential. TTS/STT models are backend constants for v1 (`eleven_multilingual_v2`, `scribe_v1`), not user-configurable.
- **Conversation:** interactive mode shares the **same** chat conversation / store as the text chat — it is an alternate UI over the same messages, not a separate session.
- **User Settings:** a new third **Voice** tab is added next to Profile / Security in UserSettingsDialog.

## Backend

### Credential type
- Add `elevenlabs` to `CredentialType` enum ([schemas.py:439](../../../backend/app/models/schemas.py#L439)) and `CredentialConfigElevenLabs { api_key: str }` + add to the `CredentialConfig` union.
- Extend in [credentials.py](../../../backend/app/api/credentials.py): `validate_credential_config` (require non-empty `api_key`) and `get_masked_value` (mask `api_key` like the openai/google branch).
- The `by-type` endpoint already supports any `CredentialType`, so `GET /api/credentials/by-type/elevenlabs` works for free.

### User preference columns
- Add to `users` ([db/models.py:60](../../../backend/app/db/models.py#L60)):
  - `tts_credential_id: UUID | None` — FK → `credentials.id`, `ondelete="SET NULL"`, nullable.
  - `tts_voice_id: str | None` — `String(64)`, nullable.
- Update `UserUpdate` / `UserResponse` schemas and `PUT /api/auth/me` ([auth.py:215](../../../backend/app/api/auth.py#L215)) to read/write both fields. When `tts_credential_id` is set, validate it is accessible to the user and is type `elevenlabs` (else 400).

### `app/services/elevenlabs_service.py`
Thin async client (httpx), isolated and unit-testable. Base URL `https://api.elevenlabs.io`, auth header `xi-api-key`.
- `async def list_voices(api_key) -> list[VoiceInfo]` → `GET /v1/voices`, maps to `{ voice_id, name }`.
- `async def text_to_speech(api_key, text, voice_id, model_id="eleven_multilingual_v2") -> bytes` → `POST /v1/text-to-speech/{voice_id}`, returns `audio/mpeg` bytes.
- `async def speech_to_text(api_key, audio: bytes, filename, content_type) -> dict` → `POST /v1/speech-to-text` multipart (`model_id=scribe_v1`, `file=...`), returns `{ text, language_code }`.
- Upstream/network errors are raised as a typed error that the router converts to `HTTPException(502)`.

### `app/api/voice.py` — router `/api/voice`
All endpoints require `get_current_user`. Credential resolution helper: use `credential_id` from the request if given, else the user's `tts_credential_id`; load via `get_accessible_credential`; 404 if missing, 400 if not `elevenlabs`; `decrypt_config` → `api_key`.
- `GET /api/voice/voices?credential_id=` → `list_voices`. Used by the Voice settings picker.
- `POST /api/voice/tts` body `{ text, voice_id?, credential_id? }` → `StreamingResponse(media_type="audio/mpeg")`. Voice defaults to the user's `tts_voice_id`; 400 if no voice resolvable.
- `POST /api/voice/stt` multipart `file` (+ optional `credential_id`) → `{ text, language_code }`.
- Register in [main.py](../../../backend/app/main.py): `app.include_router(voice.router, prefix="/api/voice", tags=["Voice"])`.

### Migration
One Alembic migration: add `elevenlabs` to the `credential_type` Postgres enum (`ALTER TYPE credential_type ADD VALUE 'elevenlabs'`, non-transactional / `op.execute` with autocommit handling consistent with prior enum migrations) and add the two `users` columns.

## Frontend

### Service — `voiceApi` (api.ts)
- `listVoices(credentialId): Promise<VoiceInfo[]>`
- `tts(text, opts?): Promise<Blob>` (responseType blob)
- `stt(blob): Promise<{ text: string; language_code: string }>` (multipart)

### `useTextToSpeech()` composable
Owns a single shared `Audio` element (only one message plays at a time). Exposes `speak(id, text)`, `stop()`, reactive `playingId`, and `isConfigured` (derived from the auth store user's `tts_credential_id` + `tts_voice_id`). Used by both per-message buttons and interactive mode.

### `useVoiceStore` (Pinia)
Tiny bridge so chat components can ask AppHeader to open settings: `requestVoiceSettings()` sets a flag/target-tab that AppHeader watches to open `UserSettingsDialog` on the Voice tab. Avoids prop-drilling across the layout.

### Per-message read-aloud button — ChatConversation.vue
Add a speaker button immediately adjacent to the existing Copy button ([ChatConversation.vue:903](../../../frontend/src/components/Chat/ChatConversation.vue#L903)) on **both** roles' bubbles. `Volume2` icon, switching to `Square` while that message is playing. Click behavior: if `useTextToSpeech().isConfigured` is false → `useVoiceStore().requestVoiceSettings()`; otherwise `speak(msg.id, plainText(msg))` / `stop()` toggle.

### Interactive voice mode
- Entry button in the chat input bar (next to the existing dictation mic / Send at [ChatConversation.vue:1158](../../../frontend/src/components/Chat/ChatConversation.vue#L1158)). If not configured → open Voice settings instead.
- `InteractiveVoiceMode.vue` — full-screen fixed overlay, theme-aware via existing Tailwind dark classes, responsive for mobile + web. Center animated orb reflecting state (idle / listening / thinking / speaking), a mute toggle, and a close (X) button. Shows the live user transcript and the assistant's reply text.
- `useInteractiveVoice()` composable — state machine and orchestration, keeping the component thin:
  - `getUserMedia` + `MediaRecorder` capture; Web Audio `AnalyserNode` computes RMS to detect speech start and a silence timeout to detect end of utterance (VAD).
  - On utterance end → `voiceApi.stt(blob)` → push transcript through the existing `chatStore.sendMessage` flow (same conversation).
  - Watch the chat store until the latest assistant message finishes streaming → `useTextToSpeech().speak(...)` on its text → on audio end, resume listening.
  - Mute pauses the capture loop; X tears down media + recognizer and closes the overlay.
- Browser support: `getUserMedia` + `MediaRecorder` work in Firefox too, so Scribe-based STT works everywhere. If unsupported, hide the mic and offer read-aloud only (graceful fallback).

### User Settings — Voice tab (UserSettingsDialog.vue)
Third tab next to Profile / Security:
- ElevenLabs credential dropdown via `credentialsApi.listByType("elevenlabs")`.
- **Add credential** button → opens `CredentialDialog` with a new optional `presetType="elevenlabs"` prop ([CredentialDialog.vue:22](../../../frontend/src/components/Credentials/CredentialDialog.vue#L22)).
- Voice picker (`voiceApi.listVoices(credentialId)`), disabled until a credential is selected.
- Save → `authStore.updateUser({ tts_credential_id, tts_voice_id })`.
- When opened via the chat "not configured" path, the dialog opens directly on this tab.

### Type additions (frontend/src/types/credential.ts)
Add `elevenlabs` to `CredentialType`, `CredentialConfigElevenLabs`, the union, and the label/description maps.

## Error handling
- **Backend:** `HTTPException` only — 404 (credential not found), 400 (wrong type / missing api_key / unresolved voice), 502 (ElevenLabs upstream/network failure).
- **Frontend:** typed catches with axios handling; toast on failure; mic-permission-denied shows an inline message in interactive mode; "not configured" routes the user to the Voice settings tab.

## Testing (required)
- `backend/tests/test_voice_api.py` (new): tts / stt / voices happy paths and the 404 / 400 / 502 paths, credential resolution (request override vs user default), and wrong-type rejection — `elevenlabs_service` mocked with `AsyncMock` (and/or httpx transport mock).
- Extend credential tests: `elevenlabs` `validate_credential_config` and `get_masked_value`.
- Extend auth/user-update tests: setting `tts_credential_id` / `tts_voice_id`, including the wrong-type/inaccessible rejection.
- Frontend: no test runner today (per repo conventions) — covered by `bun run lint` + `bun run typecheck`.

## Out of scope (v1)
- Chat Portal voice.
- WebSocket / streaming low-latency pipeline and barge-in.
- User-selectable TTS/STT model IDs (fixed constants for v1).
- Replacing the existing Web Speech dictation in the input box ([ChatConversation.vue:512](../../../frontend/src/components/Chat/ChatConversation.vue#L512)) — left as-is.

## Feature documentation
Medium/large feature → update docs via the `heym-documentation` skill (new credential type, Voice settings, interactive voice mode) as part of implementation.
