import { getGenerationLatest } from "@/lib/api";
import { publicError, publicJson } from "@/lib/routeErrors";

// Same-origin refresh for open dashboards. The browser never contacts GSE or the backend directly.
export async function GET() {
  const result = await getGenerationLatest();
  if (!result.ok) return publicError(result.error);
  return publicJson(result.data);
}
