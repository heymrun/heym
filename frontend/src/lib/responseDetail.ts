/**
 * The `detail` message of a failed API request, or null when it has none.
 *
 * Reads the error the way `axios.isAxiosError` does, without importing axios, so components that
 * Heym Work also renders can show the message whichever app's client made the request. Heym's
 * and Work's clients both use axios, and Work's proxy passes Heym's FastAPI error bodies through.
 */
export function responseDetail(error: unknown): string | null {
  if (typeof error !== "object" || error === null) return null;
  if ((error as { isAxiosError?: unknown }).isAxiosError !== true) return null;
  const detail = (error as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
  return typeof detail === "string" && detail.trim() ? detail : null;
}
