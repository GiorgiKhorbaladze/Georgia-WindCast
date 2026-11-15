import { getGenerationHistory } from "@/lib/api";

// Same-origin proxy so the browser never needs the backend address.
export async function GET(request: Request) {
  const url = new URL(request.url);
  const result = await getGenerationHistory(url.searchParams.get("start"), url.searchParams.get("end"));
  if (!result.ok) {
    const status = result.error.startsWith("http_") ? Number(result.error.slice(5)) : 502;
    return Response.json({ error: result.error }, { status });
  }
  return Response.json(result.data, { headers: { "cache-control": "no-store" } });
}
