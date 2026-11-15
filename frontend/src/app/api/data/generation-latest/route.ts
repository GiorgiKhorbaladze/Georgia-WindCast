import { getGenerationLatest } from "@/lib/api";

// Same-origin refresh for open dashboards. The browser never contacts GSE or the backend directly.
export async function GET() {
  const result = await getGenerationLatest();
  if (!result.ok) {
    const status = result.error.startsWith("http_") ? Number(result.error.slice(5)) : 502;
    return Response.json({ error: result.error }, { status, headers: { "cache-control": "no-store" } });
  }
  return Response.json(result.data, { headers: { "cache-control": "no-store" } });
}
