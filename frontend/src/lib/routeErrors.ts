/**
 * Public error responses for the /api/data/* routes.
 *
 * Validation errors from the backend (4xx) keep their status and a short code. Everything else
 * (backend 5xx, timeouts, unreachable backend) becomes 502 with a generic code, so no internal
 * detail reaches anonymous visitors. Responses are never cached.
 */
export function publicError(error: string): Response {
  const upstream = error.startsWith("http_") ? Number(error.slice(5)) : NaN;
  const clientError = upstream >= 400 && upstream < 500 && upstream !== 429;
  const status = clientError ? upstream : 502;
  const code = clientError ? (upstream === 422 ? "invalid_request" : upstream === 404 ? "not_found" : "bad_request") : "upstream_unavailable";
  return Response.json({ error: code }, { status, headers: { "cache-control": "no-store" } });
}

export function publicJson(data: unknown): Response {
  return Response.json(data, { headers: { "cache-control": "no-store" } });
}
