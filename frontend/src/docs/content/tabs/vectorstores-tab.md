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

- **Upload files** – Drag and drop or select files (PDF, TXT, etc.)
- **Duplicate handling** – Choose to override or skip duplicate filenames
- **Progress** – Upload progress is shown during ingestion

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
