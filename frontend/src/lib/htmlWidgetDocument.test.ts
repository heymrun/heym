import { describe, expect, it } from "vitest";

import {
  buildHtmlWidgetDocument,
  HTML_WIDGET_CSP,
  HTML_WIDGET_LINK_MESSAGE,
  HTML_WIDGET_SANDBOX,
  htmlWidgetLink,
} from "@/lib/htmlWidgetDocument";

function directive(name: string): string | undefined {
  return HTML_WIDGET_CSP.split("; ").find((part) => part.startsWith(`${name} `));
}

describe("html widget sandbox", () => {
  it("runs scripts only, never on Heym's origin", () => {
    expect(HTML_WIDGET_SANDBOX.split(" ")).toEqual(["allow-scripts"]);
  });

  it("blocks requests, forms, frames and <base> inside the frame", () => {
    expect(directive("default-src")).toBe("default-src 'none'");
    expect(directive("connect-src")).toBe("connect-src 'none'");
    expect(directive("form-action")).toBe("form-action 'none'");
    expect(directive("frame-src")).toBe("frame-src 'none'");
    expect(directive("worker-src")).toBe("worker-src 'none'");
    expect(directive("base-uri")).toBe("base-uri 'none'");
  });
});

describe("buildHtmlWidgetDocument", () => {
  const author = "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src *\"><p>Hi</p>";

  it("puts Heym's policy in the head, before anything the author wrote", () => {
    const doc = buildHtmlWidgetDocument(author, false);
    const policy = doc.indexOf(`content="${HTML_WIDGET_CSP}"`);
    expect(policy).toBeGreaterThan(-1);
    expect(policy).toBeLessThan(doc.indexOf("</head>"));
    expect(doc.indexOf("</head>")).toBeLessThan(doc.indexOf(author));
    expect(doc).toContain('<meta name="referrer" content="no-referrer">');
  });

  it("follows the dashboard's theme", () => {
    expect(buildHtmlWidgetDocument("", true)).toContain("color-scheme:dark");
    expect(buildHtmlWidgetDocument("", false)).toContain("color-scheme:light");
  });
});

describe("htmlWidgetLink", () => {
  const link = (href: unknown): string | null => htmlWidgetLink({ type: HTML_WIDGET_LINK_MESSAGE, href });

  it("opens http(s) links and paths inside Heym", () => {
    expect(link("https://example.com/a?b=1")).toBe("https://example.com/a?b=1");
    expect(link("http://example.com")).toBe("http://example.com/");
    expect(link("/dashboards")).toBe("/dashboards");
  });

  it("refuses script, data and protocol-relative links", () => {
    expect(link("javascript:alert(1)")).toBeNull();
    expect(link("data:text/html,<script>1</script>")).toBeNull();
    expect(link("//evil.example")).toBeNull();
    expect(link(42)).toBeNull();
  });

  it("ignores messages that are not a link request", () => {
    expect(htmlWidgetLink(null)).toBeNull();
    expect(htmlWidgetLink("https://example.com")).toBeNull();
    expect(htmlWidgetLink({ type: "other", href: "https://example.com" })).toBeNull();
  });
});
