"""Syntax helpers shared by expression preview and workflow execution."""

import io
import tokenize

# `$global` reads as a Python keyword, so `ast.parse` rejects `global.x` outright and the
# whole expression silently degrades to the string-only fallback resolver.
_GLOBAL_CONTEXT_ALIAS = "heymGlobalContext"
_RESERVED_CONTEXT_ALIASES = {"global": _GLOBAL_CONTEXT_ALIAS}
RESERVED_CONTEXT_NAMES_BY_ALIAS = {alias: name for name, alias in _RESERVED_CONTEXT_ALIASES.items()}
_TOKEN_TYPES_WITHOUT_DOT_STATE = frozenset(
    {tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT}
)


def alias_reserved_context_names(expr: str) -> str:
    """Rewrite context names Python reserves so the expression parser accepts them."""
    if not any(name in expr for name in _RESERVED_CONTEXT_ALIASES):
        return expr
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(expr).readline))
    except Exception:  # noqa: BLE001 - unparseable input keeps its original form
        return expr

    replacements: list[tuple[int, int, int, str]] = []
    after_dot = False
    for token in tokens:
        if token.type == tokenize.NAME and not after_dot:
            alias = _RESERVED_CONTEXT_ALIASES.get(token.string)
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
