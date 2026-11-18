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
  - **Documents** – PDF, Word (DOCX), Excel (XLSX), Markdown, text, CSV and JSON
  - **Images** – PNG, JPEG, TIFF, WebP and BMP, read with the same Tesseract OCR as the
    [Converter](../nodes/converter-node.md) node, language detected automatically
  - **Audio** – mp3, wav, ogg, opus (WhatsApp voice notes) and flac, transcribed with the Converter's Whisper model on your
    own instance; each chunk keeps where it starts and ends in the recording
    (`start_seconds`, `end_seconds`)
  - **Any other plain-text file** – a file such as `notes` or `README` is read as text when
    it is valid UTF-8
- **Word documents** – the body is read in order: paragraphs, table rows, content controls and
  text boxes. Tracked changes count as accepted. Headers, footers, footnotes and comments are
  left out
- **Excel workbooks** – every worksheet is read. Its first non-empty row names the columns, and
  each row after it becomes one chunk, `Column: value | Column: value`, as a CSV row does. Each
  chunk keeps its `sheet` and its `row` number as Excel shows it. A column without a name is
  called by its letter, and formulas read as the value Excel last saved
- **Scanned PDFs** – pages without a text layer are read with OCR, up to 200 such pages per file
- **Background uploads** – audio and PDFs with scanned pages take minutes, so Heym reads them in
  the background. They show at the top of the store's items as *Transcribing* or *Reading scanned
  pages* and turn into a normal source when their chunks are in. A failed one shows why and can
  be dismissed. With **Override existing files**, the old version stays searchable until the new
  one is ready
- **Duplicate handling** – Choose to override or skip duplicate filenames
- **Progress** – Upload progress is shown during ingestion

An image without readable text, a Word document or Excel workbook without text, an audio file
without speech, and a binary file of another type are refused with a message.

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

The owner shares a store with users by email or with a team, and picks a permission for each share:

| Permission | What the user can do |
|------------|----------------------|
| **Read** | See the store and its documents, search it, and use it in RAG `search` operations |
| **Write** | Everything Read allows, plus upload documents, delete documents and chunks, dismiss failed background uploads, and run RAG `insert`, `upsert` and `delete` operations |

- Change a share's permission from the dialog's dropdown, or remove the share
- Renaming, deleting and sharing the store stay with the owner
- Shares created before permissions existed are **Read**
- A user who reaches a store through several shares gets the strongest one
- Shared stores show their permission on the card (**Shared · Read** or **Shared · Write**)
- `POST /api/vector-stores/{id}/shares` and `/team-shares` accept `permission` (`read` or `write`, default `read`); posting an existing user or team again updates its permission

## From Chat and MCP

[Chat](./chat-tab.md), Heym Work's Chat, the `heym_chat` [MCP tool](./mcp-tab.md) and [A2A](../reference/a2a.md) treat your vector stores as knowledge bases:

- **Ask a question** – When a store's name or description fits a question, such as "what does our refund policy say about digital goods?", Chat searches that store before it runs a workflow and answers from the matching chunks, naming the documents it used. It can search up to five stores in one step and says so when none of them covers the question
- **List stores and documents** – Ask which knowledge bases you have, or which documents are in one; Chat lists each document with its chunk count
- **Access** – Chat reaches the stores you own and the ones shared with you directly or through a team, and searches them through the same search endpoint as Heym Work
- **Descriptions matter** – Every turn shows Chat the name and the first 200 characters of the description of up to 50 stores (it lists the rest on request), so a short description of what a store holds helps it pick the right one

## Using in Workflows

In a [RAG node](../nodes/rag-node.md), select the vector store by name. The node retrieves relevant chunks and augments the LLM context with them.

## Related

- [Credentials Tab](./credentials-tab.md) – Vector store credential setup (Qdrant, Postgres, or custom embeddings)
- [RAG Node](../nodes/rag-node.md) – Node reference
- [Workflows Tab](./workflows-tab.md) – Create workflows that use RAG
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
