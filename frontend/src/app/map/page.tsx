import { WindMap } from "@/components/WindMap";
import { getI18n } from "@/lib/locale-server";
import { loadSites } from "@/lib/sitesData";

const DEFAULT_HEIGHT = 120;

export default async function MapPage() {
  const [{ locale, t }, sites] = await Promise.all([getI18n(), loadSites(DEFAULT_HEIGHT)]);
  const usable = sites.filter((s) => s.site !== null).map((s) => ({ site: s.site!, weather: s.data }));
  return (
    <div className="flex flex-col gap-5">
      <header>
        <h1 className="text-2xl font-semibold text-white">{t.map.title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-400">{t.map.coverage}</p>
      </header>
      {usable.length ? (
        <WindMap initial={usable} initialHeight={DEFAULT_HEIGHT} locale={locale} />
      ) : (
        <p className="wc-panel p-6 text-slate-400">{t.apiUnreachable}</p>
      )}
    </div>
  );
}
