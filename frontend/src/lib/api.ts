import type {
  ApiResult,
  GenerationHistory,
  GenerationLatest,
  SiteWeather,
  SystemStatus,
  WeatherOverview,
} from "./types";

// Server-side only. The browser reaches backend data exclusively through this app's own
// /api/data/* route handlers, so no backend address or credential is shipped to the client.
const DEFAULT_TIMEOUT_MS = 6000;

export function apiBaseUrl(): string {
  return (process.env.WINDCAST_API_URL ?? "http://localhost:8000").replace(/\/+$/, "");
}

export async function getJson<T>(path: string, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<ApiResult<T>> {
  try {
    const res = await fetch(`${apiBaseUrl()}${path}`, {
      cache: "no-store",
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (!res.ok) return { ok: false, error: `http_${res.status}` };
    return { ok: true, data: (await res.json()) as T };
  } catch (err) {
    const name = err instanceof Error ? err.name : "unknown";
    return { ok: false, error: name === "TimeoutError" ? "timeout" : "unreachable" };
  }
}

function query(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const getGenerationLatest = () => getJson<GenerationLatest>("/api/v1/generation/latest");
export const getSystemStatus = () => getJson<SystemStatus>("/api/v1/status");
export const getGenerationHistory = (start?: string | null, end?: string | null) =>
  getJson<GenerationHistory>(`/api/v1/generation/history${query({ start, end })}`);
export const getWeatherOverview = () => getJson<WeatherOverview>("/api/v1/weather");
export const getSiteWeather = (siteId: string, height: number, start?: string | null, end?: string | null) =>
  getJson<SiteWeather>(`/api/v1/weather/sites/${encodeURIComponent(siteId)}${query({ height, start, end })}`);
