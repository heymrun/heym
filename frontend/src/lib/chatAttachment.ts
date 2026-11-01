/** Marker the server appends to a user message that carries a Drive file attachment. */
export const DRIVE_ATTACHMENT_MARKER = "\n\n[ATTACHED DRIVE FILE: ";

export interface SplitDriveAttachment {
  text: string;
  name: string | null;
}

/** Split a stored user message into its visible text and the attached Drive file's name. */
export function splitDriveAttachment(content: string): SplitDriveAttachment {
  const start = content.indexOf(DRIVE_ATTACHMENT_MARKER);
  if (start === -1) return { text: content, name: null };
  const header = content.slice(start + DRIVE_ATTACHMENT_MARKER.length).split("\n", 1)[0] ?? "";
  const name = header.split(" · ", 1)[0]?.replace(/\]$/, "").trim() || null;
  return { text: content.slice(0, start), name };
}
