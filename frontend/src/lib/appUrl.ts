/**
 * Join a window origin with an in-app path. Prevents `origin + undefined` → "...comundefined".
 */
export function joinOriginAndPath(origin: string, path: string | undefined | null): string {
  const normalizedOrigin = origin.replace(/\/$/, "");
  const rawPath = path == null || path === "" ? "/" : path;
  const normalizedPath = rawPath.startsWith("/") ? rawPath : `/${rawPath}`;
  return `${normalizedOrigin}${normalizedPath}`;
}
