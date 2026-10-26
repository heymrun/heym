/**
 * Search for the Ctrl+K palette: every word of the query has to match, by prefix,
 * substring, a compact subsequence or a one-letter typo, and a word naming a group
 * ("tab", "workflow", "template", "doc") narrows the results to that group.
 */

export type PaletteScope = "tabs" | "workflows" | "templates" | "docs";

export interface PaletteQuery {
  terms: string[];
  scope: PaletteScope | null;
}

const SCOPE_WORDS: Record<string, PaletteScope> = {
  tab: "tabs",
  tabs: "tabs",
  workflow: "workflows",
  workflows: "workflows",
  template: "templates",
  templates: "templates",
  doc: "docs",
  docs: "docs",
};

function tokenize(raw: string): string[] {
  return raw.toLowerCase().trim().split(/\s+/).filter(Boolean);
}

/** Reads a group word at either end of the query: "mcp tab" and "tab mcp" both search tabs. */
export function parsePaletteQuery(raw: string): PaletteQuery {
  const tokens = tokenize(raw);
  if (tokens.length === 0) return { terms: [], scope: null };
  const last = SCOPE_WORDS[tokens[tokens.length - 1]];
  if (last) return { terms: tokens.slice(0, -1), scope: last };
  const first = SCOPE_WORDS[tokens[0]];
  if (first) return { terms: tokens.slice(1), scope: first };
  return { terms: tokens, scope: null };
}

/** The same query with its group word read as an ordinary search word. */
export function unscopedQuery(raw: string): PaletteQuery {
  return { terms: tokenize(raw), scope: null };
}

function withinOneEdit(a: string, b: string): boolean {
  if (Math.abs(a.length - b.length) > 1) return false;
  let i = 0;
  while (i < a.length && i < b.length && a[i] === b[i]) i += 1;
  if (i === a.length && i === b.length) return true;
  const transposed =
    a.length === b.length && a[i] === b[i + 1] && a[i + 1] === b[i] && a.slice(i + 2) === b.slice(i + 2);
  return (
    transposed ||
    a.slice(i + 1) === b.slice(i + 1) ||
    a.slice(i) === b.slice(i + 1) ||
    a.slice(i + 1) === b.slice(i)
  );
}

// Letters in order within a short stretch of one word, so "crdntl" finds "credentials" but
// letters spread over several words ("mail (copy)" for "mcp") do not count.
function compactSubsequence(term: string, text: string): boolean {
  const maxSpan = term.length * 3;
  for (let start = text.indexOf(term[0]); start !== -1; start = text.indexOf(term[0], start + 1)) {
    let position = start;
    let matched = 1;
    while (matched < term.length) {
      position = text.indexOf(term[matched], position + 1);
      if (position === -1 || position - start >= maxSpan) break;
      matched += 1;
    }
    if (matched === term.length) return true;
  }
  return false;
}

/** How well one query word matches one text; 0 means no match. */
export function termScore(term: string, text: string): number {
  const haystack = text.toLowerCase();
  if (haystack === term) return 100;
  if (haystack.startsWith(term)) return 80;
  const words = haystack.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  if (words.some((word) => word.startsWith(term))) return 60;
  if (haystack.includes(term)) return 50;
  if (term.length >= 3 && words.some((word) => compactSubsequence(term, word))) return 30;
  if (
    term.length >= 4 &&
    words.some(
      (word) =>
        withinOneEdit(term, word) ||
        (word.length > term.length && withinOneEdit(term, word.slice(0, term.length))),
    )
  ) {
    return 20;
  }
  return 0;
}

/**
 * Score for an item: every term has to match the label or one of the other fields.
 * Other fields count half, so a label match ranks first. 0 means the item is left out.
 */
export function paletteScore(
  label: string,
  others: (string | null | undefined)[],
  terms: string[],
): number {
  if (terms.length === 0) return 1;
  let total = 0;
  for (const term of terms) {
    let best = termScore(term, label);
    for (const field of others) {
      if (field) best = Math.max(best, termScore(term, field) / 2);
    }
    if (best === 0) return 0;
    total += best;
  }
  return total;
}

/** Items that match, best first; ties keep their original order. */
export function rankByPaletteScore<T>(
  items: T[],
  terms: string[],
  fields: (item: T) => { label: string; others?: (string | null | undefined)[] },
): T[] {
  if (terms.length === 0) return items;
  return items
    .map((item, index) => {
      const { label, others } = fields(item);
      return { item, index, score: paletteScore(label, others ?? [], terms) };
    })
    .filter((entry) => entry.score > 0)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((entry) => entry.item);
}
