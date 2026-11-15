import { StatusBadge } from "@/components/StatusBadge";
import { formatTbilisiMinute } from "@/lib/format";
import type { Dictionary } from "@/lib/i18n";
import { freshnessTone } from "@/lib/status";
import type { ApiResult, WeatherOverview } from "@/lib/types";

/** States forecast coverage honestly on the forecast and map pages (issue #16). */
export function ForecastCoverageBanner({
  overview,
  t,
  locale,
}: {
  overview: ApiResult<WeatherOverview>;
  t: Dictionary;
  locale: "ka" | "en";
}) {
  if (!overview.ok) {
    return <p className="wc-panel p-3 text-sm text-rose-warn" data-testid="forecast-coverage">{t.apiUnreachable}</p>;
  }
  const w = overview.data;
  const reason = w.forecast_reason ? (t.weather.coverage[w.forecast_reason] ?? w.forecast_reason) : null;
  return (
    <div className="wc-panel flex flex-wrap items-center gap-x-4 gap-y-2 p-3 text-sm" data-testid="forecast-coverage">
      <StatusBadge tone={freshnessTone(w.forecast_state)}>{t.freshness[w.forecast_state]}</StatusBadge>
      {w.forecast_state !== "unavailable" && (
        <span className="text-slate-300">
          {Math.max(0, Math.round(w.forecast_forward_hours ?? 0))} {t.weather.forwardHours}
        </span>
      )}
      {w.forecast_run_at && (
        <span className="text-slate-400">{t.weather.run}: {formatTbilisiMinute(w.forecast_run_at)}</span>
      )}
      {reason && <span className="text-amber-warn">{reason}</span>}
      {w.site_coverage && w.site_coverage.length > 0 && (
        <ul className="flex w-full flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400" data-testid="site-coverage">
          {w.site_coverage.map((c) => {
            const site = w.sites.find((s) => s.id === c.site_id);
            const name = site ? (locale === "ka" ? site.name_ka : site.name_en) : c.site_id;
            return (
              <li key={c.site_id} className={c.forward_hours > 0 && !c.missing_hours ? "" : "text-amber-warn"}>
                {name}: {Math.round(c.forward_hours)} {t.weather.forwardHours}
                {c.missing_hours ? ` · ${t.weather.missingHours(c.missing_hours)}` : ""}
              </li>
            );
          })}
        </ul>
      )}
      <p className="w-full text-xs text-slate-400">{t.weather.coverageNote}</p>
    </div>
  );
}
