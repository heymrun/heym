"""Helpers and service for unified expression evaluation."""

from __future__ import annotations

import ast
import inspect
import json
import re
from typing import Any, Callable, Literal

from pydantic import BaseModel

EXPRESSION_MAX_LENGTH = 10_000

ExpressionResultType = Literal["string", "number", "boolean", "array", "object", "null"]

# Between two `$node...` spans in a condition-style expression (same rules as workflow branch).
_CONDITION_GLUE_ONLY = re.compile(
    r"^(?:\s+|!=|==|<=|>=|&&|\|\||[<>()+*/%-]|\band\b|\bor\b|\bnot\b|"
    r"\btrue\b|\bfalse\b|\bnull\b|\bNone\b|\bundefined\b|[0-9]+(?:\.[0-9]+)?)*$",
    re.IGNORECASE,
)

# Require at least one comparison or binary operator so `$a.x and $b.y` stays a text template
# (literal "and") instead of Python boolean `and`. Include arithmetic so `$global.x - 50`
# is evaluated as an expression, not string template concatenation.
_CONDITION_HAS_OPERATOR = re.compile(r"!=|==|<=|>=|&&|\|\||[<>]|[+\-*/%]")

# Subset of operators that imply a boolean condition (vs arithmetic-only tail).
_CONDITION_HAS_COMPARISON = re.compile(
    r"!=|==|<=|>=|&&|\|\||[<>]|\band\b|\bor\b|\bnot\b",
    re.IGNORECASE,
)

# Explicit comparison operators only; excludes bare ``and/or/not`` text templates.
_CONDITION_HAS_EXPLICIT_COMPARISON = re.compile(r"!=|==|<=|>=|[<>]")

# Symbolic comparison/logical operators (excludes bare ``and/or/not`` keywords and pure arithmetic).
# Used to distinguish genuine conditions ($a.x != $b.y, $a.x && $b.y) from natural-language
# templates ($a.x and $b.y) and pure arithmetic ($a.length - $b.length).
_CONDITION_HAS_SYMBOLIC_OPERATOR = re.compile(r"!=|==|<=|>=|&&|\|\||[<>]")

# Entire trimmed value is a single nodeLabel.field... path without `$` (e.g. dialog selection text).
_UNPREFIXED_NODE_PATH = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+$")


class ExpressionTooLongError(ValueError):
    """Raised when an expression exceeds the configured maximum length."""


class ExpressionEvaluateResponse(BaseModel):
    """Structured evaluation response used by the API and the frontend dialog."""

    result: Any = None
    result_type: ExpressionResultType
    preserved_type: bool
    error: str | None = None
    selected_loop_total: int | None = None


def _fallback_find_expressions(text: str) -> list[tuple[int, int, str]]:
    """Return `$...` spans using the same parsing rules as the workflow executor."""
    expressions: list[tuple[int, int, str]] = []
    index = 0

    while index < len(text):
        if text[index] == "$" and index + 1 < len(text) and text[index + 1].isalpha():
            start = index
            index += 1
            while index < len(text) and (text[index].isalnum() or text[index] in "._"):
                index += 1
            while index < len(text):
                while index < len(text) and (text[index] == "(" or text[index] == "["):
                    bracket = text[index]
                    close_bracket = ")" if bracket == "(" else "]"
                    depth = 1
                    index += 1
                    while index < len(text) and depth > 0:
                        if text[index] == bracket:
                            depth += 1
                        elif text[index] == close_bracket:
                            depth -= 1
                        elif text[index] == '"' or text[index] == "'":
                            quote = text[index]
                            index += 1
                            while index < len(text) and text[index] != quote:
                                if text[index] == "\\":
                                    index += 1
                                index += 1
                        index += 1
                if index < len(text) and text[index] == ".":
                    index += 1
                    while index < len(text) and (text[index].isalnum() or text[index] == "_"):
                        index += 1
                    continue
                break
            expressions.append((start, index, text[start:index]))
        else:
            index += 1

    return expressions


def coerce_unprefixed_node_path_expression(trimmed: str) -> str:
    """If ``trimmed`` is only ``label.prop...`` (no ``$``), return ``$`` + path for evaluation.

    Used by the expression evaluate API so clients can send a bare path (e.g. text selected
    inside ``.get(...)``) without rewriting to ``$`` on the frontend.
    """
    if not trimmed or trimmed.startswith("$"):
        return trimmed
    if _UNPREFIXED_NODE_PATH.fullmatch(trimmed):
        return f"${trimmed}"
    return trimmed


def _split_ternary_expression(expression: str) -> tuple[str, str, str] | None:
    """Split a JS-like ternary expression into condition / truthy / falsy parts."""
    depth = 0
    in_string = False
    string_char = ""
    question_index = -1

    for index, char in enumerate(expression):
        if in_string:
            if char == string_char and expression[index - 1] != "\\":
                in_string = False
            continue

        if char in ("'", '"'):
            in_string = True
            string_char = char
            continue

        if char in "([{":
            depth += 1
            continue

        if char in ")]}":
            depth -= 1
            continue

        if char == "?" and depth == 0:
            next_char = expression[index + 1] if index + 1 < len(expression) else ""
            if next_char in {".", "["}:
                continue
            question_index = index
            break

    if question_index == -1:
        return None

    depth = 0
    in_string = False
    string_char = ""
    colon_index = -1

    for index in range(question_index + 1, len(expression)):
        char = expression[index]
        if in_string:
            if char == string_char and expression[index - 1] != "\\":
                in_string = False
            continue

        if char in ("'", '"'):
            in_string = True
            string_char = char
            continue

        if char in "([{":
            depth += 1
            continue

        if char in ")]}":
            depth -= 1
            continue

        if char == ":" and depth == 0:
            colon_index = index
            break

    if colon_index == -1:
        return None

    return (
        expression[:question_index].strip(),
        expression[question_index + 1 : colon_index].strip(),
        expression[colon_index + 1 :].strip(),
    )


def _fallback_transform_ternary_expression(expression: str) -> str:
    """Convert JS-like ternary syntax into a Python expression for syntax validation."""
    split = _split_ternary_expression(expression)
    if not split:
        return expression

    condition, truthy, falsy = split
    transformed_condition = _fallback_transform_ternary_expression(condition)
    transformed_truthy = _fallback_transform_ternary_expression(truthy)
    transformed_falsy = _fallback_transform_ternary_expression(falsy)
    return f"({transformed_truthy}) if ({transformed_condition}) else ({transformed_falsy})"


def is_single_dollar_expression(
    template: str,
    *,
    find_expressions: Callable[[str], list[tuple[int, int, str]]] | None = None,
    transform_ternary_expression: Callable[[str], str] | None = None,
) -> bool:
    """Return True when the full trimmed value is one `$expr`, not a text template."""
    trimmed = template.strip()
    if not trimmed.startswith("$"):
        return False

    find = find_expressions or _fallback_find_expressions
    transform = transform_ternary_expression or _fallback_transform_ternary_expression
    expr_body = trimmed[1:].strip()
    if not expr_body:
        return False
    if re.fullmatch(r"\d+(?:\.\d+)?", expr_body):
        return False

    found = find(trimmed)
    if len(found) == 1:
        start, end, _expr = found[0]
        if start == 0 and end == len(trimmed):
            return True

    transformed = transform(expr_body)
    try:
        ast.parse(transformed, mode="eval")
    except SyntaxError:
        return False
    return True


def should_evaluate_as_multi_ref_condition(
    expression: str,
    executor: Any,
) -> bool:
    """True when the value is a multi-`$ref` comparison like ``$a.x != $b.y`` (not a text template)."""
    trimmed = expression.strip()
    if not trimmed.startswith("$"):
        return False
    if not _CONDITION_HAS_SYMBOLIC_OPERATOR.search(trimmed):
        return False
    if is_single_dollar_expression(
        trimmed,
        find_expressions=executor._find_expressions,
        transform_ternary_expression=executor._transform_ternary_expression,
    ):
        return False

    spans: list[tuple[int, int, str]] = executor._find_expressions(trimmed)
    if len(spans) < 2:
        return False
    if spans[0][0] != 0:
        return False
    for idx in range(len(spans) - 1):
        glue = trimmed[spans[idx][1] : spans[idx + 1][0]]
        if not glue or not _CONDITION_GLUE_ONLY.fullmatch(glue):
            return False
    tail = trimmed[spans[-1][1] :]
    if tail and not _CONDITION_GLUE_ONLY.fullmatch(tail):
        return False
    return True


def _code_nesting_depth_before_index(text: str, end_index: int) -> int:
    """Return nesting depth from ``(``, ``[``, ``{`` before ``end_index`` (strings ignored)."""
    paren = 0
    square = 0
    curly = 0
    index = 0
    in_string: str | None = None
    while index < end_index:
        char = text[index]
        if in_string is not None:
            if char == "\\" and index + 1 < end_index:
                index += 2
                continue
            if char == in_string:
                in_string = None
            index += 1
            continue
        if char in ('"', "'"):
            in_string = char
            index += 1
            continue
        if char == "(":
            paren += 1
        elif char == ")":
            paren = max(0, paren - 1)
        elif char == "[":
            square += 1
        elif char == "]":
            square = max(0, square - 1)
        elif char == "{":
            curly += 1
        elif char == "}":
            curly = max(0, curly - 1)
        index += 1
    return paren + square + curly


def _any_dollar_span_under_code_nesting(trimmed: str, executor: Any) -> bool:
    """True when at least one ``$`` expression starts inside ``()``, ``[]``, or ``{}``."""
    for start, _end, _expr in executor._find_expressions(trimmed):
        if _code_nesting_depth_before_index(trimmed, start) > 0:
            return True
    return False


def _probe_substituted_expression_ast_ok(trimmed: str, executor: Any) -> bool:
    """True when replacing each ``$...`` span with ``0`` yields valid ``ast.parse(..., mode='eval')``."""
    spans = executor._find_expressions(trimmed)
    if not spans:
        return False
    parts: list[str] = []
    last_end = 0
    for start, end, _expr in spans:
        parts.append(trimmed[last_end:start])
        parts.append("0")
        last_end = end
    parts.append(trimmed[last_end:])
    probe = "".join(parts)
    probe = executor._transform_ternary_expression(probe)
    probe = re.sub(r"&&", " and ", probe)
    probe = re.sub(r"\|\|", " or ", probe)
    try:
        ast.parse(probe, mode="eval")
    except SyntaxError:
        return False
    return True


def should_evaluate_as_multi_span_comparison_condition(
    expression: str,
    executor: Any,
) -> bool:
    """True for repeated ``$...`` spans combined with literal comparisons.

    Covers expressions like ``$agent.action == "buy" || $agent.action == "sell"``,
    which should be evaluated as a boolean condition instead of a string template.
    """
    trimmed = expression.strip()
    if not trimmed.startswith("$"):
        return False
    if not _CONDITION_HAS_EXPLICIT_COMPARISON.search(trimmed):
        return False
    if is_single_dollar_expression(
        trimmed,
        find_expressions=executor._find_expressions,
        transform_ternary_expression=executor._transform_ternary_expression,
    ):
        return False

    spans = executor._find_expressions(trimmed)
    if len(spans) < 2 or spans[0][0] != 0:
        return False
    return _probe_substituted_expression_ast_ok(trimmed, executor)


def should_resolve_embedded_dollar_refs_arithmetically(trimmed: str, executor: Any) -> bool:
    """Prefer ``resolve_arithmetic_expression`` over string templates for code-like values.

    Covers ``int($node.field)``, ``max(1, $x)``, ``items[$i]``, and ``1 + $x`` while keeping
    natural-language templates like ``$a.x and $b.y`` on the message-template path.
    """
    if "$" not in trimmed or not trimmed.strip():
        return False
    if _any_dollar_span_under_code_nesting(trimmed, executor):
        return True
    if trimmed.lstrip().startswith("$"):
        # Multi-ref arithmetic like `$a.length - $b.length`: two or more $spans connected
        # exclusively by arithmetic operators in the GLUE between them.  We inspect the
        # glue text (not the full expression) to avoid false-positives from operators
        # embedded inside string literals in the $spans themselves (e.g. "user-agent").
        spans = executor._find_expressions(trimmed)
        if len(spans) < 2 or spans[0][0] != 0:
            return False
        has_arithmetic_glue = False
        for idx in range(len(spans) - 1):
            glue = trimmed[spans[idx][1] : spans[idx + 1][0]]
            if not glue or not _CONDITION_GLUE_ONLY.fullmatch(glue):
                return False
            if _CONDITION_HAS_SYMBOLIC_OPERATOR.search(glue):
                return False
            if re.search(r"[+\-*/%]", glue):
                has_arithmetic_glue = True
        tail = trimmed[spans[-1][1] :]
        if tail and not _CONDITION_GLUE_ONLY.fullmatch(tail):
            return False
        if tail and _CONDITION_HAS_SYMBOLIC_OPERATOR.search(tail):
            return False
        return has_arithmetic_glue
    return _probe_substituted_expression_ast_ok(trimmed, executor)


def should_evaluate_as_single_span_condition_tail(expression: str, executor: Any) -> bool:
    """True for one leading ``$...`` span plus a comparison tail (e.g. ``.get($inner) != null``).

    Nested ``$`` inside the span breaks ``is_single_dollar_expression``'s ``ast.parse`` check, which
    would otherwise fall through to string template evaluation and lose boolean typing.
    """
    trimmed = expression.strip()
    if not trimmed.startswith("$"):
        return False
    if not _CONDITION_HAS_OPERATOR.search(trimmed):
        return False
    if is_single_dollar_expression(
        trimmed,
        find_expressions=executor._find_expressions,
        transform_ternary_expression=executor._transform_ternary_expression,
    ):
        return False

    spans: list[tuple[int, int, str]] = executor._find_expressions(trimmed)
    if len(spans) != 1:
        return False
    start, end, _ = spans[0]
    if start != 0:
        return False
    tail = trimmed[end:]
    if not tail or not _CONDITION_GLUE_ONLY.fullmatch(tail):
        return False
    return True


def classify_type(value: Any) -> ExpressionResultType:
    """Classify a Python value into a frontend-friendly JSON-ish type."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "string"


def _serialize_template_line_value(value: Any) -> str:
    """Serialize a standalone expression result for insertion into a string template line."""
    if value is None:
        return "null"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _resolve_upstream_labels(
    workflow_nodes: list[dict[str, Any]],
    workflow_edges: list[dict[str, Any]] | None,
    current_node_id: str | None,
) -> set[str] | None:
    """Resolve upstream node labels for the current node when graph data is available."""
    if not workflow_edges or not current_node_id:
        return None

    from app.services.workflow_executor import WorkflowExecutor

    executor = WorkflowExecutor(nodes=workflow_nodes, edges=workflow_edges)
    if current_node_id not in executor.nodes:
        return None
    return executor.get_upstream_node_labels(current_node_id)


def _selected_loop_node_id_for_current_node(
    workflow_nodes: list[dict[str, Any]],
    workflow_edges: list[dict[str, Any]] | None,
    current_node_id: str | None,
) -> str | None:
    """Return the innermost loop relevant to ``current_node_id`` for preview selection."""
    if not workflow_edges or not current_node_id:
        return None

    from app.services.workflow_executor import WorkflowExecutor

    executor = WorkflowExecutor(nodes=workflow_nodes, edges=workflow_edges)
    current_node = executor.nodes.get(current_node_id)
    if current_node and current_node.get("type") == "loop":
        return current_node_id

    loop_nodes = [node for node in workflow_nodes if node.get("type") == "loop" and node.get("id")]
    best_loop_id: str | None = None
    best_body_size: int | None = None

    for loop_node in loop_nodes:
        loop_id = str(loop_node["id"])
        body = executor.get_loop_body_node_ids(loop_id, workflow_edges)
        if current_node_id not in body:
            continue
        body_size = len(body)
        if (
            best_body_size is None
            or body_size < best_body_size
            or (body_size == best_body_size and loop_id < (best_loop_id or loop_id))
        ):
            best_loop_id = loop_id
            best_body_size = body_size

    return best_loop_id


def _loop_branch_from_output(output: Any) -> str | None:
    """Return the executor loop branch string from a node output."""
    if not isinstance(output, dict):
        return None
    branch = output.get("branch")
    return branch if isinstance(branch, str) and branch else None


def _loop_iteration_index_from_output(output: Any) -> int | None:
    """Return the executor loop iteration index from a node output."""
    if _loop_branch_from_output(output) != "loop" or not isinstance(output, dict):
        return None
    raw = output.get("index")
    if isinstance(raw, int) and raw >= 0:
        return raw
    if isinstance(raw, float) and raw.is_integer() and raw >= 0:
        return int(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = int(raw)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _non_negative_int(value: Any) -> int | None:
    """Return a non-negative integer when ``value`` can be losslessly coerced."""
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed >= 0 else None
    return None


def _canvas_outputs_by_label(
    workflow_nodes: list[dict[str, Any]],
    canvas_results: list[dict[str, Any]],
    *,
    workflow_edges: list[dict[str, Any]] | None = None,
    current_node_id: str | None = None,
    selected_loop_iteration_index: int | None = None,
) -> dict[str, Any]:
    """Choose per-label canvas outputs, optionally scoped to one loop iteration."""
    latest_by_label = {
        item["label"]: item.get("output") for item in canvas_results if item.get("label")
    }
    loop_id = _selected_loop_node_id_for_current_node(
        workflow_nodes,
        workflow_edges,
        current_node_id,
    )
    if (
        not loop_id
        or not workflow_edges
        or selected_loop_iteration_index is None
        or selected_loop_iteration_index < 0
    ):
        return latest_by_label

    from app.services.workflow_executor import WorkflowExecutor

    executor = WorkflowExecutor(nodes=workflow_nodes, edges=workflow_edges)
    loop_body_ids = executor.get_loop_body_node_ids(loop_id, workflow_edges)
    if not loop_body_ids and loop_id not in executor.nodes:
        return latest_by_label

    selected_by_label: dict[str, Any] = {}
    active_iteration_index: int | None = None

    for item in canvas_results:
        node_id = item.get("node_id")
        label = item.get("label")
        output = item.get("output")

        if node_id == loop_id:
            branch = _loop_branch_from_output(output)
            if branch == "loop":
                active_iteration_index = _loop_iteration_index_from_output(output)
                if active_iteration_index == selected_loop_iteration_index and label:
                    selected_by_label[label] = output
            elif branch == "done":
                active_iteration_index = None
            continue

        if (
            node_id in loop_body_ids
            and active_iteration_index == selected_loop_iteration_index
            and label
        ):
            selected_by_label[label] = output

    if not selected_by_label:
        return latest_by_label

    return {
        **latest_by_label,
        **selected_by_label,
    }


def _text_input_preview_output(initial_inputs: Any) -> dict[str, Any]:
    """Mirror the textInput node runtime output shape for evaluator previews."""
    if not isinstance(initial_inputs, dict):
        return {}

    output = dict(initial_inputs)
    body = output.get("body")
    if isinstance(body, dict):
        output.update(body)
    return output


def _toposort_enclosing_loop_nodes(
    enclosing_loops: list[dict[str, Any]],
    workflow_edges: list[dict[str, Any]],
    executor: Any,
) -> list[dict[str, Any]]:
    """Order outer loops before inner loops so ``arrayExpression`` can use ``$outer.item``."""
    ids = [n["id"] for n in enclosing_loops if n.get("id")]
    if len(ids) <= 1:
        return enclosing_loops

    prereqs: dict[str, set[str]] = {lid: set() for lid in ids}
    for outer in enclosing_loops:
        oid = outer.get("id")
        if not oid:
            continue
        outer_body = executor.get_loop_body_node_ids(oid, workflow_edges)
        for inner in enclosing_loops:
            iid = inner.get("id")
            if not iid or iid == oid:
                continue
            if iid in outer_body:
                prereqs[iid].add(oid)

    result_ids: list[str] = []
    queue = [lid for lid in ids if not prereqs[lid]]
    while queue:
        lid = queue.pop(0)
        result_ids.append(lid)
        for other in ids:
            if lid in prereqs[other]:
                prereqs[other].discard(lid)
                if not prereqs[other] and other not in result_ids and other not in queue:
                    queue.append(other)

    if len(result_ids) != len(ids):
        return enclosing_loops
    id_to_node = {n["id"]: n for n in enclosing_loops if n.get("id")}
    return [id_to_node[lid] for lid in result_ids]


def _inject_loop_preview_context_for_evaluator(
    workflow_nodes: list[dict[str, Any]],
    workflow_edges: list[dict[str, Any]],
    current_node_id: str,
    context: dict[str, Any],
    *,
    selected_loop_node_id: str | None = None,
    selected_loop_iteration_index: int | None = None,
) -> None:
    """Synthesize loop ``item``/``index``/… for nodes inside a loop body.

    After a full workflow run the canvas often stores the loop node's **done** output, which has
    no ``item``. Expression preview would show ``$loopLabel.*`` as null even though iterations
    work at runtime. Recompute the first iteration from ``arrayExpression`` instead.
    """
    from app.services.workflow_executor import WorkflowExecutor

    executor = WorkflowExecutor(nodes=workflow_nodes, edges=workflow_edges)
    if current_node_id not in executor.nodes:
        return

    enclosing: list[dict[str, Any]] = []
    for node in workflow_nodes:
        if node.get("type") != "loop":
            continue
        loop_nid = node.get("id")
        if not loop_nid:
            continue
        if current_node_id in executor.get_loop_body_node_ids(loop_nid, workflow_edges):
            enclosing.append(node)

    if not enclosing:
        return

    ordered = _toposort_enclosing_loop_nodes(enclosing, workflow_edges, executor)
    for loop_node in ordered:
        data = loop_node.get("data") or {}
        label = data.get("label")
        if not label:
            continue
        array_expression = data.get("arrayExpression", "$input")
        try:
            if array_expression.startswith("$"):
                array_value = executor.resolve_expression(
                    array_expression,
                    context,
                    current_node_id,
                    preserve_type=True,
                )
            else:
                array_value = executor.evaluate_message_template(
                    array_expression,
                    context,
                    current_node_id,
                )
        except Exception:
            continue

        if not isinstance(array_value, list):
            items: list[Any] = [] if array_value is None else [array_value]
        else:
            items = array_value

        total = len(items)
        preview_index = 0
        if (
            selected_loop_iteration_index is not None
            and selected_loop_iteration_index >= 0
            and loop_node.get("id") == selected_loop_node_id
            and total > 0
        ):
            preview_index = min(selected_loop_iteration_index, total - 1)
        if total == 0:
            context[label] = {
                "item": None,
                "index": 0,
                "total": 0,
                "isFirst": True,
                "isLast": True,
                "branch": "loop",
            }
        else:
            context[label] = {
                "item": items[preview_index],
                "index": preview_index,
                "total": total,
                "isFirst": preview_index == 0,
                "isLast": preview_index == total - 1,
                "branch": "loop",
            }


def _evaluate_set_like_preview_output(
    node: dict[str, Any],
    context: dict[str, Any],
    executor: Any,
) -> dict[str, Any] | None:
    """Mirror executor semantics for ``set`` / ``jsonOutputMapper`` preview outputs."""
    node_id = node.get("id")
    if not isinstance(node_id, str) or not node_id:
        return None

    mappings = (node.get("data") or {}).get("mappings")
    if not isinstance(mappings, list):
        return {}

    result: dict[str, Any] = {}
    try:
        for mapping in mappings:
            if not isinstance(mapping, dict):
                continue
            key = mapping.get("key", "")
            if not isinstance(key, str) or not key:
                continue

            value_template = mapping.get("value", "")
            if not isinstance(value_template, str):
                result[key] = value_template
                continue

            if executor._has_arithmetic(value_template):
                result[key] = executor.resolve_arithmetic_expression(
                    value_template,
                    context,
                    node_id,
                    preserve_type=True,
                )
            elif executor._is_single_dollar_expression(value_template):
                result[key] = executor.resolve_expression(
                    value_template.strip(),
                    context,
                    node_id,
                    preserve_type=True,
                )
            elif "$" in value_template:
                result[key] = executor._resolve_value_with_dollar_refs(
                    value_template,
                    context,
                    node_id,
                )
            else:
                result[key] = value_template
    except Exception:
        return None

    return result


def _inject_upstream_set_like_preview_outputs(
    workflow_nodes: list[dict[str, Any]],
    workflow_edges: list[dict[str, Any]],
    current_node_id: str,
    context: dict[str, Any],
    allowed_labels: set[str] | None,
) -> None:
    """Synthesize upstream ``set`` / ``jsonOutputMapper`` outputs when preview-only context is missing."""
    from app.services.workflow_executor import WorkflowExecutor

    executor = WorkflowExecutor(nodes=workflow_nodes, edges=workflow_edges)
    if current_node_id not in executor.nodes:
        return

    node_by_id = {
        str(node["id"]): node for node in workflow_nodes if isinstance(node.get("id"), str)
    }
    upstream_ids = executor.get_upstream_node_ids(current_node_id)
    if not upstream_ids:
        return

    forward_edges = [edge for edge in workflow_edges if edge.get("targetHandle") != "loop"]
    direct_source_labels: dict[str, set[str]] = {}
    for edge in forward_edges:
        target = edge.get("target")
        source = edge.get("source")
        if not isinstance(target, str) or target not in upstream_ids:
            continue
        if not isinstance(source, str):
            continue
        source_node = node_by_id.get(source)
        source_label = (source_node or {}).get("data", {}).get("label")
        if isinstance(source_label, str) and source_label:
            direct_source_labels.setdefault(target, set()).add(source_label)

    remaining = {
        node_id
        for node_id in upstream_ids
        if (node_by_id.get(node_id) or {}).get("type") in ("set", "jsonOutputMapper")
    }
    while remaining:
        progressed = False
        for node_id in list(remaining):
            node = node_by_id.get(node_id)
            if not node:
                remaining.discard(node_id)
                continue

            label = (node.get("data") or {}).get("label")
            if not isinstance(label, str) or not label:
                remaining.discard(node_id)
                continue
            if allowed_labels is not None and label not in allowed_labels:
                remaining.discard(node_id)
                continue
            if label in context:
                remaining.discard(node_id)
                continue

            required_labels = direct_source_labels.get(node_id, set())
            if any(required_label not in context for required_label in required_labels):
                continue

            preview_output = _evaluate_set_like_preview_output(node, context, executor)
            if preview_output is None:
                continue

            context[label] = preview_output
            remaining.discard(node_id)
            progressed = True

        if not progressed:
            break


def build_eval_context(
    workflow_nodes: list[dict[str, Any]],
    canvas_results: list[dict[str, Any]],
    *,
    workflow_edges: list[dict[str, Any]] | None = None,
    current_node_id: str | None = None,
    initial_inputs: Any = None,
    selected_loop_iteration_index: int | None = None,
) -> dict[str, Any]:
    """Build label -> output context where pinned data wins over last-run canvas outputs."""
    allowed_labels = _resolve_upstream_labels(workflow_nodes, workflow_edges, current_node_id)
    canvas_by_label = _canvas_outputs_by_label(
        workflow_nodes,
        canvas_results,
        workflow_edges=workflow_edges,
        current_node_id=current_node_id,
        selected_loop_iteration_index=selected_loop_iteration_index,
    )
    input_preview_output = _text_input_preview_output(initial_inputs)
    selected_loop_node_id = _selected_loop_node_id_for_current_node(
        workflow_nodes,
        workflow_edges,
        current_node_id,
    )

    context: dict[str, Any] = {}
    for node in workflow_nodes:
        data = node.get("data") or {}
        label = data.get("label")
        if not label:
            continue
        if allowed_labels is not None and label not in allowed_labels:
            continue

        pinned_data = data.get("pinnedData")
        if pinned_data is not None:
            context[label] = pinned_data
            continue

        if node.get("type") == "textInput" and input_preview_output:
            context[label] = input_preview_output
            continue

        if label in canvas_by_label:
            context[label] = canvas_by_label[label]

    if workflow_edges and current_node_id:
        _inject_loop_preview_context_for_evaluator(
            workflow_nodes,
            workflow_edges,
            current_node_id,
            context,
            selected_loop_node_id=selected_loop_node_id,
            selected_loop_iteration_index=selected_loop_iteration_index,
        )
        _inject_upstream_set_like_preview_outputs(
            workflow_nodes,
            workflow_edges,
            current_node_id,
            context,
            allowed_labels,
        )

    return context


def get_selected_loop_total(
    workflow_nodes: list[dict[str, Any]],
    workflow_edges: list[dict[str, Any]] | None,
    current_node_id: str | None,
    context: dict[str, Any],
    evaluator: ExpressionEvaluatorService | None = None,
) -> int | None:
    """Return the active enclosing loop's total item count for evaluator responses."""
    loop_node_id = _selected_loop_node_id_for_current_node(
        workflow_nodes,
        workflow_edges,
        current_node_id,
    )
    if not loop_node_id:
        return None

    loop_node = next(
        (node for node in workflow_nodes if node.get("id") == loop_node_id),
        None,
    )
    if not loop_node:
        return None

    label = (loop_node.get("data") or {}).get("label")
    if not isinstance(label, str) or not label:
        return None

    loop_value = context.get(label)
    if isinstance(loop_value, dict):
        total = _non_negative_int(loop_value.get("total"))
        if total is not None:
            return total

    if evaluator is None:
        return None

    array_expression = (loop_node.get("data") or {}).get("arrayExpression")
    if not isinstance(array_expression, str) or not array_expression.strip():
        array_expression = "$input"

    evaluated = evaluator.evaluate(
        array_expression,
        context,
        current_node_id=current_node_id,
    )
    if evaluated.error:
        return None

    result = evaluated.result
    if result is None:
        return 0
    if isinstance(result, list):
        return len(result)
    return 1


def build_vars_context(
    workflow_nodes: list[dict[str, Any]],
    canvas_results: list[dict[str, Any]],
    *,
    workflow_edges: list[dict[str, Any]] | None = None,
    current_node_id: str | None = None,
) -> dict[str, Any]:
    """Build the `$vars` namespace from upstream variable node outputs or pinned data."""
    allowed_labels = _resolve_upstream_labels(workflow_nodes, workflow_edges, current_node_id)
    canvas_by_label = {
        item["label"]: item.get("output") for item in canvas_results if item.get("label")
    }

    vars_context: dict[str, Any] = {}
    for node in workflow_nodes:
        if node.get("type") != "variable":
            continue

        data = node.get("data") or {}
        label = data.get("label")
        variable_name = data.get("variableName")
        if not label or not variable_name:
            continue
        if allowed_labels is not None and label not in allowed_labels:
            continue

        value_source = data.get("pinnedData")
        if value_source is None:
            value_source = canvas_by_label.get(label)

        if isinstance(value_source, dict) and "value" in value_source:
            vars_context[variable_name] = value_source.get("value")
        elif value_source is not None:
            vars_context[variable_name] = value_source

    return vars_context


class ExpressionEvaluatorService:
    """Evaluate expressions using the workflow executor's existing semantics."""

    def __init__(
        self,
        *,
        workflow_nodes: list[dict[str, Any]] | None = None,
        workflow_edges: list[dict[str, Any]] | None = None,
        credentials_context: dict[str, str] | None = None,
        global_variables_context: dict[str, Any] | None = None,
        vars_context: dict[str, Any] | None = None,
    ) -> None:
        self.workflow_nodes = workflow_nodes or []
        self.workflow_edges = workflow_edges or []
        self.credentials_context = credentials_context or {}
        self.global_variables_context = global_variables_context or {}
        self.vars_context = vars_context or {}

    def evaluate(
        self,
        expression: str,
        context: dict[str, Any],
        *,
        current_node_id: str | None = None,
    ) -> ExpressionEvaluateResponse:
        """Evaluate a unified expression/template string against the provided context."""
        if len(expression) > EXPRESSION_MAX_LENGTH:
            raise ExpressionTooLongError(
                f"Expression length {len(expression)} exceeds maximum {EXPRESSION_MAX_LENGTH}"
            )

        if expression == "":
            return ExpressionEvaluateResponse(
                result="",
                result_type="string",
                preserved_type=False,
                error=None,
            )

        from app.services.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor(
            nodes=self.workflow_nodes,
            edges=self.workflow_edges,
            credentials_context=self.credentials_context,
            global_variables_context=self.global_variables_context,
        )
        executor.vars = dict(self.vars_context)
        raw_trimmed = expression.strip()
        if "\n" in raw_trimmed or "\r" in raw_trimmed:
            trimmed = raw_trimmed
        else:
            trimmed = coerce_unprefixed_node_path_expression(raw_trimmed)
        found_expressions = executor._find_expressions(trimmed) if trimmed else []

        def evaluate_template_lines(source: str) -> str:
            rendered_parts: list[str] = []
            for raw_line in source.splitlines(keepends=True):
                line = raw_line.rstrip("\r\n")
                newline = raw_line[len(line) :]
                trimmed_line = line.strip()

                if not trimmed_line:
                    rendered_parts.append(raw_line)
                    continue

                if is_single_dollar_expression(
                    trimmed_line,
                    find_expressions=executor._find_expressions,
                    transform_ternary_expression=executor._transform_ternary_expression,
                ):
                    value = executor.resolve_expression(
                        trimmed_line,
                        context,
                        current_node_id,
                        preserve_type=False,
                    )
                    rendered_parts.append(_serialize_template_line_value(value) + newline)
                    continue

                if "$" in line:
                    rendered_parts.append(
                        executor.evaluate_message_template(line, context, current_node_id) + newline
                    )
                    continue

                rendered_parts.append(raw_line)

            return "".join(rendered_parts)

        try:
            if is_single_dollar_expression(
                trimmed,
                find_expressions=executor._find_expressions,
                transform_ternary_expression=executor._transform_ternary_expression,
            ):
                result = executor.resolve_expression(
                    trimmed,
                    context,
                    current_node_id,
                    preserve_type=True,
                )
                if callable(result) and not trimmed.endswith(")"):
                    try:
                        signature = inspect.signature(result)
                    except (TypeError, ValueError):
                        signature = None

                    if signature is not None:
                        required_params = [
                            param
                            for param in signature.parameters.values()
                            if param.kind
                            not in (
                                inspect.Parameter.VAR_POSITIONAL,
                                inspect.Parameter.VAR_KEYWORD,
                            )
                            and param.default is inspect.Signature.empty
                        ]
                        if not required_params:
                            result = executor._unwrap_value(result())
                return ExpressionEvaluateResponse(
                    result=result,
                    result_type=classify_type(result),
                    preserved_type=True,
                    error=None,
                )

            if trimmed.startswith("$") and not found_expressions:
                return ExpressionEvaluateResponse(
                    result=None,
                    result_type="null",
                    preserved_type=False,
                    error="Invalid expression",
                )

            if "$" in trimmed:
                if "\n" not in expression and "\r" not in expression:
                    if should_evaluate_as_multi_ref_condition(trimmed, executor):
                        try:
                            cond_result = executor.evaluate_condition_strict(
                                trimmed, context, current_node_id
                            )
                            return ExpressionEvaluateResponse(
                                result=cond_result,
                                result_type="boolean",
                                preserved_type=True,
                                error=None,
                            )
                        except Exception as exc:  # noqa: BLE001
                            return ExpressionEvaluateResponse(
                                result=None,
                                result_type="null",
                                preserved_type=False,
                                error=str(exc),
                            )
                    if should_evaluate_as_single_span_condition_tail(trimmed, executor):
                        try:
                            if _CONDITION_HAS_COMPARISON.search(trimmed):
                                cond_result = executor.evaluate_condition_strict(
                                    trimmed, context, current_node_id
                                )
                                return ExpressionEvaluateResponse(
                                    result=cond_result,
                                    result_type="boolean",
                                    preserved_type=True,
                                    error=None,
                                )
                            value_result = executor.evaluate_expression_tail_strict(
                                trimmed, context, current_node_id
                            )
                            return ExpressionEvaluateResponse(
                                result=value_result,
                                result_type=classify_type(value_result),
                                preserved_type=True,
                                error=None,
                            )
                        except Exception as exc:  # noqa: BLE001
                            return ExpressionEvaluateResponse(
                                result=None,
                                result_type="null",
                                preserved_type=False,
                                error=str(exc),
                            )
                    if should_evaluate_as_multi_span_comparison_condition(trimmed, executor):
                        try:
                            cond_result = executor.evaluate_condition_strict(
                                trimmed, context, current_node_id
                            )
                            return ExpressionEvaluateResponse(
                                result=cond_result,
                                result_type="boolean",
                                preserved_type=True,
                                error=None,
                            )
                        except Exception as exc:  # noqa: BLE001
                            return ExpressionEvaluateResponse(
                                result=None,
                                result_type="null",
                                preserved_type=False,
                                error=str(exc),
                            )

                if "\n" in expression or "\r" in expression:
                    result = evaluate_template_lines(expression)
                else:
                    if should_resolve_embedded_dollar_refs_arithmetically(trimmed, executor):
                        try:
                            result = executor.resolve_arithmetic_expression(
                                trimmed, context, current_node_id, preserve_type=True
                            )
                            return ExpressionEvaluateResponse(
                                result=result,
                                result_type=classify_type(result),
                                preserved_type=True,
                                error=None,
                            )
                        except Exception as exc:  # noqa: BLE001
                            return ExpressionEvaluateResponse(
                                result=None,
                                result_type="null",
                                preserved_type=False,
                                error=str(exc),
                            )
                    result = executor.evaluate_message_template(trimmed, context, current_node_id)
                return ExpressionEvaluateResponse(
                    result=result,
                    result_type=classify_type(result),
                    preserved_type=False,
                    error=None,
                )

            return ExpressionEvaluateResponse(
                result=expression,
                result_type="string",
                preserved_type=False,
                error=None,
            )
        except Exception as exc:  # noqa: BLE001
            return ExpressionEvaluateResponse(
                result=None,
                result_type="null",
                preserved_type=False,
                error=str(exc),
            )


_classify_type = classify_type
_is_single_dollar_expression = is_single_dollar_expression
