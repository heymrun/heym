import axios from "axios";

/** The server's `detail` message for a refused request, or the fallback when it has none. */
export function apiErrorDetail(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err) && typeof err.response?.data?.detail === "string") {
    return err.response.data.detail;
  }
  return fallback;
}
