import type { MetadataRoute } from "next";

import { indexingAllowed, publicUrl } from "@/lib/site";

// Evaluated per request so the same image serves a private pilot (disallow everything) and an
// approved public deployment (allow pages, never the data routes). See src/lib/site.ts.
export const dynamic = "force-dynamic";

export default function robots(): MetadataRoute.Robots {
  if (!indexingAllowed()) return { rules: { userAgent: "*", disallow: "/" } };
  const base = publicUrl()!;
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/api/", "/healthz"] },
    sitemap: new URL("/sitemap.xml", base).href,
    host: base.origin,
  };
}
