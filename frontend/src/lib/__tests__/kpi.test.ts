import { describe, expect, it } from "vitest";

import { generationKpiView } from "../kpi";
import type { GenerationLatest } from "../types";

const base: GenerationLatest = {
  scope: "national_aggregate",
  unit: "MW",
  freshness: "fresh",
  value_mw: 12.34,
  source_observed_at: "2026-11-14T10:00:00Z",
  retrieved_at: "2026-11-14T10:00:30Z",
  reason: null,
  quality: "ACT",
  quality_flagged: false,
  period_seconds: 180,
  source: { name: "GSE", url: "https://www.gse.com.ge" },
};

describe("generationKpiView", () => {
  it("shows a fresh value", () => {
    const v = generationKpiView({ ok: true, data: base });
    expect(v).toMatchObject({ value: "12.3", freshness: "fresh", apiReachable: true });
  });

  it("renders zero as a real reading, not as unavailable", () => {
    const v = generationKpiView({ ok: true, data: { ...base, value_mw: 0 } });
    expect(v.value).toBe("0.0");
    expect(v.freshness).toBe("fresh");
  });

  it("keeps the last value but marks it stale", () => {
    const v = generationKpiView({ ok: true, data: { ...base, freshness: "stale", reason: "source_timeout" } });
    expect(v).toMatchObject({ value: "12.3", freshness: "stale", reason: "source_timeout" });
  });

  it("never shows a number when the backend says unavailable", () => {
    const v = generationKpiView({ ok: true, data: { ...base, freshness: "unavailable", value_mw: 99 } });
    expect(v.value).toBeNull();
    expect(v.freshness).toBe("unavailable");
  });

  it("surfaces a non-ACT quality flag with the value", () => {
    const v = generationKpiView({ ok: true, data: { ...base, quality: "NRE", quality_flagged: true } });
    expect(v).toMatchObject({ value: "12.3", quality: "NRE", qualityFlagged: true });
  });

  it("drops quality when no value may be shown", () => {
    const v = generationKpiView({ ok: true, data: { ...base, freshness: "unavailable", quality_flagged: true } });
    expect(v).toMatchObject({ value: null, quality: null, qualityFlagged: false });
  });

  it("treats a missing or non-finite value as unavailable", () => {
    expect(generationKpiView({ ok: true, data: { ...base, value_mw: null } }).freshness).toBe("unavailable");
    expect(generationKpiView({ ok: true, data: { ...base, value_mw: Number.NaN } }).value).toBeNull();
  });

  it("reports an unreachable API without inventing data", () => {
    const v = generationKpiView({ ok: false, error: "unreachable" });
    expect(v).toEqual({
      value: null,
      freshness: "unavailable",
      observedAt: null,
      retrievedAt: null,
      reason: "unreachable",
      quality: null,
      qualityFlagged: false,
      apiReachable: false,
    });
  });
});
