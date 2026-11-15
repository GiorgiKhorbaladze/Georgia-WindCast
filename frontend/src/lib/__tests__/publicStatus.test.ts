import { describe, expect, it } from "vitest";

import { toPublicStatus } from "../publicStatus";
import { publicError } from "../routeErrors";
import type { SystemStatus } from "../types";

const FULL: SystemStatus = {
  generated_at: "2026-11-15T08:00:00Z",
  app_env: "production",
  worker: { state: "running", last_seen_at: "2026-11-15T07:59:50Z" },
  sources: [
    {
      id: "gse",
      state: "degraded",
      detail: "ConnectTimeout: admin.gse.com.ge:443 via 10.0.0.7",
      last_attempt_at: "2026-11-15T07:59:00Z",
      last_success_at: "2026-11-15T07:40:00Z",
      consecutive_failures: 2,
      backoff_until: "2026-11-15T08:02:00Z",
    },
  ],
  sites: [],
};

describe("toPublicStatus", () => {
  it("exposes exactly the allow-listed fields", () => {
    const pub = toPublicStatus(FULL);
    expect(Object.keys(pub).sort()).toEqual(["generated_at", "sites", "sources", "worker"]);
    expect(Object.keys(pub.worker).sort()).toEqual(["last_seen_at", "state"]);
    expect(pub.sources).toEqual([{ id: "gse", state: "degraded", last_success_at: "2026-11-15T07:40:00Z" }]);
  });

  it("never leaks operational errors, timing or environment", () => {
    const text = JSON.stringify(toPublicStatus(FULL));
    for (const secret of ["ConnectTimeout", "10.0.0.7", "backoff", "consecutive", "last_attempt", "production", "detail"]) {
      expect(text).not.toContain(secret);
    }
  });
});

describe("publicError", () => {
  it("keeps validation status with a generic code", async () => {
    const res = publicError("http_422");
    expect(res.status).toBe(422);
    expect(await res.json()).toEqual({ error: "invalid_request" });
  });

  it("maps backend failures, timeouts and rate limits to 502 without detail", async () => {
    for (const e of ["http_500", "http_503", "http_429", "timeout", "unreachable"]) {
      const res = publicError(e);
      expect(res.status).toBe(502);
      expect(await res.json()).toEqual({ error: "upstream_unavailable" });
      expect(res.headers.get("cache-control")).toBe("no-store");
    }
  });
});
