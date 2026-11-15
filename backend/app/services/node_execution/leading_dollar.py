"""Values that start with ``$``: one expression, or text that only starts with a reference."""

from __future__ import annotations

from typing import Any

from app.services.expression_evaluator import (
    should_evaluate_as_multi_ref_condition,
    should_evaluate_as_multi_span_comparison_condition,
)


def resolve_leading_dollar_value(
    executor: Any, template: str, inputs: dict, node_id: str
) -> object:
    """A value that starts with ``$``: one expression keeps its type.

    Text that only starts with a reference, such as ``$a.name signed up for $a.plan``,
    is not an expression and resolves to None; render it as the text template it is,
    as the expression dialog does. Ternaries and conditions keep resolving as expressions,
    so a ternary whose chosen branch is null stays null.
    """
    result = executor.resolve_expression(template, inputs, node_id, preserve_type=True)
    if (
        result is None
        and not executor._is_single_dollar_expression(template)
        and not executor._is_top_level_ternary_expression(template)
        and not should_evaluate_as_multi_ref_condition(template, executor)
        and not should_evaluate_as_multi_span_comparison_condition(template, executor)
    ):
        return executor.evaluate_message_template(template, inputs, node_id)
    return result
