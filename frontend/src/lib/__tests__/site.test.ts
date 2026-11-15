import { describe, expect, it } from "vitest";

import { indexingAllowed, publicUrl } from "../site";

describe("publicUrl", () => {
  it("is unset by default", () => {
    expect(publicUrl({})).toBeNull();
  });

  it("accepts a plain https origin", () => {
    expect(publicUrl({ WINDCAST_PUBLIC_URL: "https://windcast.example.org" })?.href).toBe("https://windcast.example.org/");
    expect(publicUrl({ WINDCAST_PUBLIC_URL: "https://windcast.example.org/" })?.origin).toBe("https://windcast.example.org");
  });

  it("rejects http, paths, credentials and garbage", () => {
    for (const v of ["http://windcast.example.org", "https://x.org/app", "https://u:p@x.org", "https://x.org/?a=1", "not a url"]) {
      expect(publicUrl({ WINDCAST_PUBLIC_URL: v })).toBeNull();
    }
  });
});

describe("indexingAllowed", () => {
  it("is off unless explicitly enabled with a valid public URL", () => {
    expect(indexingAllowed({})).toBe(false);
    expect(indexingAllowed({ WINDCAST_PUBLIC_INDEXING: "true" })).toBe(false);
    expect(indexingAllowed({ WINDCAST_PUBLIC_URL: "https://x.org" })).toBe(false);
    expect(indexingAllowed({ WINDCAST_PUBLIC_URL: "https://x.org", WINDCAST_PUBLIC_INDEXING: "true" })).toBe(true);
  });
});
