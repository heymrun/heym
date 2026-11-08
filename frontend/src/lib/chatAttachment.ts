/**
 * Markers the server puts before each attachment block it appends to a user message
 * (`_build_user_message`), one block per attached file, in the order they were attached.
 */
export const ATTACHMENT_MARKERS = {
  drive: "\n\n[ATTACHED DRIVE FILE: ",
  file: "\n\n[ATTACHED FILE: ",
  image: "\n\n[ATTACHED IMAGE: ",
  zip: "\n\n[ATTACHED ZIP: ",
} as const;

/** Marker the server appends to a user message that carries a Drive file attachment. */
export const DRIVE_ATTACHMENT_MARKER = ATTACHMENT_MARKERS.drive;

export type AttachmentBlockKind = keyof typeof ATTACHMENT_MARKERS;

export interface AttachmentBlock {
  kind: AttachmentBlockKind;
  name: string;
  /** What follows the block's header line: an inline file's text, a zip's summary. */
  body: string;
}

export interface SplitAttachments {
  text: string;
  blocks: AttachmentBlock[];
}

function blockStarts(content: string): Array<{ at: number; kind: AttachmentBlockKind }> {
  const starts: Array<{ at: number; kind: AttachmentBlockKind }> = [];
  for (const kind of Object.keys(ATTACHMENT_MARKERS) as AttachmentBlockKind[]) {
    const marker = ATTACHMENT_MARKERS[kind];
    let at = content.indexOf(marker);
    while (at !== -1) {
      starts.push({ at, kind });
      at = content.indexOf(marker, at + 1);
    }
  }
  return starts.sort((a, b) => a.at - b.at);
}

function blockName(kind: AttachmentBlockKind, header: string): string {
  const closed = header.endsWith("]") ? header.slice(0, -1) : header;
  const name = kind === "drive" ? closed.split(" · ", 1)[0] : closed;
  return (name ?? "").trim();
}

/** Split a stored user message into its visible text and the files the server attached to it. */
export function splitAttachmentBlocks(content: string): SplitAttachments {
  const starts = blockStarts(content);
  if (starts.length === 0) return { text: content, blocks: [] };
  const blocks: AttachmentBlock[] = [];
  starts.forEach((start, index) => {
    const end = index + 1 < starts.length ? starts[index + 1].at : content.length;
    const raw = content.slice(start.at + ATTACHMENT_MARKERS[start.kind].length, end);
    const lineEnd = raw.indexOf("\n");
    const header = lineEnd === -1 ? raw : raw.slice(0, lineEnd);
    const name = blockName(start.kind, header);
    if (name) {
      blocks.push({ kind: start.kind, name, body: lineEnd === -1 ? "" : raw.slice(lineEnd + 1) });
    }
  });
  return { text: content.slice(0, starts[0].at), blocks };
}

/** The names of the files a stored user message carries, in order. */
export function attachmentNames(content: string): string[] {
  return splitAttachmentBlocks(content).blocks.map((block) => block.name);
}
