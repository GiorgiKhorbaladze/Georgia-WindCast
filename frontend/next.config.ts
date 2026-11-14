import type { NextConfig } from "next";

// cacheComponents/partialPrefetching are intentionally not enabled: every data view in
// WindCast is request-time and locale-dependent. See docs/adr/0001-foundation-stack.md.
const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
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
