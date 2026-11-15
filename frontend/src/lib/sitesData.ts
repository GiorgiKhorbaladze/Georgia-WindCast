import { getSiteWeather } from "./api";
import type { SiteSummary, SiteWeather } from "./types";

export const SITE_IDS = ["ruisi", "zemo-wind", "kartli-gori"] as const;

/** Fetch per-site weather server-side; a failed site yields null rather than invented data. */
export async function loadSites(height: number): Promise<{ id: string; site: SiteSummary | null; data: SiteWeather | null }[]> {
  return Promise.all(
    SITE_IDS.map(async (id) => {
      const r = await getSiteWeather(id, height);
      return { id, site: r.ok ? r.data.site : null, data: r.ok ? r.data : null };
    }),
  );
}
