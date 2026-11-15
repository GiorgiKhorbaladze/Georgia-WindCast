/** Wind direction helpers. Meteorological convention: direction is where the wind comes FROM. */

const COMPASS_EN = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
const COMPASS_KA = ["ჩ", "ჩჩა", "ჩა", "აჩა", "ა", "ასა", "სა", "სსა", "ს", "სსდ", "სდ", "დსდ", "დ", "დჩდ", "ჩდ", "ჩჩდ"];

export function normalizeDeg(deg: number): number {
  return ((deg % 360) + 360) % 360;
}

/** Bearing the air moves TOWARD (downwind), clockwise from north. */
export function downwindBearing(fromDeg: number): number {
  return normalizeDeg(fromDeg + 180);
}

export function compass(fromDeg: number, locale: "ka" | "en"): string {
  const idx = Math.round(normalizeDeg(fromDeg) / 22.5) % 16;
  return (locale === "ka" ? COMPASS_KA : COMPASS_EN)[idx];
}

/** Screen-space unit vector (x right, y down) for a downwind bearing. */
export function screenVector(fromDeg: number): { dx: number; dy: number } {
  const rad = (downwindBearing(fromDeg) * Math.PI) / 180;
  return { dx: Math.sin(rad), dy: -Math.cos(rad) };
}

export function formatSpeed(v: number | null | undefined): string | null {
  if (v === null || v === undefined || !Number.isFinite(v)) return null;
  return v.toFixed(1);
}
