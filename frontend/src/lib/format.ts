import type { Locale } from "./i18n";

export const DISPLAY_TIME_ZONE = "Asia/Tbilisi";

/** Format a UTC ISO timestamp for display in Asia/Tbilisi. Returns null for missing/invalid input. */
export function formatTbilisi(iso: string | null | undefined, locale: Locale): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(locale === "ka" ? "ka-GE" : "en-GB", {
    timeZone: DISPLAY_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

/** Format MW with fixed precision. Zero is a valid reading and must render as "0.0". */
export function formatMw(value: number | null | undefined): string | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  return value.toFixed(1);
}
