import { ForecastExplorer } from "@/components/WeatherCharts";
import { getI18n } from "@/lib/locale-server";
import { loadSites } from "@/lib/sitesData";

const DEFAULT_HEIGHT = 120;

export default async function ForecastPage() {
  const [{ locale, t }, sites] = await Promise.all([getI18n(), loadSites(DEFAULT_HEIGHT)]);
  return (
    <div className="flex flex-col gap-5">
      <header>
        <h1 className="text-2xl font-semibold text-white">{t.weather.pageTitle}</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-400">{t.weather.pageNote} {t.weather.notMeasured}.</p>
      </header>
      <ForecastExplorer initial={sites.map((s) => ({ id: s.id, data: s.data }))} locale={locale} initialHeight={DEFAULT_HEIGHT} />
    </div>
  );
}
