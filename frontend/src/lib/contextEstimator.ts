export function estimateTokens(payload: unknown): number {
  if (payload == null) return 0
  return Math.floor(JSON.stringify(payload).length / 4)
}
