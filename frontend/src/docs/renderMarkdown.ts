import GithubSlugger from "github-slugger";
import { Marked } from "marked";

/** Resolve GitHub-friendly relative Markdown links to application documentation routes. */
export function resolveDocLink(href: string, currentPath: string): string {
  if (!href || /^(?:https?:\/\/|#|\/docs\/)/.test(href)) return href;
  const match = /^([^?#]+)\.md(#[^]*)?$/.exec(href);
  if (!match) return href;

  const resolved = currentPath.split("/").slice(0, -1);
  for (const segment of match[1].split("/")) {
    if (segment === "..") resolved.pop();
    else if (segment && segment !== ".") resolved.push(segment);
  }
  return `/docs/${resolved.join("/")}${match[2] ?? ""}`;
}

function escapeHtml(value: string): string {
  return value.replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

/** Render article HTML with GitHub heading IDs. The caller must sanitize the result. */
export function renderDocMarkdown(raw: string, currentPath: string): string {
  const slugger = new GithubSlugger();
  const markdown = new Marked({
    breaks: true,
    gfm: true,
    renderer: {
      heading({ tokens, depth }) {
        const text = this.parser.parseInline(tokens, this.parser.textRenderer);
        const id = slugger.slug(text.replace(/<[^>]*>/g, ""));
        return `<h${depth} id="${escapeHtml(id)}">${this.parser.parseInline(tokens)}</h${depth}>\n`;
      },
      link({ href, title, text }) {
        const resolved = resolveDocLink(href ?? "", currentPath);
        const titleAttr = title ? ` title="${escapeHtml(title)}"` : "";
        const external = resolved.startsWith("/docs/") || resolved.startsWith("#")
          ? "" : ' target="_blank" rel="noopener noreferrer"';
        return `<a href="${escapeHtml(resolved)}"${titleAttr}${external}>${text}</a>`;
      },
      code({ text, lang }) {
        const langClass = lang ? ` language-${escapeHtml(lang)}` : "";
        return `<pre class="doc-code-block${langClass}"><code class="${langClass}">${escapeHtml(text)}</code></pre>`;
      },
    },
  });
  return markdown.parse(raw, { async: false });
}
