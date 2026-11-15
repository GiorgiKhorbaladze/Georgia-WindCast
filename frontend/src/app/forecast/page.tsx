import { ForecastExplorer } from "@/components/WeatherCharts";
import { ForecastCoverageBanner } from "@/components/ForecastCoverageBanner";
import { getWeatherOverview } from "@/lib/api";
import { getI18n } from "@/lib/locale-server";
import { loadSites } from "@/lib/sitesData";
import { pageMetadata } from "@/lib/pageMeta";

const DEFAULT_HEIGHT = 120;

export const generateMetadata = () => pageMetadata("forecast", "/forecast");

export default async function ForecastPage() {
  const [{ locale, t }, sites, overview] = await Promise.all([getI18n(), loadSites(DEFAULT_HEIGHT), getWeatherOverview()]);
  return (
    <div className="flex flex-col gap-5">
      <header>
        <h1 className="text-2xl font-semibold text-white">{t.weather.pageTitle}</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-400">{t.weather.pageNote} {t.weather.notMeasured}.</p>
      </header>
      <ForecastCoverageBanner overview={overview} t={t} locale={locale} />
      <ForecastExplorer initial={sites.map((s) => ({ id: s.id, data: s.data }))} locale={locale} initialHeight={DEFAULT_HEIGHT} />
    </div>
  );
}
