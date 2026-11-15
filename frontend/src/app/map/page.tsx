import { WindMap } from "@/components/WindMap";
import { ForecastCoverageBanner } from "@/components/ForecastCoverageBanner";
import { getWeatherOverview } from "@/lib/api";
import { getI18n } from "@/lib/locale-server";
import { loadSites } from "@/lib/sitesData";
import { pageMetadata } from "@/lib/pageMeta";

const DEFAULT_HEIGHT = 120;

export const generateMetadata = () => pageMetadata("map", "/map");

export default async function MapPage() {
  const [{ locale, t }, sites, overview] = await Promise.all([getI18n(), loadSites(DEFAULT_HEIGHT), getWeatherOverview()]);
  const usable = sites.filter((s) => s.site !== null).map((s) => ({ site: s.site!, weather: s.data }));
  return (
    <div className="flex flex-col gap-5">
      <header>
        <h1 className="text-2xl font-semibold text-white">{t.map.title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-400">{t.map.coverage}</p>
      </header>
      <ForecastCoverageBanner overview={overview} t={t} locale={locale} />
      {usable.length ? (
        <WindMap initial={usable} initialHeight={DEFAULT_HEIGHT} locale={locale} />
      ) : (
        <p className="wc-panel p-6 text-slate-400">{t.apiUnreachable}</p>
      )}
    </div>
  );
}
