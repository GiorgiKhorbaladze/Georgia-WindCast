// Mirrors backend/app/schemas.py. There is intentionally no per-site MW type.

export type Freshness = "fresh" | "stale" | "unverified" | "unavailable";
export type WorkerState = "running" | "stale" | "never_seen";
export type SourceState = "not_configured" | "ok" | "degraded" | "down";

export interface SourceAttribution {
  name: string;
  url: string;
}

export interface GenerationLatest {
  scope: "national_aggregate";
  unit: "MW";
  freshness: Freshness;
  value_mw: number | null;
  source_observed_at: string | null;
  retrieved_at: string | null;
  reason: string | null;
  quality: string | null;
  quality_flagged: boolean;
  period_seconds: number | null;
  source: SourceAttribution;
}

export interface GenerationHistory {
  scope: "national_aggregate";
  unit: "MW";
  start: string;
  end: string;
  cadence_seconds: number;
  collection_started_at: string | null;
  points: { t: string; value_mw: number; quality: string }[];
  gaps: { start: string; end: string }[];
  source: SourceAttribution;
}

export interface SiteSummary {
  id: string;
  name_ka: string;
  name_en: string;
  coordinates_verified: boolean;
  latitude: number | null;
  longitude: number | null;
}

export interface SystemStatus {
  generated_at: string;
  app_env: string;
  worker: { state: WorkerState; last_seen_at: string | null };
  sources: { id: string; state: SourceState; detail: string | null }[];
  sites: SiteSummary[];
}

export type ApiResult<T> = { ok: true; data: T } | { ok: false; error: string };
