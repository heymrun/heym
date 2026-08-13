/** Adjacent src in a lightbox gallery. Wraps; stays put for a single image. */
export function adjacentImageSrc(
  srcs: readonly string[],
  current: string | null,
  delta: number,
): string | null {
  if (!current || srcs.length === 0) {
    return current;
  }
  if (srcs.length === 1) {
    return srcs[0] ?? current;
  }
  const index = srcs.indexOf(current);
  if (index < 0) {
    return current;
  }
  const nextIndex = (index + delta + srcs.length) % srcs.length;
  return srcs[nextIndex] ?? current;
}

/** 1-based position for the counter, or null when navigation does not apply. */
export function imageGalleryPosition(
  srcs: readonly string[],
  current: string | null,
): { index: number; total: number } | null {
  if (!current || srcs.length <= 1) {
    return null;
  }
  const index = srcs.indexOf(current);
  if (index < 0) {
    return null;
  }
  return { index: index + 1, total: srcs.length };
}
