import { describe, expect, it } from "vitest";

import { formatMw, formatTbilisi, formatTbilisiMinute, formatTbilisiShort, tbilisiInputValue } from "../format";
import { resolveLocale } from "../i18n";

describe("formatTbilisi", () => {
  it("converts UTC to Asia/Tbilisi (UTC+4) across a date boundary", () => {
    // 21:30 UTC on 14 Nov is 01:30 on 15 Nov in Tbilisi.
    expect(formatTbilisi("2026-11-14T21:30:00Z", "en")).toBe("15.11.2026 01:30:00");
    expect(formatTbilisi("2026-11-14T21:30:00Z", "ka")).toBe("15.11.2026 01:30:00");
    expect(formatTbilisiMinute("2026-12-31T20:05:00Z")).toBe("01.01.2027 00:05");
    expect(formatTbilisiShort("2026-11-14T21:30:00Z", true)).toBe("15.11 01:30");
    expect(tbilisiInputValue("2026-11-14T21:30:00Z")).toBe("2026-11-15T01:30");
  });

  it("returns null for missing or invalid timestamps", () => {
    expect(formatTbilisi(null, "ka")).toBeNull();
    expect(formatTbilisi("not-a-date", "ka")).toBeNull();
  });
});

describe("formatMw", () => {
  it("formats with one decimal and keeps zero", () => {
    expect(formatMw(78.444)).toBe("78.4");
    expect(formatMw(0)).toBe("0.0");
    expect(formatMw(null)).toBeNull();
    expect(formatMw(Number.POSITIVE_INFINITY)).toBeNull();
  });
});

describe("resolveLocale", () => {
  it("defaults to Georgian", () => {
    expect(resolveLocale(undefined)).toBe("ka");
    expect(resolveLocale("fr")).toBe("ka");
    expect(resolveLocale("en")).toBe("en");
  });
});
