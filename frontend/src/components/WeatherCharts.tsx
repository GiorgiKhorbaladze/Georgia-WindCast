"use client";

import { useMemo, useState } from "react";

import { EChart } from "@/components/charts/EChart";
import { baseChart, COLORS, tbilisiAxisLabel, tbilisiTooltipTime } from "@/lib/chartTheme";
import { formatTbilisiMinute } from "@/lib/format";
import { getDictionary, type Locale } from "@/lib/i18n";
import { breakOnStep, type ChartDatum } from "@/lib/series";
import type { SiteWeather, WeatherPoint } from "@/lib/types";
import { compass, downwindBearing } from "@/lib/wind";

export const FORECAST_HEIGHTS = [10, 80, 120, 180] as const;
export const ALL_HEIGHTS = [10, 80, 100, 120, 180, 200] as const;
const HOUR = 3600e3;

function speedData(points: WeatherPoint[]): ChartDatum[] {
  return breakOnStep(points.map((p) => [Date.parse(p.t), p.speed_ms] as ChartDatum), 1.5 * HOUR);
}

export function buildWeatherOption(w: SiteWeather, locale: Locale) {
  const t = getDictionary(locale);
  const tip = tbilisiTooltipTime();
  const all = [...w.history.points, ...w.forecast.points, ...w.reanalysis.points];
  const times = all.map((p) => Date.parse(p.t));
  const minT = times.length ? Math.min(...times) : Date.now() - 48 * HOUR;
  const maxT = times.length ? Math.max(...times) : Date.now() + 72 * HOUR;
  const now = Date.now();
  // Direction arrows: forecast + history, thinned to one every 3 h for legibility.
  const dirPoints = [...w.history.points, ...w.forecast.points]
    .filter((p) => p.direction_deg !== null && new Date(p.t).getUTCHours() % 3 === 0)
    .map((p) => ({
      value: [Date.parse(p.t), 0],
      dir: p.direction_deg as number,
      symbolRotate: -downwindBearing(p.direction_deg as number), // ECharts rotates counter-clockwise
      itemStyle: { color: Date.parse(p.t) >= now ? COLORS.forecast : COLORS.model },
    }));

  return {
    ...baseChart,
    legend: {
      top: 0,
      textStyle: { color: COLORS.text, fontSize: 11 },
      data: [t.weather.history, t.weather.forecast, t.weather.reanalysis],
    },
    tooltip: {
      ...baseChart.tooltip,
      axisPointer: { type: "line", label: { formatter: (p: { value: number }) => tip(p.value) } },
      formatter: (params: { seriesName: string; value: [number, number | null]; data: { dir?: number } }[]) => {
        if (!params.length) return "";
        const lines = [tip(params[0].value[0])];
        for (const p of params) {
          if (p.data && typeof p.data === "object" && "dir" in p.data && p.data.dir !== undefined) {
            lines.push(`${t.weather.direction}: ${t.weather.from} ${compass(p.data.dir, locale)} (${Math.round(p.data.dir)}°)`);
          } else if (p.value[1] !== null && p.value[1] !== undefined) {
            lines.push(`${p.seriesName}: ${p.value[1].toFixed(1)} m/s`);
          }
        }
        return lines.join("<br/>");
      },
    },
    grid: [
      { left: 44, right: 16, top: 34, height: "62%" },
      { left: 44, right: 16, bottom: 30, height: "12%" },
    ],
    xAxis: [
      {
        type: "time", min: minT, max: maxT, gridIndex: 0,
        axisLabel: { show: false }, axisLine: { lineStyle: { color: COLORS.axis } }, splitLine: { show: false },
      },
      {
        type: "time", min: minT, max: maxT, gridIndex: 1,
        axisLabel: { color: COLORS.text, formatter: tbilisiAxisLabel(true), hideOverlap: true },
        axisLine: { lineStyle: { color: COLORS.axis } },
      },
    ],
    yAxis: [
      {
        type: "value", gridIndex: 0, name: "m/s", min: 0, nameTextStyle: { color: COLORS.text },
        axisLabel: { color: COLORS.text }, splitLine: { lineStyle: { color: COLORS.grid } },
      },
      { type: "value", gridIndex: 1, min: -1, max: 1, show: false },
    ],
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    series: [
      {
        name: t.weather.history, type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false,
        data: speedData(w.history.points), connectNulls: false,
        lineStyle: { color: COLORS.model, width: 2 }, itemStyle: { color: COLORS.model },
        markLine: {
          silent: true, symbol: "none",
          label: { formatter: t.weather.nowLine, color: COLORS.text, fontSize: 10 },
          lineStyle: { color: "rgba(226,232,240,0.35)", type: "solid" },
          data: [{ xAxis: now }],
        },
      },
      {
        name: t.weather.forecast, type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false,
        data: speedData(w.forecast.points), connectNulls: false,
        lineStyle: { color: COLORS.forecast, width: 2, type: "dashed" }, itemStyle: { color: COLORS.forecast },
        areaStyle: { color: "rgba(167,139,250,0.08)" },
      },
      {
        name: t.weather.reanalysis, type: "line", xAxisIndex: 0, yAxisIndex: 0, showSymbol: false,
        data: speedData(w.reanalysis.points), connectNulls: false,
        lineStyle: { color: COLORS.reanalysis, width: 1.5, type: "dotted" }, itemStyle: { color: COLORS.reanalysis },
      },
      {
        name: t.weather.direction, type: "scatter", xAxisIndex: 1, yAxisIndex: 1,
        symbol: "path://M0,-10 L6,6 L0,2 L-6,6 Z", symbolSize: 11, data: dirPoints,
        tooltip: { show: true },
      },
    ],
  };
}

function SiteChart({ data, locale }: { data: SiteWeather; locale: Locale }) {
  const t = getDictionary(locale);
  const option = useMemo(() => buildWeatherOption(data, locale), [data, locale]);
  const noPoints = !data.history.points.length && !data.forecast.points.length && !data.reanalysis.points.length;
  const unsupported = !data.forecast.supported && !data.reanalysis.supported;
  return (
    <article className="wc-panel p-4 sm:p-5" aria-labelledby={`site-${data.site.id}`} data-testid={`weather-${data.site.id}`}>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={`site-${data.site.id}`} className="text-base font-semibold text-white">
          {locale === "ka" ? data.site.name_ka : data.site.name_en}
        </h2>
        <span className="text-xs text-slate-400">{t.weather.notMeasured}</span>
      </header>
      {unsupported ? (
        <p className="mt-6 rounded-lg border border-dashed border-line p-6 text-center text-sm text-slate-400">{t.weather.heightUnsupported}</p>
      ) : noPoints ? (
        <p className="mt-6 rounded-lg border border-dashed border-line p-6 text-center text-sm text-slate-400">{t.weather.noData}</p>
      ) : (
        <EChart option={option} height={300} ariaLabel={`${t.weather.title}: ${data.site.name_en}`} className="mt-2" />
      )}
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-400 sm:grid-cols-4">
        <div><dt className="text-slate-500">{t.weather.model}</dt><dd>{data.forecast.supported ? data.forecast.model_label : data.reanalysis.model_label}</dd></div>
        <div><dt className="text-slate-500">{t.weather.run}</dt><dd>{data.forecast.run_at ? formatTbilisiMinute(data.forecast.run_at) : "-"}</dd></div>
        <div><dt className="text-slate-500">{t.weather.retrieved}</dt><dd>{data.forecast.retrieved_at ? formatTbilisiMinute(data.forecast.retrieved_at) : "-"}</dd></div>
        <div><dt className="text-slate-500">{t.weather.gridPoint}</dt><dd>{data.forecast.grid_latitude !== null ? `${data.forecast.grid_latitude?.toFixed(3)}, ${data.forecast.grid_longitude?.toFixed(3)}` : "-"}</dd></div>
      </dl>
      {!data.forecast.supported && data.reanalysis.supported && (
        <p className="mt-2 text-xs text-amber-warn">{t.weather.forecast}: {t.weather.heightUnsupported}</p>
      )}
    </article>
  );
}

export function ForecastExplorer({
  initial,
  locale,
  initialHeight,
}: {
  initial: { id: string; data: SiteWeather | null }[];
  locale: Locale;
  initialHeight: number;
}) {
  const t = getDictionary(locale);
  const [height, setHeight] = useState(initialHeight);
  const [sites, setSites] = useState(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function choose(h: number) {
    setHeight(h);
    setLoading(true);
    setError(null);
    try {
      const results = await Promise.all(
        sites.map(async (s) => {
          const res = await fetch(`/api/data/weather/${s.id}?height=${h}`, { cache: "no-store" });
          return { id: s.id, data: res.ok ? ((await res.json()) as SiteWeather) : null };
        }),
      );
      setSites(results);
    } catch {
      setError(t.apiUnreachable);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-3">
        <span id="height-label" className="text-sm text-slate-300">{t.weather.height}</span>
        <div role="group" aria-labelledby="height-label" className="flex flex-wrap rounded-md border border-line p-0.5">
          {ALL_HEIGHTS.map((h) => (
            <button key={h} type="button" aria-pressed={height === h} onClick={() => void choose(h)}
              className={`rounded px-3 py-1.5 font-mono text-sm ${height === h ? "bg-cyan-glow/15 text-cyan-glow" : "text-slate-300 hover:text-white"}`}>
              {h} m
            </button>
          ))}
        </div>
        <span aria-live="polite" className="text-xs text-slate-400">{loading ? t.loading : ""}</span>
      </div>
      {height === 100 && <p className="mt-2 text-xs text-slate-400">100 m: {t.weather.reanalysis} · {t.weather.forecast}: {t.weather.heightUnsupported}</p>}
      {height === 200 && <p className="mt-2 text-xs text-amber-warn">{t.weather.unsupportedAll}</p>}
      {error && <p role="alert" className="mt-2 text-sm text-rose-warn">{error}</p>}
      <div className="mt-4 grid gap-5 xl:grid-cols-1">
        {sites.map((s) =>
          s.data ? (
            <SiteChart key={s.id} data={s.data} locale={locale} />
          ) : (
            <article key={s.id} className="wc-panel p-5 text-sm text-slate-400">{t.apiUnreachable}</article>
          ),
        )}
      </div>
      <p className="mt-3 text-xs text-slate-500">{t.weather.reanalysisNote}</p>
    </div>
  );
}
