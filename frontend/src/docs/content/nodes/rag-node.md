# Qdrant RAG

The **Qdrant RAG** node inserts documents into or searches a Qdrant vector store for Retrieval Augmented Generation (RAG). Use it to augment LLM context with relevant documents.

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.results` / `$nodeLabel.reranked` / `$nodeLabel.count` (search), `$nodeLabel.point_id` (insert) |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `vectorStoreId` | UUID | Vector store from [Vectorstores](../tabs/vectorstores-tab.md) tab |
| `ragOperation` | `"insert"` \| `"search"` | Operation type (also `operation`) |
| `documentContent` | expression | Document text to insert (insert only) |
| `documentMetadata` | JSON string | Metadata for inserted docs (insert only) |
| `queryText` | expression | Search query (search only) |
| `searchLimit` | number | Max results (default: 5) |
| `metadataFilters` | JSON string | Metadata filters for search |
| `enableReranker` | boolean | Use Cohere to rerank search results |
| `rerankerCredentialId` | UUID | Cohere credential for reranking |
| `rerankerTopN` | number | Number of top results to keep after reranking |

## Operations

### Insert

Add documents to the vector store.

| Field | Required | Description |
|-------|----------|-------------|
| `documentContent` | yes | Text to embed and store |
| `documentMetadata` | no | JSON object, e.g. `{"source": "user", "category": "general"}` |

**Output:** `$nodeLabel.status`, `$nodeLabel.inserted_ids`

### Search

Semantic search for similar documents.

| Field | Required | Description |
|-------|----------|-------------|
| `queryText` | yes | Search query |
| `searchLimit` | no | Max results (default: 5) |
| `metadataFilters` | no | Filter by metadata (exact match JSON object) |
| `enableReranker` | no | Enable Cohere reranking for better relevance |
| `rerankerCredentialId` | when reranking | Cohere credential |
| `rerankerTopN` | no | Final number of results after reranking |

**Output:** `$nodeLabel.results` – array of `{ id, text, score, metadata }`

When reranking is enabled:

- `$nodeLabel.reranked` becomes `true`
- Each result also includes `relevance_score`
- `score` remains the original vector similarity score
- `relevance_score` is the Cohere reranker score

## Accessing Results

- `$ragNode.results.first().text` – top result content
- `$ragNode.results.first().score` – similarity score (0–1)
- `$ragNode.results.first().metadata.source` – top result metadata
- `$ragNode.results.map("item.text").join("\n\n")` – concatenate for LLM context
- `$ragNode.reranked` – whether reranking was applied
- `$ragNode.count` – number of returned results

## Example – Search

```json
{
  "type": "rag",
  "data": {
    "label": "searchDocs",
    "vectorStoreId": "vector-store-uuid",
    "ragOperation": "search",
    "queryText": "$userInput.body.text",
    "searchLimit": 5,
    "metadataFilters": "{\"category\": \"faq\"}",
    "enableReranker": true,
    "rerankerCredentialId": "cohere-credential-uuid",
    "rerankerTopN": 5
  }
}
```

## Example – Insert

```json
{
  "type": "rag",
  "data": {
    "label": "insertDoc",
    "vectorStoreId": "vector-store-uuid",
    "ragOperation": "insert",
    "documentContent": "$userInput.body.text",
    "documentMetadata": "{\"source\": \"user_input\"}"
  }
}
```

## Related

- [Why Heym](../getting-started/why-heym.md) – Built-in RAG vs external service stitching
- [Node Types](../reference/node-types.md) – Overview of all node types
- [Vectorstores Tab](../tabs/vectorstores-tab.md) – Create and manage vector stores
- [Third-Party Integrations](../reference/integrations.md#qdrant) – Qdrant credential setup
- [Agent Node](./agent-node.md) – Use RAG results as agent context
- [LLM Node](./llm-node.md) – Feed RAG results into LLM system prompt
