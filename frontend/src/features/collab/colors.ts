/** One color per person, the same on every screen: avatar ring, cursor and follow frame. */
export const COLLAB_COLORS = [
  "#F97316",
  "#22C55E",
  "#3B82F6",
  "#EC4899",
  "#A855F7",
  "#14B8A6",
  "#EAB308",
  "#EF4444",
  "#6366F1",
  "#84CC16",
  "#06B6D4",
  "#F43F5E",
] as const;

function fnv1a(value: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

export function collabColor(userId: string): string {
  return COLLAB_COLORS[fnv1a(userId) % COLLAB_COLORS.length];
}

function channel(value: number): number {
  const linear = value / 255;
  return linear <= 0.03928 ? linear / 12.92 : ((linear + 0.055) / 1.055) ** 2.4;
}

/** Text color that stays readable on a `#RRGGBB` label: dark on light colors, white otherwise. */
export function collabTextColor(background: string): string {
  const hex = background.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((start) => channel(parseInt(hex.slice(start, start + 2), 16)));
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b;
  return luminance > 0.4 ? "#111827" : "#FFFFFF";
}
