import { getSystemStatus } from "@/lib/api";

// Read-only status for monitoring through the frontend (the API itself is not published in
// production). See docs/OPERATIONS.md section 3.
export async function GET() {
  const result = await getSystemStatus();
  if (!result.ok) {
    return Response.json({ error: result.error }, { status: 502, headers: { "cache-control": "no-store" } });
  }
  return Response.json(result.data, { headers: { "cache-control": "no-store" } });
}
