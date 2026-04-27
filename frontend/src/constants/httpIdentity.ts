/** Browsers block overriding User-Agent; use this header for API identification. */
export const HEYM_CLIENT_AGENT = "heym.run";

export const heymClientHeaders: Record<string, string> = {
  "X-Heym-Client": HEYM_CLIENT_AGENT,
};
