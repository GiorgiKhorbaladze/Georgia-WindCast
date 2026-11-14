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
  await expect(page.getByText("Stale", { exact: true }).first()).toBeVisible();
  // the reason depends on whether ingestion is enabled on the API; both are honest stale reasons
  await expect(
    page.getByText(/GSE has not published new data|GSE ingestion is disabled until reuse terms are confirmed/),
  ).toBeVisible();
  await expect(page.getByText("Fresh", { exact: true })).toHaveCount(0);
});

test("zero: 0.0 MW is shown as a real fresh reading, not as unavailable", async ({ page }) => {
  test.skip(scenario !== "zero", "zero scenario only");
  await page.goto("/");
  await expect(page.getByTestId("kpi-total-value")).toContainText("0.0");
  await expect(page.getByTestId("kpi-total-value")).toContainText("MW");
  await expect(page.getByTestId("kpi-total-value")).not.toContainText("Data unavailable");
  await expect(page.getByText("Fresh", { exact: true }).first()).toBeVisible();
});
