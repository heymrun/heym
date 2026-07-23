import { describe, expect, it } from "vitest";

import { looksLikeMarkdown } from "@/lib/markdown";

describe("looksLikeMarkdown", () => {
  it("returns false for empty or plain prose", () => {
    expect(looksLikeMarkdown("")).toBe(false);
    expect(looksLikeMarkdown("Hello world")).toBe(false);
    expect(looksLikeMarkdown("Just a short sentence without markup.")).toBe(false);
  });

  it("detects common markdown constructs", () => {
    expect(looksLikeMarkdown("# Title\n\nSome body")).toBe(true);
    expect(looksLikeMarkdown("Use **bold** text")).toBe(true);
    expect(looksLikeMarkdown("```js\nconsole.log(1)\n```")).toBe(true);
    expect(looksLikeMarkdown("- item one\n- item two")).toBe(true);
    expect(looksLikeMarkdown("1. first\n2. second")).toBe(true);
    expect(looksLikeMarkdown("> quoted")).toBe(true);
    expect(looksLikeMarkdown("[Google](https://google.com)")).toBe(true);
    expect(looksLikeMarkdown("| A | B |\n| --- | --- |\n| 1 | 2 |")).toBe(true);
  });

  it("detects markdown inside LLM sample responses", () => {
    const sample = [
      "Elbette, işte Markdown'ın temel özelliklerini gösteren bir örnek metin:",
      "",
      "```markdown",
      "# Başlık 1 (H1)",
      "",
      "Bu bir paragraf. Metin içinde **kalın**, *italik* yazılar.",
      "```",
    ].join("\n");
    expect(looksLikeMarkdown(sample)).toBe(true);
  });
});
