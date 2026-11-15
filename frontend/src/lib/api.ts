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

/**
 * Short-lived server-side cache with request coalescing (issue #18 load test).
 *
 * Many simultaneous visitors share one backend request per URL: concurrent callers await the same
 * in-flight promise, and a successful response is reused for WINDCAST_API_CACHE_SECONDS (default
 * 5 s). Failures are never cached. The data changes every 3 minutes at most (GSE) and the API
 * reports source times and freshness explicitly, so a few seconds of reuse cannot make stale data
 * look current. The cache is bounded so unique query strings cannot grow memory without limit.
 */
const MAX_ENTRIES = 256;
const cache = new Map<string, { expires: number; value: Promise<ApiResult<unknown>> }>();

function cacheTtlMs(): number {
  const raw = Number(process.env.WINDCAST_API_CACHE_SECONDS ?? "5");
  return Number.isFinite(raw) && raw > 0 ? Math.min(raw, 60) * 1000 : 0;
}

export function cachedJson<T>(path: string, now: () => number = Date.now): Promise<ApiResult<T>> {
  const ttl = cacheTtlMs();
  if (ttl === 0) return getJson<T>(path);
  const hit = cache.get(path);
  if (hit && hit.expires > now()) return hit.value as Promise<ApiResult<T>>;
  // In flight: concurrent callers share this promise until it settles.
  const entry: { expires: number; value: Promise<ApiResult<unknown>> } = {
    expires: Number.POSITIVE_INFINITY,
    value: Promise.resolve({ ok: false, error: "pending" }),
  };
  const value = getJson<T>(path).then((result) => {
    // Only touch the entry this request created: it may have been evicted and replaced by a
    // newer request for the same path, which must keep its own lifecycle (review R2).
    if (cache.get(path) === entry) {
      if (result.ok) entry.expires = now() + ttl;
      else cache.delete(path); // never keep failures
    }
    return result;
  });
  entry.value = value;
  cache.set(path, entry);
  if (cache.size > MAX_ENTRIES) cache.delete(cache.keys().next().value!);
  return value;
}

export function clearApiCache(): void {
  cache.clear();
}

function query(params: Record<string, string | number | undefined | null>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export const getGenerationLatest = () => cachedJson<GenerationLatest>("/api/v1/generation/latest");
export const getSystemStatus = () => cachedJson<SystemStatus>("/api/v1/status");
export const getGenerationHistory = (start?: string | null, end?: string | null) =>
  cachedJson<GenerationHistory>(`/api/v1/generation/history${query({ start, end })}`);
export const getWeatherOverview = () => cachedJson<WeatherOverview>("/api/v1/weather");
export const getSiteWeather = (siteId: string, height: number, start?: string | null, end?: string | null) =>
  cachedJson<SiteWeather>(`/api/v1/weather/sites/${encodeURIComponent(siteId)}${query({ height, start, end })}`);
