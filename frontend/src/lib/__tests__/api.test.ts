import { afterEach, describe, expect, it, vi } from "vitest";

import { getJson } from "../api";

afterEach(() => vi.unstubAllGlobals());

describe("getJson", () => {
  it("maps network failure to unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    expect(await getJson("/x")).toEqual({ ok: false, error: "unreachable" });
  });

  it("maps HTTP errors to an explicit error code", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 503 })));
    expect(await getJson("/x")).toEqual({ ok: false, error: "http_503" });
  });

  it("maps timeouts", async () => {
    const err = new DOMException("timed out", "TimeoutError");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(err));
    expect(await getJson("/x")).toEqual({ ok: false, error: "timeout" });
  });

  it("never caches backend responses", async () => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ a: 1 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await getJson("/x")).toEqual({ ok: true, data: { a: 1 } });
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ cache: "no-store" });
  });
});
