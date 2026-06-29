from __future__ import annotations

import json

from app.services.node_execution.base import NodeExecutionContext


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

        metadata_json = node_data.get("documentMetadata", "{}")
        try:
            if isinstance(metadata_json, str):
                metadata = json.loads(metadata_json) if metadata_json else {}
            else:
                metadata = metadata_json or {}
        except Exception:
            metadata = {}

        point_id = service.insert(collection_name, document_content, metadata)
        output = {
            "success": True,
            "operation": "insert",
            "point_id": point_id,
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
