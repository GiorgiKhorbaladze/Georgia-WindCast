import type { MetadataRoute } from "next";

import { indexingAllowed, PUBLIC_PATHS, publicUrl } from "@/lib/site";

// Empty until a public URL is approved and indexing is enabled (src/lib/site.ts).
export const dynamic = "force-dynamic";

export default function sitemap(): MetadataRoute.Sitemap {
  const base = publicUrl();
  if (!base || !indexingAllowed()) return [];
  return PUBLIC_PATHS.map((path) => ({
    url: new URL(path, base).href,
    changeFrequency: path === "/" ? "hourly" : "daily",
    priority: path === "/" ? 1 : 0.6,
  }));
}
