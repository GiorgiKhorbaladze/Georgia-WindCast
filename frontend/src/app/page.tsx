import Link from "next/link";

import { GenerationExplorer } from "@/components/GenerationChart";
import { StatusBadge, type Tone } from "@/components/StatusBadge";
import { getGenerationHistory, getGenerationLatest, getSystemStatus, getWeatherOverview } from "@/lib/api";
import { formatTbilisi } from "@/lib/format";
import { generationKpiView } from "@/lib/kpi";
import { getI18n } from "@/lib/locale-server";
import { freshnessTone, workerTone } from "@/lib/status";
import type { SourceState, WeatherOverview } from "@/lib/types";
import { compass, downwindBearing, formatSpeed } from "@/lib/wind";

const SOURCE_TONE: Record<SourceState, Tone> = { ok: "ok", degraded: "warn", down: "bad", not_configured: "neutral" };
const NOW_HEIGHTS = [10, 80, 120, 180];

export default async function DashboardPage() {
  const [{ locale, t }, generation, status, history, weather] = await Promise.all([
    getI18n(),
    getGenerationLatest(),
    getSystemStatus(),
    getGenerationHistory(),
    getWeatherOverview(),
  ]);
  const kpi = generationKpiView(generation);
  const sites = status.ok ? status.data.sites : weather.ok ? weather.data.sites : null;
  const reasonText = kpi.apiReachable ? kpi.reason && (t.reasons[kpi.reason] ?? kpi.reason) : t.apiUnreachable;
  const w = weather.ok ? weather.data : null;

  return (
    <div className="grid gap-5 lg:grid-cols-12">
      <section aria-labelledby="kpi-total" className="wc-panel relative overflow-hidden p-5 sm:p-7 lg:col-span-8">
        <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-cyan-glow/10 blur-3xl" />
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 id="kpi-total" className="wc-label">{t.kpi.totalWind}</h1>
          <StatusBadge tone={freshnessTone(kpi.freshness)}>{t.freshness[kpi.freshness]}</StatusBadge>
        </div>
        <div className="mt-5 flex flex-wrap items-baseline gap-3" data-testid="kpi-total-value">
          {kpi.value !== null ? (
            <>
              <span className="font-mono text-6xl font-semibold tracking-tight text-white sm:text-7xl">{kpi.value}</span>
              <span className="font-mono text-2xl text-cyan-glow">MW</span>
              <span className="text-xs text-slate-400">{t.kpi.periodAverage}</span>
            </>
          ) : (
            <span className="text-3xl font-semibold text-slate-300 sm:text-4xl">{t.unavailable}</span>
          )}
        </div>
        {reasonText && <p className="mt-2 max-w-xl text-sm text-slate-400">{reasonText}</p>}
        {kpi.qualityFlagged && (
          <p className="mt-2 max-w-xl text-sm text-amber-warn" data-testid="kpi-quality-flag">{t.kpi.qualityFlagged}</p>
        )}
        <dl className="mt-6 grid gap-4 border-t border-line pt-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
          <Meta label={t.kpi.source}>
            {generation.ok ? (
              <a className="text-cyan-glow hover:underline" href={generation.data.source.url} rel="noreferrer" target="_blank">
                {generation.data.source.name}
              </a>
            ) : "GSE"}
          </Meta>
          <Meta label={t.kpi.observedAt}>{formatTbilisi(kpi.observedAt, locale) ?? t.kpi.notReported}</Meta>
          <Meta label={t.kpi.retrievedAt}>{formatTbilisi(kpi.retrievedAt, locale) ?? t.kpi.notReported}</Meta>
          <Meta label={t.kpi.quality}>{kpi.quality ?? t.kpi.notReported}</Meta>
        </dl>
        <p className="mt-4 text-xs text-slate-500">{t.kpi.scopeNote}</p>
      </section>

      <div className="grid gap-5 sm:grid-cols-3 lg:col-span-4 lg:grid-cols-1">
        <SmallKpi label={t.kpi.trackedLocations} note={t.kpi.trackedLocationsNote}>
          <span className="font-mono text-3xl text-white">{sites ? sites.length : "-"}</span>
        </SmallKpi>
        <SmallKpi label={t.kpi.forecastHorizon} note={w?.forecast_model_label}>
          <ForecastHorizon w={w} locale={locale} t={t} />
        </SmallKpi>
        <SmallKpi label={t.kpi.ingestionStatus}>
          {status.ok ? (
            <ul className="space-y-1.5 text-xs" data-testid="source-status">
              <li className="flex items-center justify-between gap-2">
                <span className="text-slate-300">{t.sourceName.worker}</span>
                <StatusBadge tone={workerTone(status.data.worker.state)}>{t.worker[status.data.worker.state]}</StatusBadge>
              </li>
              {status.data.sources.map((s) => (
                <li key={s.id} className="flex items-center justify-between gap-2" title={s.detail ?? undefined}>
                  <span className="text-slate-300">{t.sourceName[s.id] ?? s.id}</span>
                  <StatusBadge tone={SOURCE_TONE[s.state]}>{t.sourceState[s.state]}</StatusBadge>
                </li>
              ))}
            </ul>
          ) : (
            <StatusBadge tone="bad">{t.apiUnreachable}</StatusBadge>
          )}
        </SmallKpi>
      </div>

      <section aria-labelledby="history-title" className="wc-panel p-5 lg:col-span-8">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="history-title" className="wc-label">{t.history.title} · {t.history.range24h}</h2>
          <Link href="/history" className="text-xs text-cyan-glow hover:underline">{t.nav.history} →</Link>
        </div>
        <GenerationExplorer initial={history.ok ? history.data : null} locale={locale} compact />
      </section>

      <section aria-labelledby="wind-now" className="wc-panel p-5 lg:col-span-4" data-testid="weather-now">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="wind-now" className="wc-label">{t.weather.now}</h2>
          <Link href="/map" className="text-xs text-cyan-glow hover:underline">{t.nav.map} →</Link>
        </div>
        {sites ? (
          <ul className="mt-4 space-y-3">
            {sites.map((site) => {
              const rows = w?.now.filter((n) => n.site_id === site.id) ?? [];
              const ref = rows.find((n) => n.height_m === 120);
              return (
                <li key={site.id} className="rounded-lg border border-line bg-ink-900/60 px-3 py-2.5">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium text-slate-100">{locale === "ka" ? site.name_ka : site.name_en}</span>
                    {ref?.direction_deg != null && (
                      <span className="flex items-center gap-1 text-xs text-slate-400">
                        <svg viewBox="-12 -12 24 24" width="14" height="14" aria-hidden="true" style={{ transform: `rotate(${downwindBearing(ref.direction_deg)}deg)` }}>
                          <path d="M0,-10 L6,6 L0,2 L-6,6 Z" fill="currentColor" />
                        </svg>
                        {t.weather.from} {compass(ref.direction_deg, locale)}
                      </span>
                    )}
                  </div>
                  <div className="mt-1.5 grid grid-cols-4 gap-1 text-center">
                    {NOW_HEIGHTS.map((h) => {
                      const n = rows.find((r) => r.height_m === h);
                      return (
                        <div key={h} className="rounded bg-ink-950/60 px-1 py-1">
                          <div className="text-[10px] text-slate-500">{h} m</div>
                          <div className="font-mono text-sm text-teal-glow">{formatSpeed(n?.speed_ms) ?? "-"}</div>
                        </div>
                      );
                    })}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="mt-4 text-sm text-slate-400">{t.apiUnreachable}</p>
        )}
        <p className="mt-3 text-xs text-slate-500">m/s · {t.weather.notMeasured}. {t.sites.noMw}</p>
      </section>

      <section aria-labelledby="types-title" className="wc-panel p-5 lg:col-span-12">
        <h2 id="types-title" className="wc-label">{t.dataTypes.title}</h2>
        <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <DataType swatch="bg-cyan-glow" entry={t.dataTypes.actual} />
          <DataType swatch="bg-teal-glow" entry={t.dataTypes.model} />
          <DataType swatch="border-2 border-dashed border-violet-glow" entry={t.dataTypes.forecast} />
          <DataType swatch="bg-[repeating-linear-gradient(45deg,#fbbf24_0_3px,transparent_3px_6px)]" entry={t.dataTypes.missing} />
        </ul>
      </section>
    </div>
  );
}

function ForecastHorizon({ w, locale, t }: { w: WeatherOverview | null; locale: "ka" | "en"; t: Awaited<ReturnType<typeof getI18n>>["t"] }) {
  if (!w) return <span className="text-sm text-slate-400">{t.apiUnreachable}</span>;
  if (!w.forecast_horizon_end) return <span className="text-lg text-slate-300">{t.kpi.forecastHorizonPending}</span>;
  const hours = Math.round((Date.parse(w.forecast_horizon_end) - Date.parse(w.generated_at)) / 3600e3);
  return (
    <div className="space-y-1">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-3xl text-white">{hours}</span>
        <span className="text-sm text-violet-glow">h</span>
        <StatusBadge tone={freshnessTone(w.forecast_state)}>{t.freshness[w.forecast_state]}</StatusBadge>
      </div>
      <div className="text-xs text-slate-400">{t.kpi.until}: {formatTbilisi(w.forecast_horizon_end, locale)}</div>
      <div className="text-xs text-slate-400">{t.weather.run}: {formatTbilisi(w.forecast_run_at, locale) ?? "-"}</div>
    </div>
  );
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-0.5 tabular-nums text-slate-200">{children}</dd>
    </div>
  );
}

function SmallKpi({ label, note, children }: { label: string; note?: string | null; children: React.ReactNode }) {
  return (
    <section className="wc-panel flex flex-col justify-between gap-3 p-5">
      <h2 className="wc-label">{label}</h2>
      <div>{children}</div>
      {note && <p className="text-xs text-slate-500">{note}</p>}
    </section>
  );
}

function DataType({ swatch, entry }: { swatch: string; entry: string[] }) {
  return (
    <li className="flex items-start gap-3 rounded-lg border border-line bg-ink-900/60 p-3">
      <span aria-hidden="true" className={`mt-1 h-3 w-6 shrink-0 rounded-sm ${swatch}`} />
      <span>
        <span className="block text-sm text-slate-100">{entry[0]}</span>
        <span className="block text-xs text-slate-400">{entry[1]}</span>
      </span>
    </li>
  );
}
