import { StatusBadge } from "@/components/StatusBadge";
import { getGenerationHistory, getGenerationLatest, getSystemStatus } from "@/lib/api";
import { formatTbilisi } from "@/lib/format";
import { generationKpiView } from "@/lib/kpi";
import { getI18n } from "@/lib/locale-server";
import { freshnessTone, workerTone } from "@/lib/status";

export default async function DashboardPage() {
  const [{ locale, t }, generation, status, history] = await Promise.all([
    getI18n(),
    getGenerationLatest(),
    getSystemStatus(),
    getGenerationHistory(),
  ]);
  const kpi = generationKpiView(generation);
  const sites = status.ok ? status.data.sites : null;
  const reasonText = kpi.apiReachable
    ? kpi.reason && (t.reasons[kpi.reason] ?? kpi.reason)
    : t.apiUnreachable;

  return (
    <div className="grid gap-5 lg:grid-cols-12">
      <section aria-labelledby="kpi-total" className="wc-panel relative overflow-hidden p-5 sm:p-7 lg:col-span-8">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-cyan-glow/10 blur-3xl"
        />
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h1 id="kpi-total" className="wc-label">
            {t.kpi.totalWind}
          </h1>
          <StatusBadge tone={freshnessTone(kpi.freshness)}>{t.freshness[kpi.freshness]}</StatusBadge>
        </div>

        <div className="mt-5 flex items-baseline gap-3" data-testid="kpi-total-value">
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
          <p className="mt-2 max-w-xl text-sm text-amber-warn" data-testid="kpi-quality-flag">
            {t.kpi.qualityFlagged}
          </p>
        )}

        <dl className="mt-6 grid gap-4 border-t border-line pt-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
          <Meta label={t.kpi.source}>
            {generation.ok ? (
              <a className="text-cyan-glow hover:underline" href={generation.data.source.url} rel="noreferrer" target="_blank">
                {generation.data.source.name}
              </a>
            ) : (
              "GSE"
            )}
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
        <SmallKpi label={t.kpi.ingestionStatus}>
          {status.ok ? (
            <StatusBadge tone={workerTone(status.data.worker.state)}>{t.worker[status.data.worker.state]}</StatusBadge>
          ) : (
            <StatusBadge tone="bad">{t.apiUnreachable}</StatusBadge>
          )}
        </SmallKpi>
        <SmallKpi label={t.kpi.forecastHorizon} note={t.kpi.forecastHorizonPending}>
          <span className="text-lg text-slate-300">{t.unavailable}</span>
        </SmallKpi>
      </div>

      <section aria-labelledby="history-title" className="wc-panel p-5 lg:col-span-8">
        <h2 id="history-title" className="wc-label">
          {t.history.title}
        </h2>
        <div className="mt-4 flex h-56 flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-line bg-ink-900/60 px-6 text-center text-sm text-slate-400">
          {!history.ok ? (
            <span>{t.apiUnreachable}</span>
          ) : history.data.points.length === 0 ? (
            <span>{t.history.empty}</span>
          ) : (
            <>
              <span className="text-slate-200">{t.history.collected(history.data.points.length)}</span>
              {history.data.collection_started_at && (
                <span>
                  {t.history.since}: {formatTbilisi(history.data.collection_started_at, locale)}
                </span>
              )}
              <span>{t.history.gaps(history.data.gaps.length)}</span>
              <span className="text-xs text-slate-500">{t.history.chartPending}</span>
            </>
          )}
        </div>
      </section>

      <section aria-labelledby="sites-title" className="wc-panel p-5 lg:col-span-4">
        <h2 id="sites-title" className="wc-label">
          {t.sites.title}
        </h2>
        {sites ? (
          <ul className="mt-4 space-y-3">
            {sites.map((site) => (
              <li key={site.id} className="rounded-lg border border-line bg-ink-900/60 px-3 py-2.5">
                <div className="text-sm font-medium text-slate-100">{locale === "ka" ? site.name_ka : site.name_en}</div>
                <div className="mt-0.5 text-xs text-slate-400">
                  {site.coordinates_verified && site.latitude !== null && site.longitude !== null
                    ? `${site.latitude.toFixed(4)}°N, ${site.longitude.toFixed(4)}°E`
                    : t.sites.coordinatesPending}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-4 text-sm text-slate-400">{t.apiUnreachable}</p>
        )}
        <p className="mt-4 text-xs text-slate-500">{t.sites.noMw}</p>
      </section>

      <section aria-labelledby="types-title" className="wc-panel p-5 lg:col-span-12">
        <h2 id="types-title" className="wc-label">
          {t.dataTypes.title}
        </h2>
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

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-0.5 tabular-nums text-slate-200">{children}</dd>
    </div>
  );
}

function SmallKpi({ label, note, children }: { label: string; note?: string; children: React.ReactNode }) {
  return (
    <section className="wc-panel flex flex-col justify-between gap-3 p-5">
      <h2 className="wc-label">{label}</h2>
      <div>{children}</div>
      {note && <p className="text-xs text-slate-500">{note}</p>}
    </section>
  );
}

function DataType({ swatch, entry }: { swatch: string; entry: [string, string] }) {
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
