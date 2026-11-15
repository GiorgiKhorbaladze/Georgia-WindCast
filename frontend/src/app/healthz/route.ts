// Frontend liveness for container health checks. Does not depend on the backend.
export function GET() {
  return Response.json({ status: "ok", service: "windcast-frontend" });
}
