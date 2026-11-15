import { describe, expect, it } from "vitest";

import { liveKpiView } from "../liveKpi";
import type { GenerationLatest } from "../types";

const T0 = Date.parse("2026-11-15T00:00:00Z");
const reading = (over: Partial<GenerationLatest> = {}): GenerationLatest => ({
  scope: "national_aggregate",
  unit: "MW",
  freshness: "fresh",
  value_mw: 74.5,
  source_observed_at: "2026-11-14T23:58:00Z",
  retrieved_at: "2026-11-14T23:59:20Z",
  reason: null,
  quality: "ACT",
  quality_flagged: false,
  period_seconds: 180,
  fresh_until: "2026-11-15T00:08:00Z",
  checked_at: "2026-11-15T00:00:00Z",
  source: { name: "GSE", url: "https://www.gse.com.ge" },
  ...over,
});

describe("liveKpiView", () => {
  it("is fresh before fresh_until", () => {
    const v = liveKpiView({ last: { ok: true, data: reading() }, refreshFailed: false, nowMs: T0 + 60_000 });
    expect(v).toMatchObject({ value: "74.5", freshness: "fresh", refreshFailed: false });
  });

  it("expires locally after fresh_until even without any refresh", () => {
    const v = liveKpiView({ last: { ok: true, data: reading() }, refreshFailed: false, nowMs: T0 + 9 * 60_000 });
    expect(v).toMatchObject({ value: "74.5", freshness: "stale", reason: "expired_in_view" });
  });

  it("marks the kept value stale when a refresh fails", () => {
    const v = liveKpiView({ last: { ok: true, data: reading() }, refreshFailed: true, nowMs: T0 + 60_000 });
    expect(v).toMatchObject({ value: "74.5", freshness: "stale", reason: "refresh_failed", refreshFailed: true });
  });

  it("unverified quality also expires and never becomes fresh", () => {
    const data = reading({ freshness: "unverified", quality: "NRE", quality_flagged: true, reason: "quality_not_actual" });
    expect(liveKpiView({ last: { ok: true, data }, refreshFailed: false, nowMs: T0 }).freshness).toBe("unverified");
    expect(liveKpiView({ last: { ok: true, data }, refreshFailed: false, nowMs: T0 + 10 * 60_000 }).freshness).toBe("stale");
  });

  it("keeps an already stale reading stale and an unavailable one unavailable", () => {
    const stale = reading({ freshness: "stale", reason: "source_not_updated" });
    expect(liveKpiView({ last: { ok: true, data: stale }, refreshFailed: false, nowMs: T0 }).reason).toBe("source_not_updated");
    const none = reading({ freshness: "unavailable", value_mw: null });
    expect(liveKpiView({ last: { ok: true, data: none }, refreshFailed: true, nowMs: T0 }).value).toBeNull();
  });

  it("zero is a real value and follows the same expiry", () => {
    const zero = reading({ value_mw: 0 });
    expect(liveKpiView({ last: { ok: true, data: zero }, refreshFailed: false, nowMs: T0 }).value).toBe("0.0");
  });
});
