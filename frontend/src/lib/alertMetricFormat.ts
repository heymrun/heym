import type { AlertConfig, AlertType } from "@/types/alerts";

export type CostMetric = "usd" | "total_tokens";

/**
 * Formats an observed or threshold value for display.
 *
 * Raw metric values are floats straight out of the evaluator, so an unformatted
 * duration reads "6186.190128326416". The unit comes from the alert type, and
 * durations use the same ms/s split as the Analytics tab so the two never
 * disagree about the same number.
 *
 * `costMetric` only matters for token_cost, where the same number is either
 * dollars or tokens. Callers read it from the alert's config or, for a past
 * firing, from the event context the handler recorded.
 */
export function formatAlertValue(
  value: number | null,
  alertType: AlertType,
  costMetric?: CostMetric,
): string {
  if (value === null || Number.isNaN(value)) return "-";

  if (alertType === "workflow_duration") {
    return value < 1000 ? `${Math.round(value)}ms` : `${(value / 1000).toFixed(2)}s`;
  }

  if (alertType === "token_cost") {
    if (costMetric === "total_tokens") {
      return `${new Intl.NumberFormat("en-US").format(Math.round(value))} tokens`;
    }
    if (costMetric === "usd") {
      // Sub-cent spend still has to read as money rather than rounding to $0.00.
      return value > 0 && value < 0.01 ? `$${value.toFixed(4)}` : `$${value.toFixed(2)}`;
    }
    // Unknown metric: a bare number beats guessing a unit and labelling tokens
    // as dollars.
    return new Intl.NumberFormat("en-US").format(Math.round(value * 100) / 100);
  }

  return new Intl.NumberFormat("en-US").format(Math.round(value));
}

/** The cost metric an alert is configured for, when it has one. */
export function costMetricFromConfig(config: AlertConfig | null | undefined): CostMetric | undefined {
  if (config && "metric" in config) return config.metric;
  return undefined;
}

/** The cost metric a past firing recorded, when it has one. */
export function costMetricFromContext(
  context: Record<string, unknown> | null | undefined,
): CostMetric | undefined {
  const metric = context?.metric;
  return metric === "usd" || metric === "total_tokens" ? metric : undefined;
}
