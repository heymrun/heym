# Vectorstores Tab

The **Vectorstores** tab manages vector stores used by [RAG](../nodes/rag-node.md) nodes. Create stores, upload documents, and share them with your team.

<video src="/features/showcase/vectorstores.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/vectorstores.webm">▶ Watch Vectorstores demo</a></p>

## Creating a Vector Store

1. Click **New Vector Store**
2. Enter a name and optional description
3. Select a vector store **credential** – *RAG: Qdrant + OpenAI* (external Qdrant server), *RAG: Psql + OpenAI* (Heym's own Postgres database via pgvector), or *RAG: Custom Embeddings* (any OpenAI-compatible embedding endpoint, targeting either backend). The credential determines the store's backend.
4. Optionally set a custom collection name (defaults to auto-generated)
5. Save

> A store's backend is fixed by its credential at creation time. In a RAG node, the **Database** dropdown filters stores to the matching backend.

## Uploading Documents

- **Upload files** – Drag and drop or pick several files. A store takes:
  - **Documents** – PDF, Markdown, text, CSV and JSON
  - **Images** – PNG, JPEG, TIFF, WebP and BMP, read with the same Tesseract OCR as the
    [Converter](../nodes/converter-node.md) node, language detected automatically
  - **Audio** – mp3, wav, ogg and flac, transcribed with the Converter's Whisper model on your
    own instance; each chunk keeps where it starts and ends in the recording
    (`start_seconds`, `end_seconds`)
  - **Any other plain-text file** – a file such as `notes` or `burak.akgun` is read as text when
    it is valid UTF-8
- **Scanned PDFs** – pages without a text layer are read with OCR, up to 200 such pages per file
- **Background uploads** – audio and PDFs with scanned pages take minutes, so Heym reads them in
  the background. They show at the top of the store's items as *Transcribing* or *Reading scanned
  pages* and turn into a normal source when their chunks are in. A failed one shows why and can
  be dismissed. With **Override existing files**, the old version stays searchable until the new
  one is ready
- **Duplicate handling** – Choose to override or skip duplicate filenames
- **Progress** – Upload progress is shown during ingestion

An image without readable text, an audio file without speech, and a binary file of another type
are refused with a message.

## Managing Content

- **View items** – See source groups and document counts per store. Uploaded files group
  under their filename; documents a [RAG node](../nodes/rag-node.md) stored without a
  `source` of their own group under **Added workflow: _name_**, naming the workflow that
  wrote them
- **Delete sources** – Remove specific files or source groups from a store, including
  everything one workflow added
- **Edit store** – Change name, description, or credential
- **Search** – `POST /api/vector-stores/{id}/search` with a `query` (and a `limit` from 1 to 20,
  default 5) returns the chunks a RAG node's search would return, best match first, each with its
  score and source. Heym Work's RAG screen uses it to test retrieval

## Sharing

- Share vector stores with other users by email
- Shared stores appear with an indicator
- Revoke sharing from the store card menu

## Using in Workflows

In a [RAG node](../nodes/rag-node.md), select the vector store by name. The node retrieves relevant chunks and augments the LLM context with them.

## Related

- [Credentials Tab](./credentials-tab.md) – Vector store credential setup (Qdrant, Postgres, or custom embeddings)
- [RAG Node](../nodes/rag-node.md) – Node reference
- [Workflows Tab](./workflows-tab.md) – Create workflows that use RAG
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
