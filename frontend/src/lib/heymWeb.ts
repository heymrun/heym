const FALLBACK = "https://heym.run";

/**
 * heym.run, or the site `VITE_HEYM_WEB_URL` points at. A production build never links to a
 * localhost site, so a leftover development value falls back to heym.run.
 */
export function heymWebBase(): string {
  const env = import.meta.env as Partial<ImportMetaEnv> | undefined;
  const raw = env?.VITE_HEYM_WEB_URL?.trim() ?? "";
  let base = raw || FALLBACK;
  if (env?.PROD && raw) {
    try {
      const { hostname } = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`);
      if (hostname === "localhost" || hostname === "127.0.0.1") base = FALLBACK;
    } catch {
      base = FALLBACK;
    }
  }
  return base.replace(/\/$/, "");
}

/** A heym.run address: a path such as "/enterprise" joins the base, an absolute URL stays. */
export function heymWebUrl(pathOrUrl = ""): string {
  if (/^https?:\/\//i.test(pathOrUrl)) return pathOrUrl;
  return `${heymWebBase()}${pathOrUrl}`;
}
