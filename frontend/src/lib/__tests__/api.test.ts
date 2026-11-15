import { afterEach, describe, expect, it, vi } from "vitest";

import { cachedJson, clearApiCache, getJson } from "../api";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  clearApiCache();
});

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

describe("cachedJson (coalescing, short TTL)", () => {
  it("coalesces concurrent requests into one backend call", async () => {
    let resolve!: (r: Response) => void;
    const fetchMock = vi.fn().mockReturnValue(new Promise<Response>((r) => (resolve = r)));
    vi.stubGlobal("fetch", fetchMock);
    const calls = Array.from({ length: 50 }, () => cachedJson("/x"));
    resolve(Response.json({ a: 1 }));
    const results = await Promise.all(calls);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(results.every((r) => r.ok)).toBe(true);
  });

  it("reuses a success within the TTL and refetches after it", async () => {
    vi.stubEnv("WINDCAST_API_CACHE_SECONDS", "5");
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(Response.json({ a: 1 })));
    vi.stubGlobal("fetch", fetchMock);
    let t = 1_000_000;
    const now = () => t;
    await cachedJson("/x", now);
    t += 4_000;
    await cachedJson("/x", now);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    t += 2_000;
    await cachedJson("/x", now);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("never caches failures", async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response("", { status: 503 })));
    vi.stubGlobal("fetch", fetchMock);
    expect(await cachedJson("/x")).toEqual({ ok: false, error: "http_503" });
    expect(await cachedJson("/x")).toEqual({ ok: false, error: "http_503" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("can be disabled with WINDCAST_API_CACHE_SECONDS=0", async () => {
    vi.stubEnv("WINDCAST_API_CACHE_SECONDS", "0");
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(Response.json({ a: 1 })));
    vi.stubGlobal("fetch", fetchMock);
    await cachedJson("/x");
    await cachedJson("/x");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("keys by full path so different ranges never share data", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve(Response.json({ url })));
    vi.stubGlobal("fetch", fetchMock);
    const a = await cachedJson<{ url: string }>("/h?start=1");
    const b = await cachedJson<{ url: string }>("/h?start=2");
    expect(a.ok && b.ok && a.data.url !== b.data.url).toBe(true);
  });
});

describe("cachedJson ownership after eviction (review R2)", () => {
  function controlledFetch() {
    const pending = new Map<string, ((r: Response) => void)[]>();
    const fn = vi.fn().mockImplementation((url: string) => {
      const path = new URL(url).pathname;
      return new Promise<Response>((resolve) => pending.set(path, [...(pending.get(path) ?? []), resolve]));
    });
    const settle = (path: string, res: Response) => pending.get(path)!.shift()!(res);
    return { fn, settle };
  }

  async function evictThenReinsert(lateResponse: Response) {
    const { fn, settle } = controlledFetch();
    vi.stubGlobal("fetch", fn);
    let t = 1_000_000;
    const now = () => t;
    const a = cachedJson("/race", now); // entry A, in flight
    for (let i = 0; i < 256; i++) void cachedJson(`/fill-${i}`, now); // evicts A
    const b = cachedJson("/race", now); // replacement entry B, in flight
    settle("/race", lateResponse); // A completes late
    await a;
    t += 60_000; // well past any TTL: B is still in flight, so it must still be shared
    const c = cachedJson("/race", now); // must coalesce with B
    expect(c).toBe(b);
    expect(fn.mock.calls.filter(([u]) => String(u).endsWith("/race"))).toHaveLength(2);
    settle("/race", Response.json({ v: "b" }));
    expect(await c).toEqual({ ok: true, data: { v: "b" } });
  }

  it("a late failure of an evicted request does not delete its replacement", async () => {
    await evictThenReinsert(new Response("", { status: 503 }));
  });

  it("a late success of an evicted request does not change its replacement", async () => {
    await evictThenReinsert(Response.json({ v: "a" }));
  });
});
