from __future__ import annotations

import json

from app.services.node_execution.base import NodeExecutionContext


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


def _json_object_field(
    executor, raw: object, inputs: dict, node_id: str, field: str
) -> dict | None:
    """A JSON object field of the node (``documentMetadata``, ``metadataFilters``), resolved.

    - One whole expression such as ``$start.meta`` is resolved once: an object, or text
      holding a JSON object, is used as it is. Its values come from the run, so ``$`` inside
      them is not resolved again, and numbers stay numbers.
    - Written JSON is parsed first, then the ``$`` expressions in its values are resolved.
    - Blank and ``null`` give ``None``. Anything else fails the node: text that is not JSON,
      or a value or an expression result that is not an object. Ignoring it would store a
      document without its metadata, or search without the filter.
    """
    if raw is None:
        return None
    if isinstance(raw, dict):
        return executor._unwrap_value(_resolve_metadata_expressions(executor, raw, inputs, node_id))
    if not isinstance(raw, str):
        raise ValueError(f"{field} must be a JSON object")
    text = raw.strip()
    if not text:
        return None
    if text.startswith("$") and executor._is_single_dollar_expression(text):
        value = executor._unwrap_value(
            executor.resolve_expression(text, inputs, node_id, preserve_type=True)
        )
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{field} is not valid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{field} must be a JSON object")
        return value
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{field} is not valid JSON: {exc}") from exc
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must be a JSON object")
    return executor._unwrap_value(_resolve_metadata_expressions(executor, parsed, inputs, node_id))


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
    """The document's metadata, resolved by `_json_object_field`, with the workflow source."""
    metadata = _json_object_field(
        executor, node_data.get("documentMetadata", "{}"), inputs, node_id, "documentMetadata"
    )
    return _with_workflow_source(executor, metadata or {})


def _rerank_with_decision_model(
    executor,
    *,
    node_id: str,
    credential_id: str,
    config: dict,
    model: str,
    query: str,
    documents: list,
    top_n: int,
) -> tuple[list, str | None]:
    """Rerank with a Decision Model credential, failing the node the way a Cohere error does.

    Returns the reranked results and the id of the trace the call wrote, if any.
    """
    from importlib import import_module

    from app.services.decision_models import DecisionProviderError, DecisionRequestError
    from app.services.reranker import DecisionRerankError, DecisionRerankerService

    base_url = str(config.get("base_url") or "").strip()
    if not base_url:
        raise ValueError("Reranker failed: the Decision Model credential has no base URL")
    if not model:
        raise ValueError("Reranker failed: enter the decision model to rerank with")

    trace_context = executor._build_llm_trace_context(credential_id, node_id)
    service = DecisionRerankerService(
        base_url=base_url,
        api_key=str(config.get("api_key") or ""),
        model=model,
        trace_context=trace_context,
    )

    def _recorded_trace_id() -> str | None:
        if trace_context is None or not trace_context.trace_ids:
            return None
        return str(trace_context.trace_ids[-1])

    try:
        results = service.rerank(query=query, documents=documents, top_n=top_n)
    except (DecisionProviderError, DecisionRequestError, DecisionRerankError) as exc:
        message = f"Reranker failed: {exc}"
        trace_id = _recorded_trace_id()
        if trace_id:
            # A failed call is still traced, so keep the execution log linked to it.
            workflow_executor = import_module("app.services.workflow_executor")
            raise workflow_executor.NodeTraceableExecutionError(message, trace_id) from exc
        raise ValueError(message) from exc
    return results, _recorded_trace_id()


def _required_template(
    executor, node_data: dict, key: str, inputs: dict, node_id: str, message: str
) -> str:
    """Resolve a required text field; a blank one is an error.

    evaluate_message_template renders a blank template as str(inputs), so a blank Document
    Content or Query embedded every input of the run, request headers included.
    """
    template = str(node_data.get(key, "") or "")
    if not template.strip():
        raise ValueError(message)
    return executor.evaluate_message_template(template, inputs, node_id)


def execute(ctx: NodeExecutionContext) -> object:
    """Execute the rag node."""
    self = ctx.executor
    node_id = ctx.node_id
    inputs = ctx.inputs
    node_data = ctx.node_data

    from app.db.session import SessionLocal
    from app.services.embedding import as_bool
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
        store = self._get_accessible_vector_store(db, vector_store_id, operation)
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
        document_content = _required_template(
            self,
            node_data,
            "documentContent",
            inputs,
            node_id,
            "RAG insert operation requires document content",
        )

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
            document_content = _required_template(
                self,
                node_data,
                "documentContent",
                inputs,
                node_id,
                "RAG upsert operation requires document content",
            )
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
        query_text = _required_template(
            self, node_data, "queryText", inputs, node_id, "RAG search operation requires a query"
        )

        search_limit = int(node_data.get("searchLimit", 5))

        # The same rules as the document metadata: a filter that is not an object fails, as
        # searching without it would return documents it is there to exclude.
        metadata_filter = _json_object_field(
            self, node_data.get("metadataFilters", "{}"), inputs, node_id, "metadataFilters"
        )

        enable_reranker = node_data.get("enableReranker", False)
        reranker_credential_id = node_data.get("rerankerCredentialId")
        reranker_top_n = int(node_data.get("rerankerTopN", search_limit))

        initial_limit = search_limit
        if enable_reranker and reranker_credential_id:
            initial_limit = max(search_limit * 3, 20)

        hybrid_search = as_bool(node_data.get("hybridSearch", False))
        run_search = service.hybrid_search if hybrid_search else service.search
        results = run_search(
            collection_name,
            query_text,
            limit=initial_limit,
            metadata_filter=metadata_filter,
        )
        # Reranking replaces the hit objects, so keep each leg's score by id.
        leg_scores = (
            {
                r.id: {"vector_score": r.vector_score, "keyword_score": r.keyword_score}
                for r in results
            }
            if hybrid_search
            else {}
        )

        reranked = False
        reranker_trace_id: str | None = None
        if enable_reranker and reranker_credential_id and results:
            from app.db.models import CredentialType
            from app.services.reranker import DocumentToRerank, create_reranker_service

            reranker_config: dict = {}
            reranker_type = None
            with SessionLocal() as db:
                reranker_cred = self._get_accessible_credential(db, reranker_credential_id)
                if reranker_cred:
                    reranker_config = decrypt_config(reranker_cred.encrypted_config)
                    reranker_type = reranker_cred.type

            docs_to_rerank = [
                DocumentToRerank(
                    id=r.id,
                    text=r.text,
                    score=r.score,
                    metadata=r.metadata,
                )
                for r in results
            ]
            if reranker_type == CredentialType.decision:
                results, reranker_trace_id = _rerank_with_decision_model(
                    self,
                    node_id=node_id,
                    credential_id=str(reranker_credential_id),
                    config=reranker_config,
                    model=str(node_data.get("rerankerModel") or "").strip(),
                    query=query_text,
                    documents=docs_to_rerank,
                    top_n=reranker_top_n,
                )
                reranked = True
            elif reranker_config.get("api_key"):
                reranker_service = create_reranker_service(reranker_config["api_key"])
                reranked_results = reranker_service.rerank(
                    query=query_text,
                    documents=docs_to_rerank,
                    top_n=reranker_top_n,
                )
                results = reranked_results
                reranked = True

        if not reranked:
            results = results[: max(search_limit, 0)]

        if reranked:
            output = {
                "success": True,
                "operation": "search",
                "query": query_text,
                "reranked": True,
                "hybrid": hybrid_search,
                "results": [
                    {
                        "id": r.id,
                        "text": r.text,
                        "score": r.original_score,
                        "relevance_score": r.relevance_score,
                        "metadata": r.metadata,
                        **leg_scores.get(r.id, {}),
                    }
                    for r in results
                ],
                "count": len(results),
            }
            if reranker_trace_id:
                # The executor pops this into node metadata, which draws the Traces link.
                output["_trace_id"] = reranker_trace_id
        else:
            output = {
                "success": True,
                "operation": "search",
                "query": query_text,
                "reranked": False,
                "hybrid": hybrid_search,
                "results": [
                    {
                        "id": r.id,
                        "text": r.text,
                        "score": r.score,
                        "metadata": r.metadata,
                        **leg_scores.get(r.id, {}),
                    }
                    for r in results
                ],
                "count": len(results),
            }
    else:
        raise ValueError(f"Unknown RAG operation: {operation}")
    return output
