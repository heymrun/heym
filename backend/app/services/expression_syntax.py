"""Syntax helpers shared by expression preview and workflow execution."""

import ast
import io
import keyword
import tokenize

# `$global` reads as a Python keyword, so `ast.parse` rejects `global.x` outright and the
# whole expression silently degrades to the string-only fallback resolver.
_GLOBAL_CONTEXT_ALIAS = "heymGlobalContext"
_RESERVED_CONTEXT_ALIASES = {"global": _GLOBAL_CONTEXT_ALIAS}
RESERVED_CONTEXT_NAMES_BY_ALIAS = {alias: name for name, alias in _RESERVED_CONTEXT_ALIASES.items()}
_RESERVED_ATTRIBUTE_NAMES = frozenset(keyword.kwlist)
_TOKEN_TYPES_WITHOUT_DOT_STATE = frozenset(
    {tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT}
)


def _reserved_attribute_aliases(expr: str) -> dict[str, str]:
    prefix = "__heymKeyword_"
    while prefix in expr:
        prefix = f"_{prefix}"
    return {name: f"{prefix}{name}" for name in _RESERVED_ATTRIBUTE_NAMES}


def alias_reserved_context_names(expr: str) -> str:
    """Rewrite reserved context names and dotted keys so Python can parse the expression."""
    if not any(name in expr for name in (*_RESERVED_CONTEXT_ALIASES, *_RESERVED_ATTRIBUTE_NAMES)):
        return expr
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(expr).readline))
    except Exception:  # noqa: BLE001 - unparseable input keeps its original form
        return expr

    attribute_aliases = _reserved_attribute_aliases(expr)
    replacements: list[tuple[int, int, int, str]] = []
    after_dot = False
    for token in tokens:
        if token.type == tokenize.NAME:
            aliases = attribute_aliases if after_dot else _RESERVED_CONTEXT_ALIASES
            alias = aliases.get(token.string)
            if alias:
                replacements.append((token.start[0] - 1, token.start[1], token.end[1], alias))
        if token.type not in _TOKEN_TYPES_WITHOUT_DOT_STATE:
            after_dot = token.type == tokenize.OP and token.string == "."
    if not replacements:
        return expr

    lines = expr.splitlines(keepends=True)
    for line_index, col_start, col_end, alias in reversed(replacements):
        if line_index >= len(lines):
            return expr
        line = lines[line_index]
        lines[line_index] = line[:col_start] + alias + line[col_end:]
    return "".join(lines)


def restore_reserved_attribute_names(tree: ast.AST, expr: str) -> ast.AST:
    """Restore dotted keys on the parsed tree, retaining ordinary attribute semantics."""
    names_by_alias = {alias: name for name, alias in _reserved_attribute_aliases(expr).items()}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            node.attr = names_by_alias.get(node.attr, node.attr)
    return tree
