# ADR 0002 - UI data access, charts, map and animation policy

- Status: Proposed (issues #5, #6, #7)
- Date: 2026-11-14

## Decisions

1. **Browser → frontend only.** Pages render server-side from the API. Interactive views (range
   filters, height selection) call same-origin route handlers (`/api/data/*`), which proxy to the
   read-only API. The API needs no public exposure or CORS, and its address never reaches the
   browser.
2. **Apache ECharts** (canvas) for time series. Missing data is a `null` break, never a connecting
   line. Collection gaps are shaded amber; time before collection began is shaded neutrally, because
   it is not a source gap.
3. **MapLibre GL JS** with the free, keyless **OpenFreeMap "dark"** style (OpenMapTiles schema,
   OpenStreetMap data), attributed on the map. The MapLibre v6 worker is served from
   `/vendor/maplibre/` and copied at build time, because bundling breaks its `import.meta.url`
   lookup.
4. **Animation only where the data supports it.** Three point forecasts are not a wind field. Particles
   are drawn only within about 55 px of each site point, move downwind (bearing + 180°), scale with
   model speed, and carry a visible "not a spatial wind field" note. Animation can be paused, is
   off by default under `prefers-reduced-motion`, and is disabled without WebGL. A schematic SVG
   fallback then keeps the markers and values usable.
5. **Deterministic time formatting.** All UI times use one Asia/Tbilisi formatter built from
   numeric `Intl` parts (`DD.MM.YYYY HH:MM`). Node and browser ICU data differ for `ka-GE`, and
   locale-dependent formatting caused hydration mismatches.
6. **Heights:** the UI offers 10/80/100/120/180/200 m. Each series reports `supported`. Unsupported
   combinations (100 m forecast, 200 m anywhere) are labelled, never interpolated.
7. **Security headers:** a CSP restricted to self plus the tile host, `frame-ancestors 'none'`.

## Consequences

- One third-party runtime origin (tiles.openfreemap.org). If it is unavailable, the map keeps working
  without a basemap (markers, values, controls). CI blocks it in browser tests.
- No client-side caching layer is needed at the pilot scale; the API is cheap to call.
