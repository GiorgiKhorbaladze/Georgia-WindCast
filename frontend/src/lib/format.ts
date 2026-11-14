import type { Locale } from "./i18n";

export const DISPLAY_TIME_ZONE = "Asia/Tbilisi";

// Numeric parts only, so server (Node ICU) and browser render identical text (no hydration
// mismatch) regardless of locale data differences.
const PARTS = new Intl.DateTimeFormat("en-GB", {
  timeZone: DISPLAY_TIME_ZONE,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

export interface TbilisiParts {
  year: string;
  month: string;
  day: string;
  hour: string;
  minute: string;
  second: string;
}

export function tbilisiParts(date: Date): TbilisiParts {
  const out: Record<string, string> = {};
  for (const p of PARTS.formatToParts(date)) if (p.type !== "literal") out[p.type] = p.value;
  return out as unknown as TbilisiParts;
}

function toDate(v: string | number | Date | null | undefined): Date | null {
  if (v === null || v === undefined) return null;
  const d = v instanceof Date ? v : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** "15.11.2026 00:48:00" in Asia/Tbilisi. The format is the same for both UI languages. */
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export function formatTbilisi(v: string | number | Date | null | undefined, locale?: Locale): string | null {
  const d = toDate(v);
  if (!d) return null;
  const p = tbilisiParts(d);
  return `${p.day}.${p.month}.${p.year} ${p.hour}:${p.minute}:${p.second}`;
}

/** "15.11.2026 00:48" */
export function formatTbilisiMinute(v: string | number | Date | null | undefined): string | null {
  const d = toDate(v);
  if (!d) return null;
  const p = tbilisiParts(d);
  return `${p.day}.${p.month}.${p.year} ${p.hour}:${p.minute}`;
}

/** "15.11 00:48" or "00:48" */
export function formatTbilisiShort(v: string | number | Date, withDate: boolean): string {
  const d = toDate(v);
  if (!d) return "";
  const p = tbilisiParts(d);
  return withDate ? `${p.day}.${p.month} ${p.hour}:${p.minute}` : `${p.hour}:${p.minute}`;
}

/** Value for <input type="datetime-local"> expressed in Tbilisi time. */
export function tbilisiInputValue(v: string | number | Date): string {
  const p = tbilisiParts(toDate(v) ?? new Date(0));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

/** Format MW with fixed precision. Zero is a valid reading and must render as "0.0". */
export function formatMw(value: number | null | undefined): string | null {
  if (value === null || value === undefined || !Number.isFinite(value)) return null;
  return value.toFixed(1);
}
