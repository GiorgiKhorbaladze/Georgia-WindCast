// MapLibre GL v6 runs tile parsing in a module worker that it locates relative to its own
// import.meta.url. Bundling breaks that lookup, so the worker is served as a static file and
// passed to maplibregl.setWorkerUrl(). Runs before dev and build.
import { copyFileSync, mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const dist = dirname(require.resolve("maplibre-gl/package.json")) + "/dist";
const out = join(process.cwd(), "public", "vendor", "maplibre");
mkdirSync(out, { recursive: true });
copyFileSync(join(dist, "maplibre-gl-worker.mjs"), join(out, "maplibre-gl-worker.mjs"));
console.log("copied maplibre-gl-worker.mjs ->", out);
