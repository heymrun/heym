export type ContextRoot = "credentials" | "vars" | "global";

// Names Python reserves: `$vars.<word>` does not parse for these, so they need brackets.
const RESERVED_WORDS: ReadonlySet<string> = new Set([
  "False", "None", "True", "and", "as", "assert", "async", "await", "break", "class",
  "continue", "def", "del", "elif", "else", "except", "finally", "for", "from", "global",
  "if", "import", "in", "is", "lambda", "nonlocal", "not", "or", "pass", "raise", "return",
  "try", "while", "with", "yield",
]);

// Same rule as Python's `str.isidentifier`, which is what the expression parser applies.
const PLAIN_NAME = /^[\p{XID_Start}_]\p{XID_Continue}*$/u;

/**
 * What follows `$credentials`, `$vars` or `$global` for a name. `-` reads as subtraction, so
 * `$vars.my-var` resolves `my` minus `var`; such names need `["my-var"]`.
 * Backend counterpart for credentials: `credential_reference` in `credential_catalog.py`.
 */
export function contextAccessor(name: string): string {
  if (PLAIN_NAME.test(name) && !RESERVED_WORDS.has(name)) return name;
  return `[${JSON.stringify(name)}]`;
}

export function contextReference(root: ContextRoot, name: string): string {
  const accessor = contextAccessor(name);
  return accessor.startsWith("[") ? `$${root}${accessor}` : `$${root}.${accessor}`;
}
