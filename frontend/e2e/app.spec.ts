import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { blockTiles, collectErrors, horizontalOverflow, useLang } from "./helpers";

const PAGES = ["/", "/history", "/forecast", "/map", "/about"];

test.beforeEach(async ({ page }) => {
  await blockTiles(page);
});

for (const path of PAGES) {
  test(`${path} renders without errors, overflow or serious a11y violations`, async ({ page }) => {
    const errors = collectErrors(page);
    await useLang(page, "ka");
    await page.goto(path);
    await expect(page.locator("main")).toBeVisible();
    await page.waitForTimeout(800);
    expect(await horizontalOverflow(page)).toBeLessThanOrEqual(0);
    const axe = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa"])
      .exclude(".maplibregl-canvas")
      .analyze();
    const serious = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test("dashboard shows the national MW KPI with source time and quality, no per-site MW", async ({ page }) => {
  await useLang(page, "en");
  await page.goto("/");
  const kpi = page.getByTestId("kpi-total-value");
  await expect(kpi).toContainText("MW");
  await expect(kpi).toContainText("79.7"); // latest seeded real reading 79.686813
  await expect(page.getByText("Source timestamp")).toBeVisible();
  await expect(page.getByTestId("kpi-freshness")).toHaveText("Fresh");
  // MW appears only in the national KPI/history, never next to a site
  const sitesPanel = page.getByTestId("weather-now");
  await expect(sitesPanel).not.toContainText(/\d+(\.\d+)?\s*MW/);
  await expect(sitesPanel).toContainText("m/s");
  // the seeded 15-minute gap, plus a trailing gap if the seed has aged past the publication allowance
  await expect(page.getByTestId("history-summary")).toContainText(/Missing intervals: [12]/);
});

test("language switch works with the keyboard and persists", async ({ page, isMobile }) => {
  await useLang(page, "ka");
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("lang", "ka");
  const en = page.getByRole("button", { name: "English" }).first();
  await en.focus();
  await page.keyboard.press("Enter");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  if (isMobile) await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("navigation").getByRole("link", { name: "History" })).toBeVisible();
  await page.goto("/about");
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
});

test("skip link is the first focusable element", async ({ page, isMobile }) => {
  test.skip(isMobile, "keyboard navigation is checked on desktop");
  await page.goto("/");
  await page.keyboard.press("Tab");
  const focused = await page.evaluate(() => document.activeElement?.getAttribute("href"));
  expect(focused).toBe("#main");
});

test("history range filters reload data and reject invalid custom ranges", async ({ page }) => {
  await useLang(page, "en");
  await page.goto("/history");
  await expect(page.getByTestId("history-summary")).toContainText("14 actual readings");
  await page.getByRole("button", { name: "7 days" }).click();
  await expect(page.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByTestId("history-summary")).toContainText("14 actual readings");
  await page.getByLabel("From", { exact: true }).fill("2026-01-01T00:00");
  await page.getByLabel("To", { exact: true }).fill("2026-03-01T00:00");
  await page.getByRole("button", { name: "Show" }).click();
  await expect(page.getByText("Enter a valid range (max. 31 days).")).toBeVisible();
});

test("forecast page shows three model charts and honest unsupported heights", async ({ page }) => {
  await useLang(page, "en");
  await page.goto("/forecast");
  for (const id of ["ruisi", "zemo-wind", "kartli-gori"]) {
    await expect(page.getByTestId(`weather-${id}`).locator("[role=img]")).toBeVisible();
  }
  await expect(page.getByText("Model data, not an anemometer measurement").first()).toBeVisible();
  await page.getByRole("button", { name: "200 m" }).click();
  await expect(page.getByText("200 m - not available")).toBeVisible();
  await expect(page.getByText("This product provides no data at this height").first()).toBeVisible();
});

test("map: three markers, keyboard-selectable, time slider and pause", async ({ page }) => {
  await useLang(page, "en");
  await page.goto("/map");
  const markers = page.locator(".wc-marker");
  await expect(markers).toHaveCount(3);
  // Geography check: Ruisi lies west of Kartli/Gori; Zemo Wind (Kaspi) lies east and south of it.
  const box = async (id: string) => (await page.locator(`.wc-marker[data-site="${id}"]`).boundingBox())!;
  const [ruisi, zemo, kartli] = [await box("ruisi"), await box("zemo-wind"), await box("kartli-gori")];
  expect(ruisi.x).toBeLessThan(kartli.x);
  expect(zemo.x).toBeGreaterThan(kartli.x);
  expect(zemo.y).toBeGreaterThan(kartli.y);
  await markers.nth(2).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("map-detail")).toContainText("Kartli");
  await expect(page.getByTestId("map-detail")).toContainText("m/s");
  const before = await page.getByTestId("map-time").textContent();
  const slider = page.getByRole("slider");
  await slider.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page.getByTestId("map-time")).not.toHaveText(before ?? "");
  const anim = page.getByRole("button", { name: /Animation/ });
  const pressed = await anim.getAttribute("aria-pressed");
  await anim.click();
  await expect(anim).toHaveAttribute("aria-pressed", pressed === "true" ? "false" : "true");
  await expect(page.getByTestId("map-attribution")).toContainText("© OpenMapTiles");
  await expect(page.getByTestId("map-attribution")).toContainText("OpenStreetMap");
});

test("map falls back to a schematic without WebGL", async ({ page }) => {
  await page.addInitScript(() => {
    const orig = HTMLCanvasElement.prototype.getContext as (this: HTMLCanvasElement, ...a: unknown[]) => unknown;
    Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
      value(this: HTMLCanvasElement, type: string, ...rest: unknown[]) {
        if (type === "webgl" || type === "webgl2") return null;
        return orig.call(this, type, ...rest);
      },
    });
  });
  await useLang(page, "en");
  await page.goto("/map");
  await expect(page.getByTestId("map-fallback")).toBeVisible();
  await expect(page.getByText("WebGL unavailable")).toBeVisible();
});
