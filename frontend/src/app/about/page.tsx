import { getSystemStatus } from "@/lib/api";
import { getI18n } from "@/lib/locale-server";

const SOURCES = [
  { name: "Georgian State Electrosystem (GSE) - national wind generation, 3-minute exports", url: "https://www.gse.com.ge" },
  { name: "Weather data by Open-Meteo.com (CC BY 4.0)", url: "https://open-meteo.com/" },
  { name: "DWD ICON global model (Deutscher Wetterdienst)", url: "https://www.dwd.de/" },
  { name: "ERA5 reanalysis (ECMWF / Copernicus Climate Change Service)", url: "https://cds.climate.copernicus.eu/" },
  { name: "Basemap: OpenFreeMap, © OpenMapTiles, data © OpenStreetMap contributors", url: "https://www.openstreetmap.org/copyright" },
];

export default async function AboutPage() {
  const [{ locale, t }, status] = await Promise.all([getI18n(), getSystemStatus()]);
  return (
    <article className="mx-auto flex max-w-3xl flex-col gap-5">
      <section className="wc-panel p-6 sm:p-8">
        <h1 className="text-2xl font-semibold text-white">{t.about.title}</h1>
        <div className="mt-5 space-y-4 leading-relaxed text-slate-300">
          {t.about.paragraphs.map((p) => <p key={p}>{p}</p>)}
        </div>
        <p className="mt-6 text-sm text-slate-400">{t.timezoneNote}</p>
      </section>
      <section className="wc-panel p-6 sm:p-8" aria-labelledby="sources-title">
        <h2 id="sources-title" className="wc-label">{t.about.sources}</h2>
        <ul className="mt-4 space-y-2 text-sm">
          {SOURCES.map((s) => (
            <li key={s.url}><a className="text-cyan-glow hover:underline" href={s.url} rel="noreferrer" target="_blank">{s.name}</a></li>
          ))}
        </ul>
      </section>
      {status.ok && (
        <section className="wc-panel p-6 sm:p-8" aria-labelledby="coords-title">
          <h2 id="coords-title" className="wc-label">{t.sites.title}</h2>
          <ul className="mt-4 space-y-4 text-sm">
            {status.data.sites.map((s) => (
              <li key={s.id} className="border-l-2 border-cyan-glow/40 pl-3">
                <div className="font-medium text-slate-100">{locale === "ka" ? s.name_ka : s.name_en}</div>
                <div className="font-mono text-xs text-slate-300">{s.latitude?.toFixed(5)}°N, {s.longitude?.toFixed(5)}°E · ±{s.coordinate_uncertainty_km} km</div>
                <div className="text-xs text-slate-400">{t.sites.coordinateSource}: {s.coordinate_source}</div>
                {s.coordinate_note && <div className="text-xs text-slate-400">{s.coordinate_note}</div>}
              </li>
            ))}
          </ul>
        </section>
      )}
    </article>
  );
}
