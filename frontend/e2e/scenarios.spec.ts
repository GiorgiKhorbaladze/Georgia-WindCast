import { expect, test } from "@playwright/test";

import { blockTiles, useLang } from "./helpers";

// Run with E2E_SCENARIO=stale|zero after seeding the matching scenario (see CI).
const scenario = process.env.E2E_SCENARIO;

test.beforeEach(async ({ page }) => {
  await blockTiles(page);
  await useLang(page, "en");
});

test("stale: last value kept but clearly marked stale, not live", async ({ page }) => {
  test.skip(scenario !== "stale", "stale scenario only");
  await page.goto("/");
  await expect(page.getByTestId("kpi-total-value")).toContainText("79.7");
  await expect(page.getByTestId("kpi-freshness")).toHaveText("Stale");
  // the reason depends on whether ingestion is enabled on the API; both are honest stale reasons
  await expect(
    page.getByText(/GSE has not published new data|GSE ingestion is disabled until reuse terms are confirmed/),
  ).toBeVisible();
  await expect(page.getByTestId("kpi-freshness")).not.toContainText("Fresh");
});

test("zero: 0.0 MW is shown as a real fresh reading, not as unavailable", async ({ page }) => {
  test.skip(scenario !== "zero", "zero scenario only");
  await page.goto("/");
  await expect(page.getByTestId("kpi-total-value")).toContainText("0.0");
  await expect(page.getByTestId("kpi-total-value")).toContainText("MW");
  await expect(page.getByTestId("kpi-total-value")).not.toContainText("Data unavailable");
  await expect(page.getByTestId("kpi-freshness")).toHaveText("Fresh");
});

test("expired forecast coverage: unavailable with reason, never negative hours", async ({ page }) => {
  test.skip(scenario !== "forecast-expired", "forecast-expired scenario only");
  await page.goto("/");
  const horizon = page.getByTestId("forecast-horizon");
  await expect(horizon).toContainText("Unavailable");
  await expect(horizon).toContainText("The latest forecast has expired");
  await expect(horizon).not.toContainText("-");
  for (const path of ["/forecast", "/map"]) {
    await page.goto(path);
    const banner = page.getByTestId("forecast-coverage");
    await expect(banner).toContainText("Unavailable");
    await expect(banner).toContainText("The latest forecast has expired");
  }
});

test("one site without forecast: aggregate not fresh, site shown with 0 hours", async ({ page }) => {
  test.skip(scenario !== "site-missing", "site-missing scenario only");
  await page.goto("/forecast");
  const banner = page.getByTestId("forecast-coverage");
  await expect(banner).toContainText("Stale");
  await expect(banner).not.toContainText("Fresh");
  await expect(banner).toContainText("incomplete for one or more sites");
  await expect(page.getByTestId("site-coverage")).toContainText("Zemo Wind: 0 hours ahead");
  await page.goto("/");
  await expect(page.getByTestId("forecast-horizon")).toContainText("incomplete for one or more sites");
  await expect(page.getByTestId("forecast-horizon")).not.toContainText("Fresh");
});
