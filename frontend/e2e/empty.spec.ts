import { expect, test } from "@playwright/test";

import { blockTiles, useLang } from "./helpers";

// Runs only when E2E_EMPTY=1: a stack with no data must show explicit unavailable states.
test.skip(process.env.E2E_EMPTY !== "1", "empty-state run only");

test("no data: explicit unavailable states and no invented numbers", async ({ page }) => {
  await blockTiles(page);
  await useLang(page, "en");
  await page.goto("/");
  await expect(page.getByTestId("kpi-total-value")).toHaveText("Data unavailable");
  await expect(page.getByTestId("kpi-total-value")).not.toContainText("MW");
  const horizon = page.getByTestId("forecast-horizon");
  await expect(horizon).toContainText("Unavailable");
  await expect(horizon).toContainText("No model forecast has been received yet.");
});
