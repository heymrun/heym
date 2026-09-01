from __future__ import annotations

import json

from app.services.node_execution.base import NodeExecutionContext


def _parse_metadata(raw: object) -> dict:
    """Metadata JSON as configured on the node, tolerating an empty or invalid value."""
    try:
        if isinstance(raw, str):
            return json.loads(raw) if raw.strip() else {}
        return dict(raw) if raw else {}
    except Exception:
        return {}


def _resolve_metadata_expressions(executor, value: object, inputs: dict, node_id: str) -> object:
    """Resolve ``$`` expressions in every string inside parsed metadata JSON.

    Values are resolved after the JSON is parsed, not by templating the raw text, so a
    resolved value containing a quote or a newline cannot break the document apart.
    """
    if isinstance(value, dict):
        return {
            key: _resolve_metadata_expressions(executor, item, inputs, node_id)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_resolve_metadata_expressions(executor, item, inputs, node_id) for item in value]
    if not isinstance(value, str) or "$" not in value:
        return value
    # A whole-string expression keeps its type, so a number stays a number and still
    # matches a metadata filter; anything else is a text template.
    if executor._is_single_dollar_expression(value):
        return executor.resolve_expression(value.strip(), inputs, node_id, preserve_type=True)
    return executor._resolve_value_with_dollar_refs(value, inputs, node_id)


def _resolve_filter_expressions(
    executor, parsed: object, inputs: dict, node_id: str
) -> dict | None:
    """Search filter JSON with ``$`` expressions resolved, using the document metadata rules.

    Sharing the resolver keeps a whole-string expression's type, so a numeric filter value
    stays a number and still matches the number stored by an insert.
    """
    resolved = executor._unwrap_value(
        _resolve_metadata_expressions(executor, parsed, inputs, node_id)
    )
    return resolved if isinstance(resolved, dict) else None


def _with_workflow_source(executor, metadata: dict) -> dict:
    """Name the workflow as the source when the author supplied none of their own."""
    from app.services.vector_store import WORKFLOW_SOURCE_PREFIX

    if metadata.get("source"):
        return metadata

    name = str(executor._get_workflow_metadata()[0] or "").strip()
    if not name:
        return metadata
    return {**metadata, "source": f"{WORKFLOW_SOURCE_PREFIX}{name}"}


def _metadata_from_node_data(executor, node_data: dict, inputs: dict, node_id: str) -> dict:
    """Node metadata JSON with expressions resolved and Dot* values made serializable."""
    metadata = _parse_metadata(node_data.get("documentMetadata", "{}"))
    resolved = _resolve_metadata_expressions(executor, metadata, inputs, node_id)
    unwrapped = executor._unwrap_value(resolved)
    if not isinstance(unwrapped, dict):
        return {}
    return _with_workflow_source(executor, unwrapped)


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the rag node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.db.session import SessionLocal
    from app.services.encryption import decrypt_config
    from app.services.vector_store import (
        create_vector_store_service_for_credential,
    )

    vector_store_id = node_data.get("vectorStoreId")
    if not vector_store_id:
        raise ValueError("RAG node requires a vector store")

    operation = node_data.get("ragOperation") or node_data.get("operation", "")
    if not operation:
        raise ValueError("RAG node requires an operation")

    vector_store_config: dict = {}
    credential_type = None
    collection_name: str = ""
    with SessionLocal() as db:
        store = self._get_accessible_vector_store(db, vector_store_id)
        if not store:
            raise ValueError("Vector store not found or not accessible")
        collection_name = store.collection_name
        cred = self._get_vector_store_backing_credential(db, store.credential_id)
        if cred:
            vector_store_config = decrypt_config(cred.encrypted_config)
            credential_type = cred.type

    if not vector_store_config:
        raise ValueError("Vector store credential not found")

    service = create_vector_store_service_for_credential(credential_type, vector_store_config)

    if operation == "insert":
        document_content = node_data.get("documentContent", "")
        document_content = self.evaluate_message_template(document_content, inputs, node_id)

        metadata = _metadata_from_node_data(self, node_data, inputs, node_id)

        point_id = service.insert(collection_name, document_content, metadata)
        output = {
            "success": True,
            "operation": "insert",
            "point_id": point_id,
        }

    elif operation in ("upsert", "delete"):
        from app.services.vector_store import DEFAULT_DOCUMENT_ID_FIELD

        id_field = str(node_data.get("documentIdField") or "").strip() or DEFAULT_DOCUMENT_ID_FIELD

        raw_document_id = node_data.get("documentId", "")
        document_id = ""
        if raw_document_id not in (None, ""):
            document_id = str(
                self.evaluate_message_template(str(raw_document_id), inputs, node_id)
            ).strip()
        if not document_id:
            raise ValueError(f"RAG {operation} operation requires a document ID")

        if operation == "upsert":
            document_content = node_data.get("documentContent", "")
            document_content = self.evaluate_message_template(document_content, inputs, node_id)
            metadata = _metadata_from_node_data(self, node_data, inputs, node_id)

            point_id, replaced = service.upsert_by_field(
                collection_name,
                id_field,
                document_id,
                document_content,
                metadata,
            )
            output = {
                "success": True,
                "operation": "upsert",
                "point_id": point_id,
                "id_field": id_field,
                "document_id": document_id,
                "replaced": replaced > 0,
                "replaced_count": replaced,
            }
        else:
            deleted_count = service.delete_by_field(collection_name, id_field, document_id)
            output = {
                "success": True,
                "operation": "delete",
                "id_field": id_field,
                "document_id": document_id,
                "deleted": deleted_count > 0,
                "deleted_count": deleted_count,
            }

    elif operation == "search":
        query_text = node_data.get("queryText", "")
        query_text = self.evaluate_message_template(query_text, inputs, node_id)

        search_limit = int(node_data.get("searchLimit", 5))

        metadata_filter_json = node_data.get("metadataFilters", "{}")
        try:
            if isinstance(metadata_filter_json, str):
                metadata_filter = json.loads(metadata_filter_json) if metadata_filter_json else None
            else:
                metadata_filter = metadata_filter_json or None
        except Exception:
            metadata_filter = None
        if metadata_filter is not None:
            metadata_filter = _resolve_filter_expressions(self, metadata_filter, inputs, node_id)

        enable_reranker = node_data.get("enableReranker", False)
        reranker_credential_id = node_data.get("rerankerCredentialId")
        reranker_top_n = int(node_data.get("rerankerTopN", search_limit))

        initial_limit = search_limit
        if enable_reranker and reranker_credential_id:
            initial_limit = max(search_limit * 3, 20)

        results = service.search(
            collection_name,
            query_text,
            limit=initial_limit,
            metadata_filter=metadata_filter,
        )

        reranked = False
        if enable_reranker and reranker_credential_id and results:
            from app.services.reranker import DocumentToRerank, create_reranker_service

            cohere_config: dict = {}
            with SessionLocal() as db:
                reranker_cred = self._get_accessible_credential(db, reranker_credential_id)
                if reranker_cred:
                    cohere_config = decrypt_config(reranker_cred.encrypted_config)

            if cohere_config and cohere_config.get("api_key"):
                reranker_service = create_reranker_service(cohere_config["api_key"])
                docs_to_rerank = [
                    DocumentToRerank(
                        id=r.id,
                        text=r.text,
                        score=r.score,
                        metadata=r.metadata,
                    )
                    for r in results
                ]
                reranked_results = reranker_service.rerank(
                    query=query_text,
                    documents=docs_to_rerank,
                    top_n=reranker_top_n,
                )
                results = reranked_results
                reranked = True

        if reranked:
            output = {
                "success": True,
                "operation": "search",
                "query": query_text,
                "reranked": True,
                "results": [
                    {
                        "id": r.id,
                        "text": r.text,
                        "score": r.original_score,
                        "relevance_score": r.relevance_score,
                        "metadata": r.metadata,
                    }
                    for r in results
                ],
                "count": len(results),
            }
        else:
            output = {
                "success": True,
                "operation": "search",
                "query": query_text,
                "reranked": False,
                "results": [
                    {
                        "id": r.id,
                        "text": r.text,
                        "score": r.score,
                        "metadata": r.metadata,
                    }
                    for r in results
                ],
                "count": len(results),
            }
    else:
        raise ValueError(f"Unknown RAG operation: {operation}")
    return output
