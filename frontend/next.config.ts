import type { NextConfig } from "next";

// cacheComponents/partialPrefetching are intentionally not enabled: every data view in
// WindCast is request-time and locale-dependent. See docs/adr/0001-foundation-stack.md.
const TILE_HOST = "https://tiles.openfreemap.org";
const CSP = [
  "default-src 'self'",
  // Next.js inlines bootstrap scripts and styles; no third-party script origins are allowed.
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  `img-src 'self' data: blob: ${TILE_HOST}`,
  `connect-src 'self' ${TILE_HOST}`,
  "worker-src 'self' blob:",
  "font-src 'self' data:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
  // Isolate the browsing context from cross-origin openers (Nuclei dynamic scan, info finding).
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  { key: "X-Permitted-Cross-Domain-Policies", value: "none" },
  // Not set on purpose: COEP require-corp would block the cross-origin OpenFreeMap tiles, and
  // CORP same-origin could stop social platforms from loading the Open Graph image.
];

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
