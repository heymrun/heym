# RAG / Vector Store

The **RAG / Vector Store** node inserts, upserts, deletes, and searches documents in a vector store for Retrieval Augmented Generation (RAG). Use it to augment LLM context with relevant documents, and to keep that context in step with the system the documents come from.

The node has a **Database** dropdown that selects the backend:

- **Qdrant** – stores vectors in an external Qdrant server (requires a *RAG: Qdrant + OpenAI* credential).
- **Postgres (pgvector)** – stores vectors inside Heym's own Postgres database, no external service (requires a *RAG: Psql + OpenAI* credential).

The default is **Qdrant** for backward compatibility. Changing the Database filters the **Vector Store** list to stores backed by that database. Both backends support the same operations, metadata filtering, hybrid (vector + BM25) search, and Cohere reranking.

Either backend can also be reached through a *RAG: Custom Embeddings* credential, which
replaces OpenAI with any OpenAI-compatible embedding endpoint and names its own vector
store. A store created from such a credential appears under whichever Database it
targets. See [Custom Embeddings](../reference/integrations.md#custom-embeddings-rag).

## Overview

| Property | Value |
|----------|-------|
| Inputs | 1 |
| Outputs | 1 |
| Output | `$nodeLabel.results` / `$nodeLabel.reranked` / `$nodeLabel.hybrid` / `$nodeLabel.count` (search), `$nodeLabel.point_id` (insert, upsert), `$nodeLabel.deleted` (delete) |

## Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `dbType` | `"qdrant"` \| `"pgvector"` | Vector store backend (default: `"qdrant"`) |
| `vectorStoreId` | UUID | Vector store from [Vectorstores](../tabs/vectorstores-tab.md) tab |
| `ragOperation` | `"insert"` \| `"upsert"` \| `"delete"` \| `"search"` | Operation type (also `operation`) |
| `documentContent` | expression | Document text to store (insert, upsert) |
| `documentMetadata` | JSON string | Metadata for stored docs (insert, upsert); values support expressions |
| `documentIdField` | string | Payload field holding the unique id (upsert, delete; default `doc_id`) |
| `documentId` | expression | Value of the unique id (upsert, delete) |
| `queryText` | expression | Search query (search only) |
| `searchLimit` | number | Max results (default: 5) |
| `metadataFilters` | JSON string | Metadata filters for search (values support expressions) |
| `hybridSearch` | boolean | Combine vector search with BM25 keyword search (search only; default: off) |
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

### Metadata expressions

Metadata values accept expressions, so a document can be stored with context from the run:

```json
{ "url": "$start.url", "category": "faq" }
```

Expressions are resolved after the JSON is parsed, not by substituting text into it, so a
value containing a quote or a newline cannot break the object apart. A value that is one
whole expression keeps its resolved type — `{"count": "$start.count"}` stores a number, not
`"7"` — which matters because search `metadataFilters` match on exact type. Mixed text such as
`"page $start.count"` resolves to a string, and nested objects and arrays are walked too.

The same applies to `upsert`, and to search's `metadataFilters`: it is parsed first and its
values resolved after, by the same rules. So a filter written as `{"count": "$start.count"}`
matches the number an insert stored, rather than the string `"7"`.

### Which workflow stored a document

A document stored without a `source` of its own is stamped with the workflow that stored it,
as `source: "workflow:<workflow name>"`. The [Vectorstores](../tabs/vectorstores-tab.md) tab
groups those under **Added workflow: _name_**, so a store's contents say where each document
came from, and one workflow's documents can be deleted as a group. Setting `source` yourself
in `documentMetadata` always wins over the stamp.

### Upsert

Insert a document, or replace the one already stored under the same unique id.

The id is a field **inside the payload**, not the store's internal point id, so a document
keeps the identifier your own system already uses — a CRM record id, an SKU, a page slug.
`documentIdField` names that field and `documentId` carries its value.

| Field | Required | Description |
|-------|----------|-------------|
| `documentId` | yes | Unique id of the document (supports expressions) |
| `documentContent` | yes | Text to embed and store |
| `documentIdField` | no | Payload field the id lives in (default `doc_id`) |
| `documentMetadata` | no | JSON object, e.g. `{"source": "crm", "url": "$start.url"}` (values support expressions) |

Every point whose id field matches is removed first, so a document that was previously
stored as several chunks is replaced as a whole rather than duplicated. The id field is
written into the payload for you, and the point id stays stable across upserts of the same
document.

**Output:** `$nodeLabel.point_id`, `$nodeLabel.document_id`, `$nodeLabel.replaced` (boolean —
whether an existing version was replaced), `$nodeLabel.replaced_count`

### Delete

Remove a document by the same unique id.

| Field | Required | Description |
|-------|----------|-------------|
| `documentId` | yes | Unique id of the document (supports expressions) |
| `documentIdField` | no | Payload field the id lives in (default `doc_id`) |

**Output:** `$nodeLabel.deleted` – `true` when at least one point matched, `false` when the id
was not in the store. `$nodeLabel.deleted_count` carries how many points were removed.

Deleting an id that is not there is not an error: the node succeeds with `deleted: false`, so
a cleanup branch does not need a guard in front of it.

### Search

Semantic search for similar documents.

| Field | Required | Description |
|-------|----------|-------------|
| `queryText` | yes | Search query |
| `searchLimit` | no | Max results (default: 5) |
| `metadataFilters` | no | Filter by metadata (exact match JSON object, values support expressions) |
| `hybridSearch` | no | Fuse vector similarity with BM25 keyword matching (see [Hybrid search](#hybrid-search)) |
| `enableReranker` | no | Enable Cohere reranking for better relevance |
| `rerankerCredentialId` | when reranking | Cohere credential |
| `rerankerTopN` | no | Final number of results after reranking |

**Output:** `$nodeLabel.results` – array of `{ id, text, score, metadata }`

When reranking is enabled:

- `$nodeLabel.reranked` becomes `true`
- Each result also includes `relevance_score`
- `score` remains the original vector similarity score
- `relevance_score` is the Cohere reranker score

#### Hybrid search

Vector search finds text that means the same thing as the query. Text that only contains the exact words can rank lower: a product code, a ticket number, a person's name, an error such as `ERR-4021`. Switch on **Hybrid Search** and the node runs a keyword search next to the vector search and merges both lists, so one query finds both kinds of match.

1. The vector search returns its best matches, as it does without hybrid search.
2. A keyword search scores the stored text against the words of the query with **BM25**, which rewards rare words, repeated words and shorter documents.
3. The two ranked lists are merged with **reciprocal rank fusion**. A document near the top of both lists ranks first, and a document only one list found still appears.

Metadata filters apply to both searches, and the Cohere reranker, when enabled, runs on the merged list.

Each result carries the score of both searches:

| Field | Meaning |
|-------|---------|
| `score` | Fused score from 0 to 1. `1` means the document ranked first in both searches. |
| `vector_score` | Vector similarity (0 to 1). `null` when only the keyword search found the document. |
| `keyword_score` | BM25 score. `null` when none of the query words appear in the document. |

`$nodeLabel.hybrid` is `true` when hybrid search ran.

Good to know:

- The fused `score` ranks results against each other. It is not a vector similarity, so a threshold tuned on a plain search does not carry over.
- Query words are lowercased and split on spaces and punctuation, so `ERR-4021` is searched as `err` and `4021`. The keyword search uses up to the first 16 distinct words of the query.
- Qdrant: the first hybrid search on a collection builds a full-text index on the `text` payload field, which needs a Qdrant key with write access. Large collections take a moment once, and later searches reuse the index.
- Postgres (pgvector): the `142_vsi_text_search_index` database migration adds the full-text index. Run `alembic upgrade head` after updating. Hybrid search also runs without the index, only slower on large stores.
- For every query the keyword search reads up to 200 matching documents, starting with the rarest query words, since those carry the most weight.

## Accessing Results

- `$ragNode.results.first().text` – top result content
- `$ragNode.results.first().score` – similarity score (0–1), or the fused score with hybrid search
- `$ragNode.results.first().keyword_score` – BM25 score (hybrid search)
- `$ragNode.results.first().vector_score` – vector similarity (hybrid search)
- `$ragNode.results.first().metadata.source` – top result metadata
- `$ragNode.results.map("item.text").join("\n\n")` – concatenate for LLM context
- `$ragNode.reranked` – whether reranking was applied
- `$ragNode.hybrid` – whether hybrid search was applied
- `$ragNode.count` – number of returned results
- `$ragNode.replaced` – whether an upsert replaced an existing document
- `$ragNode.deleted` – whether a delete removed anything

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

## Example – Hybrid search

```json
{
  "type": "rag",
  "data": {
    "label": "findTicket",
    "vectorStoreId": "vector-store-uuid",
    "ragOperation": "search",
    "queryText": "$userInput.body.text",
    "searchLimit": 5,
    "hybridSearch": true
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

## Example – Upsert

```json
{
  "type": "rag",
  "data": {
    "label": "syncDoc",
    "vectorStoreId": "vector-store-uuid",
    "ragOperation": "upsert",
    "documentIdField": "doc_id",
    "documentId": "$userInput.body.id",
    "documentContent": "$userInput.body.text",
    "documentMetadata": "{\"source\": \"crm\"}"
  }
}
```

## Example – Delete

```json
{
  "type": "rag",
  "data": {
    "label": "removeDoc",
    "vectorStoreId": "vector-store-uuid",
    "ragOperation": "delete",
    "documentIdField": "doc_id",
    "documentId": "$userInput.body.id"
  }
}
```

## Related

- [Why Heym](../getting-started/why-heym.md) – Built-in RAG as part of the agent runtime
- [Node Types](../reference/node-types.md) – Overview of all node types
- [Vectorstores Tab](../tabs/vectorstores-tab.md) – Create and manage vector stores
- [Third-Party Integrations](../reference/integrations.md#qdrant) – Qdrant and Postgres (pgvector) credential setup
- [Agent Node](./agent-node.md) – Use RAG results as agent context
- [LLM Node](./llm-node.md) – Feed RAG results into LLM system prompt
