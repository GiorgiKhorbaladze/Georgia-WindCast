# UI screenshots at code `7c583ee6af2dbf06f89a4844bc27001a854e172d` (PR #19)

Captured 2026-11-15 by Playwright (Chromium, deviceScaleFactor 1) against a local production build
(`next start`) of that exact frontend code, with the API on the **E2E test seed**: real recorded GSE
values re-timestamped for testing, ingestion disabled. **Not live data; not launch screenshots.**
Map tiles are the real OpenFreeMap tiles.

Matrix: languages `ka`, `en` × widths `1440` (desktop) and `390`, `375`, `320` (mobile emulation,
touch) × pages `dashboard`, `history`, `forecast`, `map`. Full-page captures, colours quantised to
256 for size. File name: `<lang>-<width>-<page>.png`. No horizontal overflow in any of the 32
views (measured in the same run).

What to look for (review of PR #19):
- History charts: shaded areas carry no text; the legend under the chart explains "No data" and
  "Before collection".
- Dashboard "Now (model)": its own forecast state badge, valid time and model run.
- Navigation: mobile disclosure menu button in the header (closed in these captures; behaviour is
  covered by `frontend/e2e/public.spec.ts`).

Not covered here: Safari/iPhone and Firefox rendering, real devices, the public HTTPS host.
