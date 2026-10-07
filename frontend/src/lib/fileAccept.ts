/**
 * File checks a drop zone runs before uploading, mirroring the server's file intake:
 * `allowedTypes` entries are MIME globs ("image/*") or extensions (".csv"), and an
 * empty list accepts any file. The server checks again; this only spares a round trip.
 */
function globMatches(glob: string, value: string): boolean {
  const source = glob.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".");
  return new RegExp(`^${source}$`).test(value);
}

export function isFileTypeAllowed(
  file: { name: string; type: string },
  allowedTypes: string[],
): boolean {
  if (allowedTypes.length === 0) return true;
  const name = file.name.toLowerCase();
  const mime = (file.type || "").toLowerCase();
  return allowedTypes.some((entry) => {
    const allowed = entry.trim().toLowerCase();
    if (allowed.startsWith(".")) return name.endsWith(allowed);
    return globMatches(allowed, mime);
  });
}

/** Why a file cannot be dropped, or null when it can. */
export function fileRejection(
  file: { name: string; type: string; size: number },
  allowedTypes: string[],
  maxSizeMb: number,
): string | null {
  if (!isFileTypeAllowed(file, allowedTypes)) {
    return `This workflow takes ${allowedTypes.join(", ")} files.`;
  }
  if (file.size > maxSizeMb * 1024 * 1024) {
    return `The file is larger than ${maxSizeMb} MB.`;
  }
  return null;
}

/** The `accept` attribute for a file picker with these allowed types. */
export function acceptAttribute(allowedTypes: string[]): string | undefined {
  return allowedTypes.length > 0 ? allowedTypes.join(",") : undefined;
}
