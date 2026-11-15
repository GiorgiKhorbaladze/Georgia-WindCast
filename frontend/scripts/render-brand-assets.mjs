// Renders the brand assets from design/ sources (run manually; outputs are committed):
//   design/og-card.html -> public/og-image.png (1200x630)
//   design/icon.svg     -> src/app/icon.svg, src/app/apple-icon.png (180), public/icon-192.png, public/icon-512.png
// Usage: node scripts/render-brand-assets.mjs   (PW_CHROMIUM_PATH optional), then
//   python3 -c "from PIL import Image; Image.open('design/icon-256.png').save('src/app/favicon.ico', sizes=[(16,16),(32,32),(48,48)])"
import { copyFileSync, readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { chromium } from "@playwright/test";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const browser = await chromium.launch({ executablePath: process.env.PW_CHROMIUM_PATH || undefined });
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
  await page.goto(pathToFileURL(resolve(root, "design/og-card.html")).href);
  await page.evaluate(() => document.fonts.ready);
  await page.screenshot({ path: resolve(root, "public/og-image.png") });

  const svg = readFileSync(resolve(root, "design/icon.svg"), "utf8");
  copyFileSync(resolve(root, "design/icon.svg"), resolve(root, "src/app/icon.svg"));
  for (const [size, out] of [[180, "src/app/apple-icon.png"], [192, "public/icon-192.png"], [512, "public/icon-512.png"], [256, "design/icon-256.png"]]) {
    const p = await browser.newPage({ viewport: { width: size, height: size }, deviceScaleFactor: 1 });
    await p.setContent(`<html><body style="margin:0;background:transparent">${svg.replace("<svg ", `<svg width="${size}" height="${size}" `)}</body></html>`);
    await p.screenshot({ path: resolve(root, out), omitBackground: true });
    await p.close();
  }
} finally {
  await browser.close();
}
console.log("brand assets rendered");
