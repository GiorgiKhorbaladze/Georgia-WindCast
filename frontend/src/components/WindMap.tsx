"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import type { Map as MlMap, Marker } from "maplibre-gl";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { formatTbilisiMinute } from "@/lib/format";
import { getDictionary, type Locale } from "@/lib/i18n";
import type { SiteSummary, SiteWeather, WeatherPoint } from "@/lib/types";
import { compass, downwindBearing, formatSpeed, screenVector } from "@/lib/wind";

import { FORECAST_HEIGHTS } from "./WeatherCharts";

const STYLE_URL = "https://tiles.openfreemap.org/styles/dark";
const WORKER_URL = "/vendor/maplibre/maplibre-gl-worker.mjs"; // copied by scripts/copy-maplibre-worker.mjs
const ATTRIBUTION =
  '<a href="https://openfreemap.org" target="_blank" rel="noreferrer">OpenFreeMap</a> ' +
  '<a href="https://www.openmaptiles.org/" target="_blank" rel="noreferrer">© OpenMapTiles</a> ' +
  'Data from <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a>';

type SiteData = { site: SiteSummary; weather: SiteWeather | null };

const noopSubscribe = () => () => {};
let webglCache: boolean | null = null;
function clientWebGL(): boolean {
  if (webglCache === null) webglCache = hasWebGL();
  return webglCache;
}
function subscribeReducedMotion(cb: () => void) {
  const mq = window.matchMedia?.("(prefers-reduced-motion: reduce)");
  mq?.addEventListener("change", cb);
  return () => mq?.removeEventListener("change", cb);
}
function prefersReducedMotion(): boolean {
  return Boolean(window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
}

export function hasWebGL(): boolean {
  try {
    const c = document.createElement("canvas");
    return Boolean(c.getContext("webgl2") || c.getContext("webgl"));
  } catch {
    return false;
  }
}

function valueAt(points: WeatherPoint[] | undefined, t: number): WeatherPoint | null {
  if (!points) return null;
  return points.find((p) => Date.parse(p.t) === t) ?? null;
}

function arrowSvg(dir: number | null): string {
  if (dir === null) return "";
  const rot = downwindBearing(dir);
  return `<svg viewBox="-12 -12 24 24" width="22" height="22" aria-hidden="true" style="transform:rotate(${rot}deg)"><path d="M0,-10 L6,6 L0,2 L-6,6 Z" fill="currentColor"/></svg>`;
}

function speedColor(v: number | null): string {
  if (v === null) return "#64748b";
  if (v < 4) return "#5eead4";
  if (v < 8) return "#22d3ee";
  if (v < 12) return "#a78bfa";
  return "#f0abfc";
}

export function WindMap({
  initial,
  initialHeight,
  locale,
}: {
  initial: SiteData[];
  initialHeight: number;
  locale: Locale;
}) {
  const t = getDictionary(locale);
  const [height, setHeight] = useState(initialHeight);
  const [sites, setSites] = useState(initial);
  const webgl = useSyncExternalStore(noopSubscribe, clientWebGL, () => null);
  const reducedMotion = useSyncExternalStore(subscribeReducedMotion, prefersReducedMotion, () => true);
  const [mapReady, setMapReady] = useState(false);
  const [selected, setSelected] = useState<string>(initial[0]?.site.id ?? "");
  const [playing, setPlaying] = useState(false);
  const [animateChoice, setAnimate] = useState<boolean | null>(null);
  const animate = animateChoice ?? !reducedMotion;
  const [loading, setLoading] = useState(false);

  const times = useMemo(() => {
    const set = new Set<number>();
    for (const s of sites) for (const p of s.weather?.forecast.points ?? []) set.add(Date.parse(p.t));
    return [...set].sort((a, b) => a - b);
  }, [sites]);
  const [timeIdx, setTimeIdx] = useState(0);
  const currentT = times[Math.min(timeIdx, Math.max(0, times.length - 1))];

  const current = useMemo(
    () =>
      sites.map((s) => ({
        ...s,
        value: currentT !== undefined ? valueAt(s.weather?.forecast.points, currentT) : null,
      })),
    [sites, currentT],
  );

  const container = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const map = useRef<MlMap | null>(null);
  const markers = useRef<Record<string, { marker: Marker; el: HTMLButtonElement }>>({});
  const currentRef = useRef(current);
  useEffect(() => {
    currentRef.current = current;
  }, [current]);

  // Map creation
  useEffect(() => {
    if (!webgl || !container.current) return;
    let cancelled = false;
    (async () => {
      const maplibregl = await import("maplibre-gl");
      if (cancelled || !container.current) return;
      await maplibregl.setWorkerUrl(WORKER_URL);
      if (cancelled || !container.current) return;
      const lngs = initial.map((s) => s.site.longitude ?? 44);
      const lats = initial.map((s) => s.site.latitude ?? 42);
      const m = new maplibregl.Map({
        container: container.current,
        style: STYLE_URL,
        bounds: [
          [Math.min(...lngs) - 0.35, Math.min(...lats) - 0.2],
          [Math.max(...lngs) + 0.35, Math.max(...lats) + 0.2],
        ],
        maxBounds: [[38.5, 40.0], [47.5, 44.2]],
        attributionControl: { compact: false, customAttribution: ATTRIBUTION },
        cooperativeGestures: false,
      });
      m.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
      m.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "top-left");
      for (const s of initial) {
        if (s.site.latitude === null || s.site.longitude === null) continue;
        const el = document.createElement("button");
        el.type = "button";
        el.className = "wc-marker";
        el.dataset.site = s.site.id;
        el.setAttribute("aria-label", locale === "ka" ? s.site.name_ka : s.site.name_en);
        el.textContent = "-";
        el.addEventListener("click", () => setSelected(s.site.id));
        const marker = new maplibregl.Marker({ element: el, anchor: "center" })
          .setLngLat([s.site.longitude, s.site.latitude])
          .addTo(m);
        markers.current[s.site.id] = { marker, el };
      }
      m.on("load", () => setMapReady(true));
      map.current = m;
    })();
    return () => {
      cancelled = true;
      map.current?.remove();
      map.current = null;
      markers.current = {};
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the map is created once per data set
  }, [webgl, initial]);

  // Marker contents follow time/height/selection
  useEffect(() => {
    for (const c of current) {
      const entry = markers.current[c.site.id];
      if (!entry) continue;
      const v = c.value;
      const name = locale === "ka" ? c.site.name_ka : c.site.name_en;
      const sp = formatSpeed(v?.speed_ms);
      entry.el.style.setProperty("--wc-color", speedColor(v?.speed_ms ?? null));
      entry.el.setAttribute("aria-pressed", String(selected === c.site.id));
      entry.el.setAttribute(
        "aria-label",
        `${name}: ${sp ? `${sp} m/s` : t.unavailable}${v?.direction_deg != null ? `, ${t.weather.from} ${compass(v.direction_deg, locale)}` : ""}`,
      );
      entry.el.innerHTML = `${arrowSvg(v?.direction_deg ?? null)}<span>${sp ?? "-"}</span>`;
    }
  }, [current, selected, locale, t, mapReady]);

  // Particle animation around site points only
  useEffect(() => {
    if (!webgl || !animate || !canvas.current) {
      const ctx = canvas.current?.getContext("2d");
      ctx?.clearRect(0, 0, canvas.current?.width ?? 0, canvas.current?.height ?? 0);
      return;
    }
    const cv = canvas.current;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    type P = { site: string; x: number; y: number; age: number; life: number };
    const parts: P[] = [];
    let raf = 0;
    const R = 54;
    const frame = () => {
      const m = map.current;
      const dpr = window.devicePixelRatio || 1;
      const w = cv.clientWidth, h = cv.clientHeight;
      if (cv.width !== w * dpr || cv.height !== h * dpr) {
        cv.width = w * dpr;
        cv.height = h * dpr;
      }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.globalCompositeOperation = "destination-out";
      ctx.fillStyle = "rgba(0,0,0,0.18)";
      ctx.fillRect(0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";
      if (m) {
        for (const c of currentRef.current) {
          const v = c.value;
          if (!v || v.speed_ms === null || v.direction_deg === null || c.site.latitude === null || c.site.longitude === null) continue;
          const center = m.project([c.site.longitude, c.site.latitude]);
          const count = parts.filter((p) => p.site === c.site.id).length;
          for (let i = count; i < 70; i++) {
            const a = Math.random() * Math.PI * 2, r = Math.sqrt(Math.random()) * R;
            parts.push({ site: c.site.id, x: center.x + Math.cos(a) * r, y: center.y + Math.sin(a) * r, age: 0, life: 40 + Math.random() * 60 });
          }
          const { dx, dy } = screenVector(v.direction_deg);
          const step = 0.25 + Math.min(v.speed_ms, 25) * 0.09;
          ctx.strokeStyle = speedColor(v.speed_ms);
          ctx.lineWidth = 1.2;
          for (const p of parts) {
            if (p.site !== c.site.id) continue;
            const ox = p.x, oy = p.y;
            p.x += dx * step;
            p.y += dy * step;
            p.age++;
            const dist = Math.hypot(p.x - center.x, p.y - center.y);
            ctx.globalAlpha = Math.max(0, 0.65 * (1 - p.age / p.life) * (1 - dist / (R * 1.6)));
            ctx.beginPath();
            ctx.moveTo(ox, oy);
            ctx.lineTo(p.x, p.y);
            ctx.stroke();
            if (p.age > p.life || dist > R * 1.6) p.age = Infinity;
          }
        }
      }
      for (let i = parts.length - 1; i >= 0; i--) if (parts[i].age === Infinity) parts.splice(i, 1);
      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(frame);
    };
    raf = requestAnimationFrame(frame);
    return () => cancelAnimationFrame(raf);
  }, [webgl, animate, mapReady]);

  // Time playback
  useEffect(() => {
    if (!playing || times.length < 2) return;
    const id = window.setInterval(() => setTimeIdx((i) => (i + 1) % times.length), 900);
    return () => window.clearInterval(id);
  }, [playing, times.length]);

  const chooseHeight = useCallback(
    async (h: number) => {
      setHeight(h);
      setLoading(true);
      try {
        const next = await Promise.all(
          sites.map(async (s) => {
            const res = await fetch(`/api/data/weather/${s.site.id}?height=${h}`, { cache: "no-store" });
            return { site: s.site, weather: res.ok ? ((await res.json()) as SiteWeather) : null };
          }),
        );
        setSites(next);
      } finally {
        setLoading(false);
      }
    },
    [sites],
  );

  const sel = current.find((c) => c.site.id === selected);
  const runAt = sites.find((s) => s.weather?.forecast.run_at)?.weather?.forecast.run_at ?? null;

  return (
    <div className="grid gap-5 lg:grid-cols-12">
      <div className="lg:col-span-8">
        <div className="wc-panel relative overflow-hidden p-0">
          {webgl === false ? (
            <Schematic current={current} locale={locale} selected={selected} onSelect={setSelected} />
          ) : (
            <div className="relative h-[60vh] min-h-[360px] w-full">
              <div ref={container} className="h-full w-full" data-testid="map-canvas" />
              <canvas ref={canvas} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true" />
            </div>
          )}
        </div>
        <p className="mt-2 text-xs text-slate-400">
          {webgl === false ? t.map.webglFallback : t.map.coverage} {t.weather.notMeasured}.
        </p>

        <div className="wc-panel mt-4 flex flex-col gap-4 p-4">
          <div className="flex flex-wrap items-center gap-3">
            <span id="map-height" className="text-sm text-slate-300">{t.weather.height}</span>
            <div role="group" aria-labelledby="map-height" className="flex rounded-md border border-line p-0.5">
              {FORECAST_HEIGHTS.map((h) => (
                <button key={h} type="button" aria-pressed={height === h} onClick={() => void chooseHeight(h)}
                  className={`rounded px-3 py-1.5 font-mono text-sm ${height === h ? "bg-cyan-glow/15 text-cyan-glow" : "text-slate-300 hover:text-white"}`}>
                  {h} m
                </button>
              ))}
            </div>
            <span className="text-xs text-slate-400">100 / 200 m: {t.weather.heightUnsupported}</span>
            <button type="button" aria-pressed={animate} onClick={() => setAnimate(!animate)}
              className="ml-auto rounded-md border border-line px-3 py-1.5 text-sm text-slate-300 hover:text-white">
              {t.map.animation}: {animate ? t.map.animationOn : t.map.animationOff}
            </button>
          </div>
          {times.length > 0 ? (
            <div className="flex flex-wrap items-center gap-3">
              <button type="button" onClick={() => setPlaying((p) => !p)} aria-pressed={playing}
                className="rounded-md border border-cyan-glow/40 px-3 py-1.5 text-sm text-cyan-glow hover:bg-cyan-glow/10">
                {playing ? t.map.pause : t.map.play}
              </button>
              <label className="flex min-w-[220px] flex-1 flex-col gap-1 text-xs text-slate-400">
                <span>{t.map.time}: <span className="font-mono text-slate-100" data-testid="map-time">{currentT !== undefined ? formatTbilisiMinute(currentT) : "-"}</span></span>
                <input type="range" min={0} max={Math.max(0, times.length - 1)} value={Math.min(timeIdx, times.length - 1)}
                  onChange={(e) => { setPlaying(false); setTimeIdx(Number(e.target.value)); }}
                  aria-valuetext={currentT !== undefined ? (formatTbilisiMinute(currentT) ?? "") : ""}
                  className="accent-cyan-400" />
              </label>
              <span className="text-xs text-slate-400">{t.weather.run}: {runAt ? formatTbilisiMinute(runAt) : "-"}</span>
            </div>
          ) : (
            <p className="text-sm text-slate-400">{t.weather.noData}</p>
          )}
          <span aria-live="polite" className="text-xs text-slate-400">{loading ? t.loading : ""}</span>
        </div>
      </div>

      <aside className="flex flex-col gap-4 lg:col-span-4">
        {sel && <SiteDetail data={sel} locale={locale} height={height} />}
        <section className="wc-panel p-4" aria-labelledby="map-list">
          <h2 id="map-list" className="wc-label">{t.map.list}</h2>
          <ul className="mt-3 space-y-2">
            {current.map((c) => (
              <li key={c.site.id}>
                <button type="button" onClick={() => setSelected(c.site.id)} aria-pressed={selected === c.site.id}
                  className={`flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left ${selected === c.site.id ? "border-cyan-glow/50 bg-cyan-glow/5" : "border-line bg-ink-900/60"}`}>
                  <span className="text-sm text-slate-100">{locale === "ka" ? c.site.name_ka : c.site.name_en}</span>
                  <span className="flex items-center gap-2 font-mono text-sm" style={{ color: speedColor(c.value?.speed_ms ?? null) }}>
                    <span dangerouslySetInnerHTML={{ __html: arrowSvg(c.value?.direction_deg ?? null) }} />
                    {formatSpeed(c.value?.speed_ms) ?? "-"} <span className="text-xs text-slate-400">m/s</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>
      </aside>
    </div>
  );
}

function SiteDetail({ data, locale, height }: { data: SiteData & { value: WeatherPoint | null }; locale: Locale; height: number }) {
  const t = getDictionary(locale);
  const v = data.value;
  return (
    <section className="wc-panel p-4" aria-live="polite" data-testid="map-detail">
      <h2 className="text-base font-semibold text-white">{locale === "ka" ? data.site.name_ka : data.site.name_en}</h2>
      <p className="text-xs text-slate-400">
        {locale === "ka" ? (data.site.municipality_ka ?? data.site.municipality_en) : data.site.municipality_en} ·{" "}
        {locale === "ka" ? (data.site.status_ka ?? data.site.status_en) : data.site.status_en}
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-3 text-sm">
        <div><dt className="text-xs text-slate-400">{t.weather.speed} ({height} m)</dt><dd className="font-mono text-2xl text-white">{formatSpeed(v?.speed_ms) ?? "-"} <span className="text-sm text-cyan-glow">m/s</span></dd></div>
        <div><dt className="text-xs text-slate-400">{t.weather.direction}</dt><dd className="font-mono text-slate-100">{v?.direction_deg != null ? `${t.weather.from} ${compass(v.direction_deg, locale)} · ${Math.round(v.direction_deg)}°` : "-"}</dd></div>
        <div><dt className="text-xs text-slate-400">{t.weather.validTime}</dt><dd className="text-slate-200">{v ? formatTbilisiMinute(v.t) : "-"}</dd></div>
        <div><dt className="text-xs text-slate-400">{t.weather.model}</dt><dd className="text-slate-200">{data.weather?.forecast.model_label ?? "-"}</dd></div>
      </dl>
      <p className="mt-3 text-xs text-slate-400">{t.weather.notMeasured}.</p>
      <p className="mt-2 text-xs text-slate-400">
        {t.sites.coordinateSource}: {data.site.coordinate_source}
        {data.site.coordinate_uncertainty_km != null && ` · ${t.sites.uncertainty} ≈ ${data.site.coordinate_uncertainty_km} km`}
      </p>
    </section>
  );
}

function Schematic({
  current,
  locale,
  selected,
  onSelect,
}: {
  current: (SiteData & { value: WeatherPoint | null })[];
  locale: Locale;
  selected: string;
  onSelect: (id: string) => void;
}) {
  const pts = current.filter((c) => c.site.latitude !== null && c.site.longitude !== null);
  const lons = pts.map((c) => c.site.longitude as number);
  const lats = pts.map((c) => c.site.latitude as number);
  const [x0, x1, y0, y1] = [Math.min(...lons) - 0.15, Math.max(...lons) + 0.15, Math.min(...lats) - 0.1, Math.max(...lats) + 0.1];
  const W = 640, H = 360;
  const px = (lon: number) => ((lon - x0) / (x1 - x0)) * W;
  const py = (lat: number) => H - ((lat - y0) / (y1 - y0)) * H;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-[360px] w-full bg-ink-900" role="group" aria-label="schematic map" data-testid="map-fallback">
      {pts.map((c) => {
        const x = px(c.site.longitude as number), y = py(c.site.latitude as number);
        const dir = c.value?.direction_deg;
        return (
          <g key={c.site.id} transform={`translate(${x},${y})`} role="button" tabIndex={0} aria-pressed={selected === c.site.id}
            aria-label={locale === "ka" ? c.site.name_ka : c.site.name_en}
            onClick={() => onSelect(c.site.id)} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && onSelect(c.site.id)}>
            <circle r="16" fill="rgba(34,211,238,0.12)" stroke={speedColor(c.value?.speed_ms ?? null)} />
            {dir != null && <path d="M0,-10 L6,6 L0,2 L-6,6 Z" fill={speedColor(c.value?.speed_ms ?? null)} transform={`rotate(${downwindBearing(dir)})`} />}
            <text y="32" textAnchor="middle" fill="#cbd5e1" fontSize="12">{locale === "ka" ? c.site.name_ka : c.site.name_en}</text>
            <text y="48" textAnchor="middle" fill="#22d3ee" fontSize="12" fontFamily="monospace">{formatSpeed(c.value?.speed_ms) ?? "-"} m/s</text>
          </g>
        );
      })}
    </svg>
  );
}
