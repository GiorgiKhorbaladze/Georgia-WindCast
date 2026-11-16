import { expect, test } from "@playwright/test";

import { blockTiles, useLang } from "./helpers";

// Issue #18: public presentation, link-preview metadata, safe public contracts, mobile menu.
test.beforeEach(async ({ page }) => {
  await blockTiles(page);
});

test("link-preview metadata is present in the visitor's language", async ({ page }) => {
  await useLang(page, "ka");
  await page.goto("/");
  await expect(page).toHaveTitle(/Georgia WindCast/);
  const og = (p: string) => page.locator(`meta[property="og:${p}"]`).first();
  await expect(og("title")).toHaveAttribute("content", /Georgia WindCast/);
  await expect(og("locale")).toHaveAttribute("content", "ka_GE");
  await expect(og("image")).toHaveAttribute("content", /\/og-image\.png$/);
  await expect(og("image:width")).toHaveAttribute("content", "1200");
  await expect(page.locator('meta[name="twitter:card"]')).toHaveAttribute("content", "summary_large_image");
  await expect(page.locator('meta[name="description"]')).toHaveAttribute("content", /GSE/);

  await useLang(page, "en");
  await page.goto("/history");
  await expect(page).toHaveTitle("Generation history · Georgia WindCast");
  await expect(og("locale")).toHaveAttribute("content", "en_US");
});

test("unapproved deployments are not indexed", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.locator('meta[name="robots"]')).toHaveAttribute("content", /noindex/);
  const robots = await (await request.get("/robots.txt")).text();
  expect(robots).toMatch(/Disallow: \//);
  const sitemap = await (await request.get("/sitemap.xml")).text();
  expect(sitemap).not.toContain("<loc>");
});

test("social card and icons are served", async ({ request }) => {
  for (const [path, type] of [
    ["/og-image.png", "image/png"],
    ["/icon.svg", "image/svg+xml"],
    ["/apple-icon.png", "image/png"],
    ["/icon-192.png", "image/png"],
    ["/manifest.webmanifest", "application/manifest+json"],
  ]) {
    const res = await request.get(path);
    expect(res.status(), path).toBe(200);
    expect(res.headers()["content-type"], path).toContain(type);
  }
});

test("public status exposes only allow-listed fields", async ({ request }) => {
  const res = await request.get("/api/data/status");
  expect(res.status()).toBe(200);
  const body = await res.json();
  expect(Object.keys(body).sort()).toEqual(["generated_at", "sites", "sources", "worker"]);
  for (const s of body.sources) expect(Object.keys(s).sort()).toEqual(["id", "last_success_at", "state"]);
  const text = JSON.stringify(body);
  for (const k of ["detail", "backoff_until", "consecutive_failures", "last_attempt_at", "app_env"]) expect(text).not.toContain(k);
});

test("data routes return generic errors for invalid input", async ({ request }) => {
  const bad = await request.get("/api/data/generation-history?start=2026-01-01T00:00:00Z&end=2026-03-01T00:00:00Z");
  expect(bad.status()).toBe(422);
  expect(await bad.json()).toEqual({ error: "invalid_request" });
  const long = await request.get(`/api/data/generation-history?start=${"9".repeat(200)}`);
  expect(long.status()).toBe(400);
});

test("security headers are set on pages", async ({ request }) => {
  const res = await request.get("/");
  const h = res.headers();
  expect(h["content-security-policy"]).toContain("frame-ancestors 'none'");
  expect(h["x-content-type-options"]).toBe("nosniff");
  expect(h["referrer-policy"]).toBe("strict-origin-when-cross-origin");
  expect(h["x-powered-by"]).toBeUndefined();
  expect(h["cross-origin-opener-policy"]).toBe("same-origin");
  expect(h["x-permitted-cross-domain-policies"]).toBe("none");
});

test("about page states independence and privacy", async ({ page }) => {
  await useLang(page, "en");
  await page.goto("/about");
  await expect(page.getByTestId("independence")).toContainText("Not an official service");
  await expect(page.getByRole("heading", { name: "Privacy" })).toBeVisible();
  await expect(page.locator("footer")).toContainText("Independent informational project");
});

test("mobile menu is a keyboard-operable disclosure", async ({ page, isMobile }) => {
  test.skip(!isMobile, "the disclosure menu exists below the lg breakpoint");
  await useLang(page, "en");
  await page.goto("/");
  const toggle = page.getByRole("button", { name: "Open menu" });
  await expect(toggle).toHaveAttribute("aria-expanded", "false");
  const forecast = page.getByRole("navigation").getByRole("link", { name: "Forecast" });
  await expect(forecast).toBeHidden();
  await toggle.click();
  await expect(page.getByRole("button", { name: "Close menu" })).toHaveAttribute("aria-expanded", "true");
  await expect(forecast).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(forecast).toBeHidden();
  await expect(page.getByRole("button", { name: "Open menu" })).toBeFocused();
  await page.getByRole("button", { name: "Open menu" }).click();
  await forecast.click();
  await expect(page).toHaveURL(/\/forecast$/);
  await expect(page.getByRole("navigation").getByRole("link", { name: "Map" })).toBeHidden();
});

test("language cookie is HttpOnly, SameSite=Lax and holds only an allow-listed code", async ({ page, context }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "English" }).first().click();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  const cookie = (await context.cookies()).find((c) => c.name === "windcast_lang");
  expect(cookie?.value).toBe("en");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Lax");
  expect(await page.evaluate(() => document.cookie)).not.toContain("windcast_lang");
});
