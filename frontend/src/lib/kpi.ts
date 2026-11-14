import { formatMw } from "./format";
import type { ApiResult, Freshness, GenerationLatest } from "./types";

export interface GenerationKpiView {
  /** Formatted MW string, or null when no value may be shown. */
  value: string | null;
  freshness: Freshness;
  observedAt: string | null;
  retrievedAt: string | null;
  reason: string | null;
  apiReachable: boolean;
}

/**
 * Decide what the national KPI may display. A value is shown only if the backend returned a
 * finite number; stale and unverified readings keep their value but carry an explicit state.
 */
export function generationKpiView(result: ApiResult<GenerationLatest>): GenerationKpiView {
  if (!result.ok) {
    return {
      value: null,
      freshness: "unavailable",
      observedAt: null,
      retrievedAt: null,
      reason: result.error,
      apiReachable: false,
    };
  }
  const d = result.data;
  const value = d.freshness === "unavailable" ? null : formatMw(d.value_mw);
  return {
    value,
    // A non-unavailable state without a usable number is still unavailable to the user.
    freshness: value === null ? "unavailable" : d.freshness,
    observedAt: d.source_observed_at,
    retrievedAt: d.retrieved_at,
    reason: d.reason,
    apiReachable: true,
  };
}
