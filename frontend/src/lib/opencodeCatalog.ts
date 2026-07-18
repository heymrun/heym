/** OpenCode Go (zen) fallback model catalog + reasoning variants. */

export const OPENCODE_MODEL_FALLBACK = [
  { id: "opencode/kimi-k3", name: "Kimi K3" },
  { id: "opencode/deepseek-v4-pro", name: "DeepSeek V4 Pro" },
  { id: "opencode/qwen3.7-max", name: "Qwen3.7 Max" },
  { id: "opencode/minimax-m3", name: "MiniMax M3" },
] as const;

export const OPENCODE_DEFAULT_MODEL = "opencode/kimi-k3";

export interface OpenCodeModel {
  id: string;
  name: string;
}

export const OPENCODE_VARIANT_OPTIONS = [
  { value: "", label: "Default" },
  { value: "low", label: "Low" },
  { value: "medium", label: "Medium" },
  { value: "high", label: "High" },
] as const;

export type OpenCodeVariant = (typeof OPENCODE_VARIANT_OPTIONS)[number]["value"];
