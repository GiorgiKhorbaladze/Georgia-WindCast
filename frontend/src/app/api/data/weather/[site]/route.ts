import { getSiteWeather } from "@/lib/api";
import { publicError, publicJson } from "@/lib/routeErrors";

const SITE_ID = /^[a-z0-9-]{1,32}$/;
const MAX_PARAM = 40;
const noStore = { "cache-control": "no-store" };

export async function GET(request: Request, { params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  if (!SITE_ID.test(site)) return Response.json({ error: "invalid_site" }, { status: 400, headers: noStore });
  const url = new URL(request.url);
  const height = Number(url.searchParams.get("height") ?? "120");
  if (!Number.isInteger(height)) return Response.json({ error: "invalid_height" }, { status: 400, headers: noStore });
  const start = url.searchParams.get("start");
  const end = url.searchParams.get("end");
  if ((start?.length ?? 0) > MAX_PARAM || (end?.length ?? 0) > MAX_PARAM) {
    return Response.json({ error: "invalid_request" }, { status: 400, headers: noStore });
  }
  const result = await getSiteWeather(site, height, start, end);
  if (!result.ok) return publicError(result.error);
  return publicJson(result.data);
}
