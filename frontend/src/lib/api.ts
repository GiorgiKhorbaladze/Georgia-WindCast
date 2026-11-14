import type { ApiResult, GenerationLatest, SystemStatus } from "./types";

// Server-side only. The browser never talks to the backend directly in this stage, so no
// backend address or credential is shipped to the client bundle.
const DEFAULT_TIMEOUT_MS = 4000;

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

export const getGenerationLatest = () => getJson<GenerationLatest>("/api/v1/generation/latest");
export const getSystemStatus = () => getJson<SystemStatus>("/api/v1/status");
