import DOMPurify from "dompurify";
import { marked } from "marked";

const ALLOWED_TAGS = [
  "p", "br", "strong", "em", "u", "s", "code", "pre", "blockquote",
  "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "a", "hr",
  "table", "thead", "tbody", "tr", "th", "td", "img", "video", "source",
];

const ALLOWED_ATTR = [
  "href", "target", "rel", "src", "alt", "controls", "playsinline",
  "muted", "loop", "preload", "type",
];

const EXPLICIT_ORDERED_LINE_RE = /^(\s*)(\d+)\.(\s)/;

/**
 * GFM treats `N. ` lines as ordered lists. HTML `<ol>` only increments from
 * `start`, so descending or custom-start lists (e.g. 9, 8, 7) render as 9, 10, 11.
 * Escaping the dot keeps the author's numbers in the rendered text.
 * See Chart Output docs: numbered lists in text widgets.
 */
export function preserveExplicitOrderedListNumbers(markdown: string): string {
  return markdown
    .split("\n")
    .map((line) =>
      EXPLICIT_ORDERED_LINE_RE.test(line)
        ? line.replace(EXPLICIT_ORDERED_LINE_RE, "$1$2\\.$3")
        : line,
    )
    .join("\n");
}

/** Render dashboard chart text markdown with explicit list numbers preserved. */
export function renderChartMarkdown(content: string): string {
  if (!content) return "";
  const prepared = preserveExplicitOrderedListNumbers(content);
  const html = marked(prepared, { breaks: true, gfm: true }) as string;
  return DOMPurify.sanitize(html);
}

/**
 * Heuristic: true when text contains common Markdown constructs.
 * Used to decide whether a Markdown view toggle should appear in the UI.
 */
export function looksLikeMarkdown(content: string): boolean {
  const text = content.trim();
  if (!text) return false;

  return (
    /^#{1,6}\s+\S/m.test(text) ||
    /```[\s\S]*?```/.test(text) ||
    /~~~[\s\S]*?~~~/.test(text) ||
    /\*\*[^*\n]+\*\*/.test(text) ||
    /__[^_\n]+__/.test(text) ||
    /^>\s+\S/m.test(text) ||
    /^\s{0,3}[-*+]\s+\S/m.test(text) ||
    /^\s{0,3}\d+\.\s+\S/m.test(text) ||
    /\[[^\]]+\]\([^)]+\)/.test(text) ||
    /^\s*\|.+\|\s*$/m.test(text)
  );
}

/** Render trusted-but-sanitized markdown to an HTML string for v-html. */
export function renderMarkdown(content: string): string {
  if (!content) return "";
  const html = marked(content, { breaks: true, gfm: true }) as string;
  return DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR });
}

export function markdownToPlainText(content: string): string {
  if (!content) return "";
  const container = document.createElement("div");
  container.innerHTML = renderMarkdown(content);
  return (container.textContent || container.innerText || "").trim();
}
