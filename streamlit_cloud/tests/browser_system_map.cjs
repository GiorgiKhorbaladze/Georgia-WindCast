/* Run against the Streamlit app with Node and Playwright installed. */
const assert = require('node:assert/strict');
const path = require('node:path');
const { chromium, firefox, webkit } = require('playwright');

const engines = {chromium, firefox, webkit};
const url = process.env.STREAMLIT_URL || 'http://127.0.0.1:8501';
const output = process.env.SCREENSHOT_DIR;

async function exercise(browser, dimensions, english, fallback) {
  const context = await browser.newContext({
    viewport: dimensions, hasTouch: fallback, reducedMotion: 'reduce',
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  const nav = page.getByTestId('stSidebar');
  await nav.getByText('English', {exact: true}).waitFor({state: 'attached'});
  if (await page.getByTestId('stExpandSidebarButton').isVisible()) {
    await page.getByTestId('stExpandSidebarButton').click();
  }
  if (english) await nav.getByText('English', {exact: true}).click();
  const started = Date.now();
  await nav.getByText(english ? 'System map' : 'სისტემის რუკა', {exact: true}).click();
  if (fallback) {
    const close = page.getByTestId('stSidebarCollapseButton').locator('button');
    if (await close.isVisible()) await close.click();
  }

  const frame = page.frameLocator('iframe[title$=".system_map"]');
  const stage = frame.locator('#stage');
  await frame.getByRole('heading', {name: english ? 'Wind generation' : 'ქარის გენერაცია'}).waitFor();
  const bootMs = Date.now() - started;
  assert(await frame.locator('#map *').count() < 50);
  assert.equal(await frame.locator('#national .metric').count(), 4);
  assert.equal(await frame.locator('#mix .metric').count(), 4);
  assert.equal(await frame.locator('.exchanges article').count(), 2);
  assert(await stage.evaluate(node => node.ownerDocument.documentElement.scrollWidth <= node.ownerDocument.defaultView.innerWidth));
  const language = english ? 'en' : 'ka';
  const viewport = fallback ? 'mobile' : 'desktop';
  if (output) await stage.screenshot({path: path.join(output, language + '-' + viewport + '.png')});
  if (output && english) {
    await frame.locator('.exchanges').screenshot({path: path.join(output, 'exchange-panels-' + viewport + '.png')});
  }

  await frame.locator('#plus').click();
  const view = await frame.locator('#camera').getAttribute('transform');
  assert.match(view, /scale\(1\.27\)/);
  if (fallback) await stage.evaluate(node => Object.defineProperty(node.ownerDocument, 'fullscreenEnabled', {value: false}));
  await frame.locator('#expand').click();
  await frame.locator('#stage[data-fullscreen="native"], #stage[data-fullscreen="immersive"]').waitFor();
  const mode = await stage.getAttribute('data-fullscreen');
  if (fallback) assert.equal(mode, 'immersive');
  const box = await stage.boundingBox();
  assert(box.width >= dimensions.width - 2 && box.height >= dimensions.height - 2, JSON.stringify(box));
  assert.equal(await frame.locator('#camera').getAttribute('transform'), view);
  if (output) {
    await frame.locator('#reset').click();
    await page.screenshot({path: path.join(output, language + '-' + viewport + '-expanded.png')});
    await frame.locator('#plus').click();
  }
  if (fallback) await frame.locator('#expand').press('Escape');
  else await frame.locator('#expand').click();
  await frame.locator('#stage[data-fullscreen="normal"]').waitFor();
  assert.equal(await frame.locator('#camera').getAttribute('transform'), view);
  await frame.locator('#reset').click();
  assert.equal(await frame.locator('#camera').getAttribute('transform'), 'translate(0 0) scale(1)');

  await frame.locator('.site').first().focus();
  await frame.locator('.site').first().press('Enter');
  await frame.locator('#site-info').waitFor();
  await frame.locator('#close-site').click();
  if (await frame.locator('#play').isEnabled()) {
    await frame.locator('#play').click();
    await frame.locator('#mode[data-status="historical"]').waitFor();
    await frame.locator('#latest').click();
    assert.notEqual(await frame.locator('#mode').getAttribute('data-status'), 'historical');
  }
  assert.deepEqual(errors, []);
  console.log(language, viewport, mode, 'passed', 'map ready in', bootMs, 'ms');
  await context.close();
}

(async () => {
  const engine = engines[process.env.BROWSER_ENGINE || 'chromium'];
  const browser = await engine.launch({executablePath: process.env.BROWSER_EXECUTABLE || undefined});
  try {
    for (const english of [true, false]) {
      await exercise(browser, {width: 1440, height: 960}, english, false);
      await exercise(browser, {width: 390, height: 844}, english, true);
    }
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
