# Vectorstores Tab

The **Vectorstores** tab manages vector stores used by [RAG](../nodes/rag-node.md) nodes. Create stores, upload documents, and share them with your team.

<video src="/features/showcase/vectorstores.webm" controls playsinline muted preload="metadata" style="width:100%;border-radius:12px;margin:16px 0"></video>
<p class="github-video-link"><a href="../../../../public/features/showcase/vectorstores.webm">▶ Watch Vectorstores demo</a></p>

## Creating a Vector Store

1. Click **New Vector Store**
2. Enter a name and optional description
3. Select a **Qdrant credential** – Must be a [Credentials](./credentials-tab.md) entry of type Qdrant
4. Optionally set a custom collection name (defaults to auto-generated)
5. Save

## Uploading Documents

- **Upload files** – Drag and drop or select files (PDF, TXT, etc.)
- **Duplicate handling** – Choose to override or skip duplicate filenames
- **Progress** – Upload progress is shown during ingestion

## Managing Content

- **View items** – See source groups and document counts per store
- **Delete sources** – Remove specific files or source groups from a store
- **Edit store** – Change name, description, or credential

## Sharing

- Share vector stores with other users by email
- Shared stores appear with an indicator
- Revoke sharing from the store card menu

## Using in Workflows

In a [RAG node](../nodes/rag-node.md), select the vector store by name. The node retrieves relevant chunks and augments the LLM context with them.

## Related

- [Credentials Tab](./credentials-tab.md) – Qdrant credential setup
- [RAG Node](../nodes/rag-node.md) – Node reference
- [Workflows Tab](./workflows-tab.md) – Create workflows that use RAG
- [Contextual Showcase](../reference/contextual-showcase.md) – Compact page guide for dashboard surfaces
