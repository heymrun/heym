import { describe, expect, it } from "vitest";

import { convertMarkdownTables } from "@/lib/markdownTables";

const TABLE = [
  "| Setting | Value | Meaning |",
  "|------|-------|--------|",
  "| **User Message** | `$input.text` | The text field |",
  "| Model | (empty) | Not chosen yet |",
].join("\n");

describe("convertMarkdownTables", () => {
  it("renders a header and its rows", () => {
    const html = convertMarkdownTables(TABLE);

    expect(html.match(/<th>/g)).toHaveLength(3);
    expect(html.match(/<tr>/g)).toHaveLength(3);
    expect(html).toContain("<td>**User Message**</td>");
    expect(html).toContain("<td>Not chosen yet</td>");
    expect(html).not.toContain("|");
  });

  it("keeps text around a table without extra newlines", () => {
    const html = convertMarkdownTables(`Before\n${TABLE}\nAfter`);

    expect(html.startsWith("Before<div class=\"md-table-wrap\">")).toBe(true);
    expect(html.endsWith("</div>After")).toBe(true);
    expect(html).not.toContain("\n");
  });

  it("reads column alignment from the separator row", () => {
    const html = convertMarkdownTables("| a | b | c |\n|:--|:-:|--:|\n| 1 | 2 | 3 |");

    expect(html).toContain('<th style="text-align:left">a</th>');
    expect(html).toContain('<td style="text-align:center">2</td>');
    expect(html).toContain('<td style="text-align:right">3</td>');
  });

  it("accepts tables without outer pipes and pads short rows", () => {
    const html = convertMarkdownTables("a | b\n--- | ---\n1 |");

    expect(html).toContain("<th>a</th><th>b</th>");
    expect(html).toContain("<td>1</td><td></td>");
  });

  it("keeps an escaped pipe inside its cell", () => {
    const html = convertMarkdownTables("| a | b |\n|---|---|\n| x \\| y | z |");

    expect(html).toContain("<td>x | y</td><td>z</td>");
  });

  it("leaves a partly streamed table as text until the separator row arrives", () => {
    const partial = "| Setting | Value |";

    expect(convertMarkdownTables(partial)).toBe(partial);
    expect(convertMarkdownTables(`${partial}\n|---`)).toBe(`${partial}\n|---`);
    expect(convertMarkdownTables(`${partial}\n|---|---|`)).toContain("<table");
  });

  it("does not touch pipes that are not a table", () => {
    const text = "Use a | b to pipe\nno table here\n- item";

    expect(convertMarkdownTables(text)).toBe(text);
  });

  it("converts two tables in one message and drops the blank lines around them", () => {
    const html = convertMarkdownTables(`${TABLE}\n\n\nBetween\n\n${TABLE}\n\nEnd`);

    expect(html.match(/<table/g)).toHaveLength(2);
    expect(html).toContain("</div>Between<div");
    expect(html.endsWith("</div>End")).toBe(true);
    expect(html).not.toContain("\n");
  });
});
