import { getGenerationHistory } from "@/lib/api";
import { publicError, publicJson } from "@/lib/routeErrors";

// Same-origin proxy so the browser never needs the backend address. The backend validates the
// range (timezone required, start < end, at most 31 days) and answers 422 otherwise.
const MAX_PARAM = 40;

export async function GET(request: Request) {
  const url = new URL(request.url);
  const start = url.searchParams.get("start");
  const end = url.searchParams.get("end");
  if ((start?.length ?? 0) > MAX_PARAM || (end?.length ?? 0) > MAX_PARAM) {
    return Response.json({ error: "invalid_request" }, { status: 400, headers: { "cache-control": "no-store" } });
  }
  const result = await getGenerationHistory(start, end);
  if (!result.ok) return publicError(result.error);
  return publicJson(result.data);
}
