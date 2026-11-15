import { getSiteWeather } from "@/lib/api";

const SITE_ID = /^[a-z0-9-]{1,32}$/;

export async function GET(request: Request, { params }: { params: Promise<{ site: string }> }) {
  const { site } = await params;
  if (!SITE_ID.test(site)) return Response.json({ error: "invalid_site" }, { status: 400 });
  const url = new URL(request.url);
  const height = Number(url.searchParams.get("height") ?? "120");
  if (!Number.isInteger(height)) return Response.json({ error: "invalid_height" }, { status: 400 });
  const result = await getSiteWeather(site, height, url.searchParams.get("start"), url.searchParams.get("end"));
  if (!result.ok) {
    const status = result.error.startsWith("http_") ? Number(result.error.slice(5)) : 502;
    return Response.json({ error: result.error }, { status });
  }
  return Response.json(result.data, { headers: { "cache-control": "no-store" } });
}
