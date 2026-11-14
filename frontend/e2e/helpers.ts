import type { Page } from "@playwright/test";

export async function useLang(page: Page, lang: "ka" | "en") {
  const url = new URL(process.env.BASE_URL ?? "http://127.0.0.1:3000");
  await page.context().addCookies([{ name: "windcast_lang", value: lang, url: url.origin }]);
}

/** CI must not depend on third-party tile servers: tile/style requests are answered locally. */
export async function blockTiles(page: Page) {
  await page.route("https://tiles.openfreemap.org/**", (route) =>
    route.request().url().endsWith("/styles/dark")
      ? route.fulfill({
          contentType: "application/json",
          body: JSON.stringify({ version: 8, sources: {}, layers: [{ id: "bg", type: "background", paint: { "background-color": "#05080f" } }] }),
        })
      : route.abort(),
  );
}

export function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error" && !/Failed to load resource|net::ERR_FAILED/.test(m.text())) errors.push(m.text());
  });
  return errors;
}

export async function horizontalOverflow(page: Page): Promise<number> {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}
