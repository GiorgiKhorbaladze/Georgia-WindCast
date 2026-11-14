"use client";

import { useMemo, useState } from "react";

import { EChart } from "@/components/charts/EChart";
import { baseChart, COLORS, tbilisiAxisLabel, tbilisiTooltipTime } from "@/lib/chartTheme";
import { formatTbilisiMinute, tbilisiInputValue } from "@/lib/format";
import { getDictionary, type Locale } from "@/lib/i18n";
import { withGapBreaks } from "@/lib/series";
import type { GenerationHistory } from "@/lib/types";

const RANGES = { "24h": 24, "7d": 24 * 7, "30d": 24 * 30 } as const;
type RangeKey = keyof typeof RANGES | "custom";
const MAX_DAYS = 31;

export function buildGenerationOption(h: GenerationHistory, locale: Locale) {
  const t = getDictionary(locale);
  const spanMs = Date.parse(h.end) - Date.parse(h.start);
  const data = withGapBreaks(h.points, (p) => p.t, (p) => p.value_mw, h.gaps);
  const marks: [{ xAxis: number; name?: string }, { xAxis: number }][] = h.gaps.map((g) => [
    { xAxis: Date.parse(g.start), name: t.history.gapLegend },
    { xAxis: Date.parse(g.end) },
  ]);
  // Time before collection began is not a source gap: shown faintly, without the amber gap style.
  const before =
    h.collection_started_at && Date.parse(h.collection_started_at) > Date.parse(h.start)
      ? [[
          {
            xAxis: Date.parse(h.start),
            name: t.history.beforeCollection,
            itemStyle: { color: "rgba(148,163,184,0.04)", borderWidth: 0 },
            label: { color: "#64748b" },
          },
          { xAxis: Date.parse(h.collection_started_at) },
        ]]
      : [];
  const tip = tbilisiTooltipTime();
  return {
    ...baseChart,
    tooltip: {
      ...baseChart.tooltip,
      valueFormatter: (v: number | null) => (v === null || v === undefined ? "-" : `${v.toFixed(1)} MW`),
      axisPointer: { type: "line", lineStyle: { color: COLORS.actual, opacity: 0.4 }, label: { formatter: (p: { value: number }) => tip(p.value) } },
    },
    xAxis: {
      type: "time",
      min: Date.parse(h.start),
      max: Date.parse(h.end),
      axisLine: { lineStyle: { color: COLORS.axis } },
      axisLabel: { color: COLORS.text, formatter: tbilisiAxisLabel(spanMs > 36 * 3600e3), hideOverlap: true },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      name: "MW",
      nameTextStyle: { color: COLORS.text },
      min: (v: { min: number }) => Math.min(0, Math.floor(v.min)),
      axisLabel: { color: COLORS.text },
      splitLine: { lineStyle: { color: COLORS.grid } },
    },
    dataZoom: [{ type: "inside", throttle: 50 }],
    series: [
      {
        name: t.history.series,
        type: "line",
        data,
        showSymbol: data.length < 60,
        symbolSize: 4,
        connectNulls: false,
        sampling: "lttb",
        lineStyle: { color: COLORS.actual, width: 2 },
        itemStyle: { color: COLORS.actual },
        areaStyle: {
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: "rgba(34,211,238,0.28)" }, { offset: 1, color: "rgba(34,211,238,0)" }],
          },
        },
        markArea: {
          silent: true,
          label: { color: "#fbbf24", fontSize: 10, position: "insideTop" },
          itemStyle: { color: COLORS.gap, borderColor: COLORS.gapBorder, borderWidth: 1, borderType: "dashed" },
          data: [...marks, ...before],
        },
      },
    ],
  };
}

function fromTbilisiInput(v: string): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(v)) return null;
  const d = new Date(`${v}:00+04:00`);
  return Number.isNaN(d.getTime()) ? null : d;
}

export function GenerationExplorer({
  initial,
  locale,
  compact = false,
}: {
  initial: GenerationHistory | null;
  locale: Locale;
  compact?: boolean;
}) {
  const t = getDictionary(locale);
  const [history, setHistory] = useState<GenerationHistory | null>(initial);
  const [range, setRange] = useState<RangeKey>("24h");
  const [error, setError] = useState<string | null>(initial ? null : t.apiUnreachable);
  const [loading, setLoading] = useState(false);
  // Initialised from the server-provided range so server and client render identical markup.
  const [from, setFrom] = useState(initial ? tbilisiInputValue(initial.start) : "");
  const [to, setTo] = useState(initial ? tbilisiInputValue(initial.end) : "");

  async function load(start: Date, end: Date) {
    setLoading(true);
    setError(null);
    try {
      const q = new URLSearchParams({ start: start.toISOString(), end: end.toISOString() });
      const res = await fetch(`/api/data/generation-history?${q}`, { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      setHistory((await res.json()) as GenerationHistory);
    } catch {
      setError(t.apiUnreachable);
    } finally {
      setLoading(false);
    }
  }

  function chooseRange(key: keyof typeof RANGES) {
    setRange(key);
    const end = new Date();
    void load(new Date(end.getTime() - RANGES[key] * 3600e3), end);
  }

  function applyCustom(e: React.FormEvent) {
    e.preventDefault();
    const s = fromTbilisiInput(from);
    const en = fromTbilisiInput(to);
    if (!s || !en || s >= en || en.getTime() - s.getTime() > MAX_DAYS * 86400e3) {
      setError(t.history.invalidRange);
      return;
    }
    setRange("custom");
    void load(s, en);
  }

  const option = useMemo(() => (history ? buildGenerationOption(history, locale) : null), [history, locale]);

  return (
    <div>
      {!compact && (
        <div className="flex flex-wrap items-end gap-3">
          <div role="group" aria-label={t.history.title} className="flex rounded-md border border-line p-0.5">
            {(Object.keys(RANGES) as (keyof typeof RANGES)[]).map((k) => (
              <button
                key={k}
                type="button"
                aria-pressed={range === k}
                onClick={() => chooseRange(k)}
                className={`rounded px-3 py-1.5 text-sm ${range === k ? "bg-cyan-glow/15 text-cyan-glow" : "text-slate-300 hover:text-white"}`}
              >
                {t.history[`range${k}` as "range24h" | "range7d" | "range30d"]}
              </button>
            ))}
          </div>
          <form onSubmit={applyCustom} className="flex flex-wrap items-end gap-2 text-sm">
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              {t.history.from}
              <input type="datetime-local" value={from} onChange={(e) => setFrom(e.target.value)}
                className="rounded-md border border-line bg-ink-900 px-2 py-1.5 text-sm text-slate-100" />
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              {t.history.to}
              <input type="datetime-local" value={to} onChange={(e) => setTo(e.target.value)}
                className="rounded-md border border-line bg-ink-900 px-2 py-1.5 text-sm text-slate-100" />
            </label>
            <button type="submit" aria-pressed={range === "custom"}
              className="rounded-md border border-cyan-glow/40 px-3 py-1.5 text-cyan-glow hover:bg-cyan-glow/10">
              {t.history.apply}
            </button>
          </form>
          <span aria-live="polite" className="text-xs text-slate-400">{loading ? t.loading : ""}</span>
        </div>
      )}
      {error && <p role="alert" className="mt-3 text-sm text-rose-warn">{error}</p>}
      {history && history.points.length === 0 ? (
        <div className="mt-4 flex h-56 items-center justify-center rounded-lg border border-dashed border-line bg-ink-900/60 px-6 text-center text-sm text-slate-400">
          {t.history.empty}
        </div>
      ) : option ? (
        <EChart option={option} height={compact ? 220 : 380} ariaLabel={t.history.series} className="mt-3" />
      ) : null}
      {history && history.points.length > 0 && (
        <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400" data-testid="history-summary">
          <span>{t.history.collected(history.points.length)}</span>
          {history.collection_started_at && (
            <span>{t.history.since}: {formatTbilisiMinute(history.collection_started_at)}</span>
          )}
          <span>{t.history.gaps(history.gaps.length)}</span>
        </p>
      )}
    </div>
  );
}
