import { expect, test } from "@playwright/test";

import { blockTiles, useLang } from "./helpers";

// Issue #16: an open dashboard must not keep showing "Fresh" indefinitely.
test("open dashboard: badge expires, failed refresh shows stale, recovery without reload", async ({ page }) => {
  await blockTiles(page);
  await useLang(page, "en");
  const initial = await (await page.request.get("/api/data/generation-latest")).json();
  test.skip(initial.freshness !== "fresh", "needs the seeded fresh scenario");

  await page.clock.install();
  await page.goto("/");
  const badge = page.getByTestId("kpi-freshness");
  const value = page.getByTestId("kpi-total-value");
  await expect(badge).toHaveText("Fresh");
  const shownValue = (await value.textContent())?.match(/\d+\.\d/)?.[0] ?? "";

  let mode: "fail" | "ok" = "fail";
  let advanced = 0;
  await page.route("**/api/data/generation-latest", (route) => {
    if (mode === "fail") {
      return route.fulfill({ status: 503, contentType: "application/json", body: '{"error":"http_503"}' });
    }
    const fakeNow = Date.now() + advanced;
    return route.fulfill({
      contentType: "application/json",
      body: JSON.stringify({
        ...initial,
        value_mw: 81.234,
        freshness: "fresh",
        reason: null,
        quality: "ACT",
        quality_flagged: false,
        source_observed_at: new Date(fakeNow - 60_000).toISOString(),
        retrieved_at: new Date(fakeNow - 20_000).toISOString(),
        fresh_until: new Date(fakeNow + 10 * 60_000).toISOString(),
        checked_at: new Date(fakeNow).toISOString(),
      }),
    });
  });

  // 1. Time passes beyond fresh_until while every refresh fails: no reload, badge must turn stale.
  advanced = Date.parse(initial.fresh_until) - Date.now() + 2 * 60_000;
  await page.clock.fastForward(advanced);
  await expect(badge).toHaveText("Stale");
  await expect(badge).not.toHaveText("Fresh");
  await expect(page.getByTestId("kpi-reason")).toContainText(/Refresh failed|expired/);
  await expect(value).toContainText(shownValue); // last value kept, explicitly not current

  // 2. The backend recovers: the next scheduled refresh restores a fresh reading in place.
  mode = "ok";
  await page.clock.fastForward(61_000);
  advanced += 61_000;
  await expect(value).toContainText("81.2");
  await expect(badge).toHaveText("Fresh");
  await expect(page.getByTestId("kpi-reason")).toHaveCount(0);
});
