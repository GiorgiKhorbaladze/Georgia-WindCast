import { describe, expect, it } from "vitest";

import { buildGenerationOption } from "@/components/GenerationChart";
import type { GenerationHistory } from "../types";

const H: GenerationHistory = {
  start: "2026-11-14T00:00:00Z",
  end: "2026-11-15T00:00:00Z",
  scope: "national_aggregate",
  unit: "MW",
  cadence_seconds: 180,
  collection_started_at: "2026-11-14T06:00:00Z",
  points: [
    { t: "2026-11-14T06:00:00Z", value_mw: 80, quality: "ACT" },
    { t: "2026-11-14T06:03:00Z", value_mw: 81, quality: "ACT" },
    { t: "2026-11-14T06:30:00Z", value_mw: 79, quality: "ACT" },
  ],
  gaps: [
    { start: "2026-11-14T06:03:00Z", end: "2026-11-14T06:30:00Z" },
    { start: "2026-11-14T06:30:00Z", end: "2026-11-15T00:00:00Z" },
  ],
  source: { name: "GSE", url: "https://www.gse.com.ge" },
};

describe("buildGenerationOption shaded areas", () => {
  it("draws every gap and the pre-collection span, with no in-chart text that could overlap", () => {
    const option = buildGenerationOption(H, "ka") as unknown as {
      series: { markArea: { label: { show: boolean }; data: { name?: string }[][] } }[];
    };
    const area = option.series[0].markArea;
    expect(area.data).toHaveLength(3); // 2 gaps + before collection
    expect(area.label.show).toBe(false);
    for (const [from, to] of area.data) {
      expect(from.name).toBeUndefined();
      expect(to.name).toBeUndefined();
    }
  });
});
