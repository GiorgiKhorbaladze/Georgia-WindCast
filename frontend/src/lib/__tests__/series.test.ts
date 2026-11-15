import { describe, expect, it } from "vitest";

import { breakOnStep, labelFlags, withGapBreaks } from "../series";

const pts = [
  { t: "2026-11-14T20:00:00Z", v: 1 },
  { t: "2026-11-14T20:03:00Z", v: 2 },
  { t: "2026-11-14T20:15:00Z", v: 3 },
];

describe("withGapBreaks", () => {
  it("inserts a null inside each gap, keeps real points untouched", () => {
    const data = withGapBreaks(pts, (p) => p.t, (p) => p.v, [
      { start: "2026-11-14T20:03:00Z", end: "2026-11-14T20:15:00Z" },
    ]);
    expect(data.map((d) => d[1])).toEqual([1, 2, null, 3]);
    expect(data[2][0]).toBe(Date.parse("2026-11-14T20:09:00Z"));
  });

  it("does not invent values when there are no gaps", () => {
    expect(withGapBreaks(pts, (p) => p.t, (p) => p.v, []).map((d) => d[1])).toEqual([1, 2, 3]);
  });
});

describe("breakOnStep", () => {
  it("breaks where steps exceed the cadence", () => {
    const d = breakOnStep([[0, 1], [3600e3, 2], [3 * 3600e3, 3]], 3600e3 * 1.5);
    expect(d.map((x) => x[1])).toEqual([1, 2, null, 3]);
  });
});

describe("labelFlags", () => {
  const H = 3600e3;
  const span = 24 * H;

  it("labels a wide interval", () => {
    expect(labelFlags([{ start: 0, end: 3 * H }], span)).toEqual([true]);
  });

  it("does not label narrow intervals (they stay shaded)", () => {
    expect(labelFlags([{ start: 0, end: 0.5 * H }], span)).toEqual([false]);
  });

  it("never labels two intervals closer than the spacing", () => {
    const flags = labelFlags(
      [
        { start: 0, end: 2 * H },
        { start: 2.5 * H, end: 5 * H },
        { start: 10 * H, end: 12 * H },
      ],
      span,
    );
    expect(flags).toEqual([true, false, true]);
  });
});
