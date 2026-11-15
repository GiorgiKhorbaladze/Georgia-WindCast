import { getSystemStatus } from "@/lib/api";
import { toPublicStatus } from "@/lib/publicStatus";
import { publicError, publicJson } from "@/lib/routeErrors";

// Public, read-only health and freshness summary. Only allow-listed fields leave the server (see
// src/lib/publicStatus.ts); operators read the full status on the host (docs/OPERATIONS.md).
export async function GET() {
  const result = await getSystemStatus();
  if (!result.ok) return publicError(result.error);
  return publicJson(toPublicStatus(result.data));
}
