import { describe, expect, it } from "vitest";

import { compass, downwindBearing, formatSpeed, screenVector } from "../wind";

describe("wind direction convention", () => {
  it("a westerly (from 270) blows toward the east (90)", () => {
    expect(downwindBearing(270)).toBe(90);
    const v = screenVector(270);
    expect(v.dx).toBeCloseTo(1); // moves right on screen
    expect(v.dy).toBeCloseTo(0);
  });

  it("a northerly (from 0/360) moves down the screen (south)", () => {
    for (const d of [0, 360]) {
      const v = screenVector(d);
      expect(v.dx).toBeCloseTo(0);
      expect(v.dy).toBeCloseTo(1);
    }
  });

  it("a south-easterly (from 135) moves up and left (toward NW)", () => {
    const v = screenVector(135);
    expect(v.dx).toBeLessThan(0);
    expect(v.dy).toBeLessThan(0);
  });

  it("compass labels", () => {
    expect(compass(0, "en")).toBe("N");
    expect(compass(292, "en")).toBe("WNW");
    expect(compass(359, "en")).toBe("N");
    expect(compass(270, "ka")).toBe("დ");
  });

  it("formats speeds and keeps missing values missing", () => {
    expect(formatSpeed(7.26)).toBe("7.3");
    expect(formatSpeed(0)).toBe("0.0");
    expect(formatSpeed(null)).toBeNull();
  });
});

describe("arrowRotation (map markers render only numbers)", () => {
  it("rotates finite directions and refuses anything else", async () => {
    const { arrowRotation } = await import("@/components/WindMap");
    expect(arrowRotation(270)).toBe(90);
    for (const bad of [null, undefined, Number.NaN, Number.POSITIVE_INFINITY, "90", '"><img src=x onerror=alert(1)>']) {
      expect(arrowRotation(bad)).toBeNull();
    }
  });
});
