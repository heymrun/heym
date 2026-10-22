type Align = "left" | "center" | "right" | null;

type Segment = { table: boolean; value: string };

const SEPARATOR_CELL = /^:?-+:?$/;

function isBlankText(segment: Segment): boolean {
  return !segment.table && segment.value.trim() === "";
}

function splitRow(line: string): string[] {
  const trimmed = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return trimmed.split(/(?<!\\)\|/).map((cell) => cell.replace(/\\\|/g, "|").trim());
}

function readAlignments(line: string): Align[] | null {
  if (!line.includes("|") && !SEPARATOR_CELL.test(line.trim())) return null;
  const cells = splitRow(line);
  if (!cells.every((cell) => SEPARATOR_CELL.test(cell))) return null;
  return cells.map((cell) => {
    if (cell.startsWith(":") && cell.endsWith(":")) return "center";
    if (cell.endsWith(":")) return "right";
    if (cell.startsWith(":")) return "left";
    return null;
  });
}

function cellTag(tag: "th" | "td", content: string, align: Align): string {
  const style = align ? ` style="text-align:${align}"` : "";
  return `<${tag}${style}>${content}</${tag}>`;
}

function renderTable(header: string[], aligns: Align[], rows: string[][]): string {
  const columns = header.length;
  const head = header.map((cell, i) => cellTag("th", cell, aligns[i] ?? null)).join("");
  const body = rows
    .map((row) => {
      const cells = Array.from({ length: columns }, (_, i) => cellTag("td", row[i] ?? "", aligns[i] ?? null));
      return `<tr>${cells.join("")}</tr>`;
    })
    .join("");
  return `<div class="md-table-wrap"><table class="md-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

/**
 * Turns GitHub-style pipe tables in `text` into HTML tables. `text` must already be HTML-escaped,
 * because cell content is passed through as is. A table is a header row followed by a separator
 * row (`|---|---|`) with the same number of cells, then the rows that still contain a pipe.
 * The converted table sits on its own line, with no newlines or blank lines around it.
 */
export function convertMarkdownTables(text: string): string {
  if (!text.includes("|")) return text;
  const lines = text.split("\n");
  const segments: Segment[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const aligns = line.includes("|") && i + 1 < lines.length ? readAlignments(lines[i + 1]) : null;
    const header = aligns ? splitRow(line) : [];
    if (!aligns || header.length !== aligns.length) {
      segments.push({ table: false, value: line });
      i += 1;
      continue;
    }

    const rows: string[][] = [];
    i += 2;
    while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
      rows.push(splitRow(lines[i]));
      i += 1;
    }
    // The table has its own margin, so blank lines around it would only add <br>s.
    while (segments.length > 0 && isBlankText(segments[segments.length - 1])) segments.pop();
    segments.push({ table: true, value: renderTable(header, aligns, rows) });
    while (i < lines.length && lines[i].trim() === "") i += 1;
  }

  return segments.reduce((result, segment, index) => {
    const joinsTable = index === 0 || segment.table || segments[index - 1].table;
    return result + (joinsTable ? "" : "\n") + segment.value;
  }, "");
}
