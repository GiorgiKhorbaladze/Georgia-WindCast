/**
 * Public site identity (issue #18). Read at request time on the server, so one image serves any
 * hostname: a private pilot sets nothing, a public deployment sets WINDCAST_PUBLIC_URL.
 *
 * - WINDCAST_PUBLIC_URL: the approved https origin (e.g. https://windcast.example.org). Enables
 *   absolute canonical/Open Graph URLs and the sitemap. Ignored unless it is a plain https origin.
 * - WINDCAST_PUBLIC_INDEXING=true: allow search engines. Default is noindex, so a pilot or an
 *   unapproved host never gets indexed by accident. Requires WINDCAST_PUBLIC_URL.
 */
export const SITE_NAME = "Georgia WindCast";
export const OG_IMAGE = { url: "/og-image.png", width: 1200, height: 630 } as const;
export const PUBLIC_PATHS = ["/", "/map", "/history", "/forecast", "/about"] as const;

export function publicUrl(env: Record<string, string | undefined> = process.env): URL | null {
  const raw = env.WINDCAST_PUBLIC_URL?.trim();
  if (!raw) return null;
  try {
    const url = new URL(raw);
    const plainOrigin = url.pathname === "/" && !url.search && !url.hash && !url.username && !url.password;
    return url.protocol === "https:" && plainOrigin ? new URL(url.origin) : null;
  } catch {
    return null;
  }
}

export function indexingAllowed(env: Record<string, string | undefined> = process.env): boolean {
  return env.WINDCAST_PUBLIC_INDEXING === "true" && publicUrl(env) !== null;
}
