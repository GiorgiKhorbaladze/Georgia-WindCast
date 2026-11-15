import { generationKpiView, type GenerationKpiView } from "./kpi";
import type { ApiResult, GenerationLatest } from "./types";

/** How often an open dashboard re-asks the app backend (never GSE directly). */
export const KPI_REFRESH_MS = 60_000;

export interface LiveKpiInput {
  /** Last successful answer from the app backend (or the server-rendered one). */
  last: ApiResult<GenerationLatest>;
  /** True when the most recent refresh attempt failed. */
  refreshFailed: boolean;
  /** Current browser time, ms since epoch. */
  nowMs: number;
}

export interface LiveKpiView extends GenerationKpiView {
  refreshFailed: boolean;
}

/**
 * What the national KPI may show *now* in an open tab.
 *
 * - A reading is never "fresh" (or "unverified") past its `fresh_until`, even if no refresh ran:
 *   the badge expires locally.
 * - A failed refresh keeps the last value visible but marks it stale; it is never presented as
 *   current. The next successful refresh restores the normal state.
 */
export function liveKpiView({ last, refreshFailed, nowMs }: LiveKpiInput): LiveKpiView {
  const base = generationKpiView(last);
  if (base.value === null) return { ...base, refreshFailed };
  const timely = base.freshness === "fresh" || base.freshness === "unverified";
  if (!timely) return { ...base, refreshFailed };

  const freshUntil = last.ok && last.data.fresh_until ? Date.parse(last.data.fresh_until) : NaN;
  if (Number.isFinite(freshUntil) && nowMs > freshUntil) {
    return { ...base, freshness: "stale", reason: refreshFailed ? "refresh_failed" : "expired_in_view", refreshFailed };
  }
  if (refreshFailed) {
    return { ...base, freshness: "stale", reason: "refresh_failed", refreshFailed };
  }
  return { ...base, refreshFailed };
}
