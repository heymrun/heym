import { tableLinkHref } from "@/components/Dashboards/chartTable";

/**
 * The html widget's iframe sandbox. allow-same-origin is absent, so the widget's script runs in
 * an opaque origin: no Heym cookies, storage, session or DOM. No popups, forms, top navigation,
 * modals or downloads either; links reach a new tab through `htmlWidgetLink` instead.
 */
export const HTML_WIDGET_SANDBOX = "allow-scripts";

/** The message the widget's frame posts when a link in it is clicked. */
export const HTML_WIDGET_LINK_MESSAGE = "heym:html-widget:open-link";

/**
 * Applied inside the frame on top of the sandbox: no fetch, XHR, WebSocket, beacons, forms,
 * nested frames, workers, plugins or <base>. Inline and https styles, scripts, images and
 * fonts still load.
 */
export const HTML_WIDGET_CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline' https:",
  "style-src 'unsafe-inline' https:",
  "img-src data: blob: https:",
  "font-src data: https:",
  "media-src data: blob: https:",
  "connect-src 'none'",
  "form-action 'none'",
  "frame-src 'none'",
  "worker-src 'none'",
  "object-src 'none'",
  "base-uri 'none'",
].join("; ");

const LINK_SCRIPT = `(function () {
  document.addEventListener("click", function (event) {
    var start = event.target;
    var link = start && start.closest ? start.closest("a[href], a[*|href]") : null;
    if (!link || event.button !== 0) return;
    var raw = link.getAttribute("href") || link.getAttribute("xlink:href") || "";
    if (raw.charAt(0) === "#") return;
    event.preventDefault();
    var href = raw;
    try { href = new URL(raw, document.baseURI).href; } catch (error) {}
    parent.postMessage({ type: "${HTML_WIDGET_LINK_MESSAGE}", href: href }, "*");
  }, true);
})();`;

/** The srcdoc of an html widget: Heym's CSP, link script and base styles, then the author's HTML. */
export function buildHtmlWidgetDocument(html: string, dark: boolean): string {
  const scheme = dark ? "dark" : "light";
  return [
    "<!doctype html><html><head><meta charset=\"utf-8\">",
    `<meta http-equiv="Content-Security-Policy" content="${HTML_WIDGET_CSP}">`,
    "<meta name=\"referrer\" content=\"no-referrer\">",
    "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">",
    `<style>:root{color-scheme:${scheme}}html,body{margin:0;background:transparent}`,
    "body{font-family:ui-sans-serif,system-ui,sans-serif;font-size:14px;line-height:1.5;overflow-wrap:anywhere}",
    "img,svg,video,canvas{max-width:100%}</style>",
    `<script>${LINK_SCRIPT}</script>`,
    "</head><body>",
    html,
    "</body></html>",
  ].join("");
}

/** The URL a link message from the widget's frame may open, or null when it is not a link Heym opens. */
export function htmlWidgetLink(data: unknown): string | null {
  if (typeof data !== "object" || data === null) return null;
  const message = data as { type?: unknown; href?: unknown };
  if (message.type !== HTML_WIDGET_LINK_MESSAGE || typeof message.href !== "string") return null;
  return tableLinkHref(message.href);
}
