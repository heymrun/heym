# Images, audio and plain-text files of any name in RAG uploads

Date: 2026-11-10
Repositories: heymrun (Heym), heym-work (Work)

## Problem

A vector store accepts only `.pdf`, `.md`, `.markdown`, `.txt`, `.csv` and `.json`
(`backend/app/api/vector_stores.py`, fixed list in `upload_file_to_vector_store`). Work's
Knowledge pages apply the same list before sending anything (`heym-work/frontend/src/lib/ragUpload.ts`).

Three gaps follow:

1. A photo of a document, a screenshot or a scanned page cannot go into a store, although the
   Converter node already reads images with Tesseract (`ocr_service.image_to_text`).
2. A voice note or call recording cannot go into a store, although the Converter node now
   transcribes audio with Whisper (`speech_to_text_service.audio_to_text`).
3. A UTF-8 text file whose name is not on the list (`notes`, `burak.akgun`) is refused. Chat
   attachments and workflow run inputs accept such files since #879 (`frontend/src/lib/textFileSniff.ts`);
   RAG uploads were left behind.

A fourth gap shows up next to them: a scanned PDF has no text layer, so pypdf extracts nothing and
the upload succeeds with 0 chunks and no message.

The workflow RAG node is not affected: its insert takes text, so Converter -> RAG insert already
works on the canvas. This change is about the two upload surfaces, Heym's Vector Stores tab and
Work's Knowledge pages.

## Behavior

| Dropped file | What Heym does | When |
|---|---|---|
| `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff`, `.webp`, `.bmp` | OCR with the Converter's Tesseract path, automatic language; the text is chunked like a text file | During the upload request |
| `.mp3`, `.wav`, `.ogg`, `.flac` | Transcription with the Converter's Whisper path, automatic language; chunks carry timing | In the background |
| `.pdf` | pypdf as today; pages that yield no text are read by OCR | During the request when every page has text, in the background otherwise |
| `.md`, `.markdown`, `.txt`, `.csv`, `.json` | Unchanged | During the request |
| Any other name | Read as plain text when its first 64 KB hold no NUL byte and decode as UTF-8 (the rule from #879) | During the request |
| Anything else | `400`, "Heym cannot read <name>. ..." | During the request |

An image with no recognizable text, an audio file with no speech, or a PDF that is still empty after
OCR fails with a message saying so. It does not succeed with 0 chunks. Text, Markdown, CSV and JSON
keep today's behavior for empty files.

Limits stay where the Converter has them: audio up to 30 minutes (`MAX_AUDIO_SECONDS`), the
Converter's OCR timeouts, and the instance upload limit (`read_upload_file_limited`).

## Backend (heymrun)

### `backend/app/services/rag_ingest.py` (new)

The one place that decides how a file enters a store.

- `RagFileKind`: `pdf`, `markdown`, `text`, `csv`, `json`, `image`, `audio`.
- Extension tables for documents, images and audio, plus `RAG_UPLOAD_EXTENSIONS` for messages.
- `reads_as_utf8_text(data: bytes) -> bool`: no NUL byte in the first 64 KB, and those bytes decode
  as UTF-8 with an incremental decoder that tolerates a character cut at the 64 KB boundary when the
  file is longer. Same rule as `textFileSniff.ts`.
- `classify(filename, data) -> RagFileKind | None`: extension first, then the UTF-8 rule.
- `needs_background(kind, data) -> bool`: `True` for audio, and for a PDF where at least one page
  yields no text with pypdf.
- `extract_chunks(kind, data, filename, file_size) -> list[TextChunk]`: the blocking extraction.
  Callers run it in a thread.
  - Documents: the existing `FileProcessor` methods.
  - Images: `ocr_service.image_to_text(..., language=AUTO_LANGUAGE)`, then
    `FileProcessor.process_extracted_text` with `file_type="image"` and `ocr_language`.
  - Audio: `speech_to_text_service.audio_to_text(..., language=AUTO_LANGUAGE)`, then
    `FileProcessor.process_timed_segments`. Segments are grouped into chunks of up to `chunk_size`
    characters; each chunk keeps `start_seconds`, `end_seconds`, `language`, `duration_seconds`,
    `file_type="audio"`. Context overlap as for text.
  - PDF: pypdf page texts; empty pages go through `ocr_service.pdf_to_text`, contiguous empty
    pages grouped into ranges of at most `ocr_service.MAX_PAGES` (50). At most
    `MAX_RAG_OCR_PAGES = 200` empty pages are read per file; a PDF with more fails before any OCR
    runs. OCR'd pages get `ocr: true` in their chunk metadata. Page numbering and `total_pages` as
    today.
  - Raises `RagIngestError` (a `ValueError`) with a user-facing message when an image, audio file or
    PDF yields no text. OCR and STT `ValueError` messages pass through unchanged.

`FileProcessor` gains two public methods, `process_extracted_text` and `process_timed_segments`, and
its PDF path is split into `pdf_page_texts` plus `process_pdf_pages` so the OCR fallback reuses the
same chunking. `process_pdf` keeps its signature and output for `board_attachment_service`.

### `vector_store_ingest_jobs` table (new, migration `154_vector_store_ingest_jobs`)

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `vector_store_id` | UUID FK `vector_stores.id`, `ON DELETE CASCADE` | indexed |
| `created_by_id` | UUID FK `users.id`, `ON DELETE SET NULL`, nullable | |
| `filename` | `String(512)` | the source name the chunks will carry |
| `file_size` | `BigInteger` | |
| `kind` | `String(16)` | `audio` or `pdf` |
| `status` | `String(16)` | `queued`, `processing` or `failed` |
| `error` | `Text`, nullable | user-facing message for `failed` |
| `override_duplicates` | `Boolean` | |
| `heartbeat_at` | `DateTime(tz)` | refreshed while the job lives |
| `created_at`, `updated_at` | `DateTime(tz)` | |

Composite index on `(vector_store_id, status)`. A finished job deletes its row: the document then
shows in the store's normal item list. A failed row stays until someone dismisses it.

### `backend/app/services/rag_ingest_jobs.py` (new)

Runs the background jobs inside the process that accepted the upload.

- The upload bytes are written to `<tempdir>/heym-rag-ingest/<job_id>`. The file name never comes
  from the upload.
- `start(job_id, path)` creates an `asyncio` task and keeps a strong reference to it until it ends.
- A per-process `asyncio.Semaphore(1)` keeps one heavy extraction running at a time in each process,
  so concurrent uploads queue instead of saturating the instance.
- The job refreshes `heartbeat_at` every 30 seconds from the moment it is queued, including while it
  waits for the semaphore.
- Order of work: status `processing`; `extract_chunks` in a thread; if `override_duplicates`, delete
  the old chunks of that source; `insert_batch` in a thread; delete the row; remove the temp file.
  The old document stays searchable until the new one is ready.
- Failure: status `failed` with the `ValueError` message, or "Heym could not read this file." plus
  a logged traceback for anything else. The temp file is removed.
- Stale jobs: a job in `queued` or `processing` whose `heartbeat_at` is older than 3 minutes lost its
  process (restart, crash, worker recycle). Listing a store's jobs marks such rows `failed` with
  "Processing stopped because Heym restarted. Upload the file again." and removes the temp file if
  it is on this host. This needs no startup hook, no leader, and works with several uvicorn workers
  per instance and several instances.

Jobs run where the upload request landed. Ingress points at the main instance, as for every other
upload, and every instance runs the same image with the OCR binaries and the Whisper model.

`audit()` stays in the router: the upload audit line is written when a job is queued, with
`queued=True`. The job itself writes only its own row (AGENTS.md, audit logging).

### API (`backend/app/api/vector_stores.py`)

- `POST /api/vector-stores/{id}/upload`
  - Classifies with `rag_ingest.classify`; `400` for an unknown binary file, naming what is accepted.
  - `409` when a job for the same file name in that store is `queued` or `processing`.
  - Synchronous kinds: extraction and `insert_batch` run in a thread (today both block the event
    loop), then the response is as today plus `status: "done"`.
  - Background kinds: creates the job, starts it, returns `status: "queued"`, `job_id`, and zero
    counts.
  - `VectorStoreUploadResponse` gains `status: Literal["done", "queued"] = "done"` and
    `job_id: UUID | None = None`. Existing fields and the 200 status code stay, so current clients
    keep working.
- `GET /api/vector-stores/{id}/ingest-jobs?limit=&offset=`: the store's jobs, newest first, after
  marking stale ones. Same access rule as `/items`.
- `DELETE /api/vector-stores/{id}/ingest-jobs/{job_id}`: dismisses a `failed` job; `409` for a job
  still running, `404` for a job of another store. Same access rule as `/upload`.

## Frontend (heymrun)

- `frontend/src/lib/ragFileTypes.ts` (new): the accepted extension groups, `ragFileKind(file)` using
  `readsAsUtf8Text`, and the human-readable format line. It imports nothing from services or stores,
  so Work can import it through `@heym/lib/ragFileTypes`.
- `VectorStoresPanel.vue`: the upload input loses its `accept` filter (as the chat composers did),
  so files like `burak.akgun` can be picked; the format line comes from `ragFileTypes.ts`. After an
  upload, queued files are reported separately: "2 file(s) are being read in the background; open
  the store to follow them."
- `frontend/src/components/VectorStores/VectorStoreIngestJobs.vue` (new): shown in the store's items
  dialog above the sources. One row per job: "Transcribing" or "Reading scanned pages" with a spinner,
  or the error with a dismiss button. Polls every 4 seconds while a job is `queued` or `processing`
  and emits `finished` so the dialog reloads its sources. `VectorStoresPanel.vue` is already far over
  300 lines; the new UI lives in this component instead of growing it.
- `services/api.ts` and `types/`: `ingestJobs`, `dismissIngestJob`, the job type, and the two new
  upload response fields.

## Work (heym-work)

- `heym_routes.py`: proxy `GET /vector-stores/{vector_store_id}/ingest-jobs` (viewer) and
  `DELETE /vector-stores/{vector_store_id}/ingest-jobs/{job_id}` (editor). Work reads jobs through
  Heym's API, so no new database grant is needed.
- `api/schemas.py`: `VectorStoreUploadView` gains `status` and `job_id` with defaults, so an older
  Heym that omits them still validates.
- `lib/ragUpload.ts`: `planStoreUpload` becomes async and uses `@heym/lib/ragFileTypes`; `RAG_ACCEPT`
  goes away and the picker in `RagDocuments.vue` loses its `accept` filter. The refusal toast names
  the new formats.
- `useStoreUpload.ts`: a queued upload is reported as "<name> is being read in the background. It
  appears in the store when it is ready." and still triggers the reload.
- `RagDocuments.vue`: shows the store's jobs above its documents (a small `RagIngestJobs.vue`
  component), polls while one runs, reloads the documents when one finishes, and lets an editor
  dismiss a failed one. A `404` from an older Heym without the jobs route counts as "no jobs".
- `vendor/heymrun` is pinned to the Heym merge commit; Work's docs come in through `bun run sync-docs`.

## Errors

| Case | Response |
|---|---|
| Binary file of an unknown type | `400` "Heym cannot read <name>. Vector stores take PDF, Markdown, text, CSV, JSON, images (PNG, JPEG, TIFF, WebP, BMP), audio (mp3, wav, ogg, flac) and other plain-text files." |
| Image without text | `422` "No text was found in <name>." |
| PDF still empty after OCR | job `failed`: "No text was found in <name>, even after reading its pages as images." |
| PDF with more than 200 pages without text | job `failed`: "<name> has <n> pages without a text layer. Heym reads at most 200 of them; split the file." |
| Audio without speech | job `failed`: "No speech was found in <name>." |
| Audio longer than 30 minutes, unreadable audio, OCR timeout | the Converter's message, as `422` (sync) or job `failed` (background) |
| Same name still processing | `409` "<name> is still being processed in this store." |
| Process gone mid-job | job `failed` after 3 minutes without a heartbeat |

## Testing

Backend (`unittest`, `AsyncMock`, OCR and STT mocked):

- `test_rag_ingest.py`: classification by extension; UTF-8 rule including a NUL byte, invalid UTF-8,
  a multi-byte character cut at 64 KB, and a short file ending inside a character; image chunks and
  metadata; timed audio chunks and their boundaries; PDF fallback that OCRs only the empty pages and
  keeps page order; the three "no text" errors.
- `test_file_processor.py`: `process_pdf` output unchanged after the split.
- `test_vector_store_ingest_jobs.py`: upload returns `queued` and a job for audio and scanned PDFs;
  `done` for images and UTF-8 files; `400` for binary; `409` for a same-name job in flight; job
  success deletes the row and inserts chunks; override deletes the old source only after extraction;
  failure records the message; stale heartbeat becomes `failed`; dismiss rules; another user cannot
  list or dismiss a store's jobs.

Frontend: Vitest for `ragFileTypes.ts` (Heym) and the async `planStoreUpload` (Work), and for the
jobs component's polling stop. The E2E environment cannot create a real store (no Qdrant), so
`frontend/e2e/tab-vectors.spec.ts` mocks the store API with `page.route`, as other tab specs do: a
`burak.akgun` file goes through the picker, an audio upload answers `queued`, the items dialog shows
the processing row and then the document once the jobs list empties, and a failed row can be
dismissed.

## Docs and announcement

- `frontend/src/docs/content/tabs/vectorstores-tab.md`: supported files, background processing, the
  jobs list.
- `frontend/src/docs/content/nodes/rag-node.md`: note that Converter -> RAG insert is the canvas path
  for the same media.
- `frontend/src/docs/content/reference/features.md`: the Vector Stores entry.
- Release tour: a new `2026.30` entry with a `rag-media-upload` section, a
  `RagMediaUploadTourVisual.vue` mock registered in `tourVisuals.ts`, the id in `sectionOrder`.
  The registry keeps five sections, so the oldest (`board-task-fields`, 2026.25) is retired with
  its visual.
- Work: release notes in the annotated tag of the release that carries the pin.

## Out of scope

- UTF-8 detection for board card attachments (`board_attachment_service`).
- Describing images with a vision LLM; images are read with OCR only.
- Cancelling a running job.
- A per-store "processing" badge in the store list.
