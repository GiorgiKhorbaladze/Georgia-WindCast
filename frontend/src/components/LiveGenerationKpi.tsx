"use client";

import { useEffect, useMemo, useState } from "react";

import { StatusBadge } from "@/components/StatusBadge";
import { formatTbilisi } from "@/lib/format";
import { getDictionary, type Locale } from "@/lib/i18n";
import { KPI_REFRESH_MS, liveKpiView } from "@/lib/liveKpi";
import { freshnessTone } from "@/lib/status";
import type { ApiResult, GenerationLatest } from "@/lib/types";

const TICK_MS = 15_000;

/**
 * National MW KPI for an open dashboard: refreshes through the app backend while visible, expires
 * its badge locally at `fresh_until`, and marks the kept value stale when a refresh fails.
 */
export function LiveGenerationKpi({ initial, locale }: { initial: ApiResult<GenerationLatest>; locale: Locale }) {
  const t = getDictionary(locale);
  const [last, setLast] = useState(initial);
  const [refreshFailed, setRefreshFailed] = useState(false);
  // Server-provided time keeps the first render identical on server and client (no hydration drift).
  const [nowMs, setNowMs] = useState(() => (initial.ok && initial.data.checked_at ? Date.parse(initial.data.checked_at) : 0));

  useEffect(() => {
    let cancelled = false;
    async function refresh() {
      if (document.visibilityState === "hidden") return;
      try {
        const res = await fetch("/api/data/generation-latest", { cache: "no-store", signal: AbortSignal.timeout(8000) });
        if (!res.ok) throw new Error(String(res.status));
        const data = (await res.json()) as GenerationLatest;
        if (cancelled) return;
        setLast({ ok: true, data });
        setRefreshFailed(false);
      } catch {
        if (!cancelled) setRefreshFailed(true);
      } finally {
        if (!cancelled) setNowMs(Date.now());
      }
    }
    const tick = window.setInterval(() => setNowMs(Date.now()), TICK_MS);
    const poll = window.setInterval(refresh, KPI_REFRESH_MS);
    const onVisible = () => document.visibilityState === "visible" && void refresh();
    document.addEventListener("visibilitychange", onVisible);
    const first = window.setTimeout(() => setNowMs(Date.now()), 0);
    return () => {
      cancelled = true;
      window.clearInterval(tick);
      window.clearInterval(poll);
      window.clearTimeout(first);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  const kpi = useMemo(() => liveKpiView({ last, refreshFailed, nowMs }), [last, refreshFailed, nowMs]);
  const reasonText = kpi.apiReachable ? kpi.reason && (t.reasons[kpi.reason] ?? kpi.reason) : t.apiUnreachable;

  return (
    <section aria-labelledby="kpi-total" className="wc-panel relative overflow-hidden p-5 sm:p-7 lg:col-span-8">
      <div aria-hidden="true" className="pointer-events-none absolute -right-24 -top-24 h-72 w-72 rounded-full bg-cyan-glow/10 blur-3xl" />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <h1 id="kpi-total" className="wc-label">{t.kpi.totalWind}</h1>
        <span data-testid="kpi-freshness" aria-live="polite">
          <StatusBadge tone={freshnessTone(kpi.freshness)}>{t.freshness[kpi.freshness]}</StatusBadge>
        </span>
      </div>
      <div className="mt-5 flex flex-wrap items-baseline gap-3" data-testid="kpi-total-value">
        {kpi.value !== null ? (
          <>
            <span className={`font-mono text-6xl font-semibold tracking-tight sm:text-7xl ${kpi.freshness === "fresh" ? "text-white" : "text-slate-300"}`}>
              {kpi.value}
            </span>
            <span className="font-mono text-2xl text-cyan-glow">MW</span>
            <span className="text-xs text-slate-400">{t.kpi.periodAverage}</span>
          </>
        ) : (
          <span className="text-3xl font-semibold text-slate-300 sm:text-4xl">{t.unavailable}</span>
        )}
      </div>
      {reasonText && <p className="mt-2 max-w-xl text-sm text-slate-400" data-testid="kpi-reason">{reasonText}</p>}
      {kpi.qualityFlagged && (
        <p className="mt-2 max-w-xl text-sm text-amber-warn" data-testid="kpi-quality-flag">{t.kpi.qualityFlagged}</p>
      )}
      <dl className="mt-6 grid gap-4 border-t border-line pt-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
        <Meta label={t.kpi.source}>
          {last.ok ? (
            <a className="text-cyan-glow hover:underline" href={last.data.source.url} rel="noreferrer" target="_blank">
              {last.data.source.name}
            </a>
          ) : "GSE"}
        </Meta>
        <Meta label={t.kpi.observedAt}>{formatTbilisi(kpi.observedAt, locale) ?? t.kpi.notReported}</Meta>
        <Meta label={t.kpi.retrievedAt}>{formatTbilisi(kpi.retrievedAt, locale) ?? t.kpi.notReported}</Meta>
        <Meta label={t.kpi.quality}>{kpi.quality ?? t.kpi.notReported}</Meta>
      </dl>
      <p className="mt-4 text-xs text-slate-400">{t.kpi.scopeNote}</p>
    </section>
  );
}

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-slate-400">{label}</dt>
      <dd className="mt-0.5 tabular-nums text-slate-200">{children}</dd>
    </div>
  );
}
