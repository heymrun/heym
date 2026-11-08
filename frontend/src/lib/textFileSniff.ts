const SNIFF_BYTES = 64 * 1024;

/**
 * Whether a file is plain text whatever its name: its first 64 KB hold no NUL byte and decode
 * as UTF-8. Lets a file such as `notes` or `burak.akgun` attach like a `.txt`.
 */
export async function readsAsUtf8Text(file: Blob): Promise<boolean> {
  const head = new Uint8Array(await file.slice(0, SNIFF_BYTES).arrayBuffer());
  if (head.includes(0)) return false;
  try {
    // A character cut at the sniff limit is not an error; the rest of the file holds it.
    new TextDecoder("utf-8", { fatal: true }).decode(head, { stream: file.size > SNIFF_BYTES });
    return true;
  } catch {
    return false;
  }
}
