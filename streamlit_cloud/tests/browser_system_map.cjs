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
  assert(await stage.evaluate(node => node.ownerDocument.defaultView.matchMedia('(prefers-reduced-motion: reduce)').matches));
  assert.equal(await frame.locator('#expand').evaluate(button => getComputedStyle(button).transitionDuration), '0s');
  assert(await frame.locator('#map *').count() < 50);
  assert.equal(await frame.locator('#national .metric').count(), 4);
  assert.equal(await frame.locator('#mix .metric').count(), 4);
  assert.equal(await frame.locator('.exchanges article').count(), 2);
  const differenceLabel = english ? 'Difference between published balance figures' : 'გამოქვეყნებული მაჩვენებლების შეუსაბამობა';
  if (await frame.locator('#closure-note').isVisible()) {
    assert((await frame.locator('#closure').innerText()).startsWith(differenceLabel));
    assert.match(await frame.locator('#closure').innerText(), / · [+-]?[\d,.]+ MW$/);
  }
  assert(await stage.evaluate(node => node.ownerDocument.documentElement.scrollWidth <= node.ownerDocument.defaultView.innerWidth));
  const language = english ? 'en' : 'ka';
  const viewport = fallback ? 'mobile' : 'desktop';
  if (output) await stage.screenshot({path: path.join(output, language + '-' + viewport + '.png')});
  if (output) {
    const prefix = english ? 'exchange-panels-' : 'ka-exchange-panels-';
    await frame.locator('.details').screenshot({path: path.join(output, prefix + viewport + '.png')});
  }

  const resized = {width: dimensions.width, height: dimensions.height + 120};
  await page.setViewportSize(resized);
  await stage.evaluate((node, height) => new Promise((resolve, reject) => {
    const check = () => {
      if (Math.abs(node.getBoundingClientRect().height - height) <= 2) {
        clearTimeout(timeout);
        observer.disconnect();
        resolve();
      }
    };
    const observer = new ResizeObserver(check);
    const timeout = setTimeout(() => { observer.disconnect(); reject(new Error('Normal height did not follow host')); }, 5000);
    observer.observe(node);
    check();
  }), Math.round(resized.height * .78));
  await page.setViewportSize(dimensions);
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
  if (fallback) {
    await page.setViewportSize({width: dimensions.height, height: dimensions.width});
    const landscape = await stage.boundingBox();
    assert(landscape.width >= dimensions.height - 2 && landscape.height >= dimensions.width - 2);
    await page.setViewportSize(dimensions);
  }
  await frame.locator('#expand').press('Escape');
  await frame.locator('#stage[data-fullscreen="normal"]').waitFor();
  await frame.locator('#expand').click();
  await frame.locator('#stage[data-fullscreen="' + mode + '"]').waitFor();
  await frame.locator('#expand').click();
  await frame.locator('#stage[data-fullscreen="normal"]').waitFor();
  assert.equal(await frame.locator('#camera').getAttribute('transform'), view);
  await stage.scrollIntoViewIfNeeded();
  const map = await frame.locator('#map').boundingBox();
  const x = map.x + map.width / 2;
  const y = map.y + map.height * .53;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x - 42, y + 30, {steps: 6});
  await page.mouse.up();
  assert.notEqual(await frame.locator('#camera').getAttribute('transform'), view);
  await frame.locator('#reset').click();
  assert.equal(await frame.locator('#camera').getAttribute('transform'), 'translate(0 0) scale(1)');

  await frame.locator('.site').first().focus();
  await frame.locator('.site').first().press('Enter');
  await frame.locator('#site-info').waitFor();
  // Regression: the details card must not sit under the bottom dock (mix panel grew it).
  const card = await frame.locator('#site-info').boundingBox();
  const dock = await frame.locator('.stage-bottom').boundingBox();
  assert(card.y + card.height <= dock.y, `site details overlap the dock: ${card.y + card.height} > ${dock.y}`);
  await frame.locator('#close-site').click();
  if (await frame.locator('#play').isEnabled()) {
    const time = frame.locator('#time');
    const latestLabel = await frame.locator('#source-time').innerText();
    await time.press('Home');
    const recorded = await time.getAttribute('aria-valuetext');
    assert.match(recorded, /\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2} \(UTC\+4\)/);
    assert((await frame.locator('#source-time').innerText()).includes(recorded));
    assert.notEqual(await frame.locator('#source-time').innerText(), latestLabel);
    await frame.locator('#speed').selectOption('4');
    await frame.locator('#play').click();
    await frame.locator('#mode[data-status="historical"]').waitFor();
    await frame.locator('#latest').click();
    assert.notEqual(await frame.locator('#mode').getAttribute('data-status'), 'historical');
    assert.equal(await frame.locator('#source-time').innerText(), latestLabel);
  }
  if (process.env.SYSTEM_MAP_AUDIT && english && !fallback) {
    console.log('ARCHIVE_AUDIT ' + JSON.stringify(await stage.evaluate(node => {
      const doc = node.ownerDocument;
      return {
        timestamp: doc.querySelector('#source-time').innerText,
        retrieved: doc.querySelector('#retrieved').innerText,
        metrics: [...doc.querySelectorAll('#national .metric,#mix .metric')].map(card => card.innerText),
        hero: doc.querySelector('#wind').innerText,
        closure: doc.querySelector('#closure').innerText,
      };
    })));
  }
  // Inject test-only presentations after testing the original archive-backed view.
  if (english && !fallback) {
    const scenarios = await stage.evaluate(() => {
      const original = data;
      const sample = {
        ...data.periods.at(-1), time: 0, status: 'unconfirmed', wind_confirmed: false,
        values: {wind: 0, import: null}, residual: null,
      };
      const inspect = periods => {
        render({...original, refresh_failed: false, periods});
        const doc = document;
        return {
          state: doc.querySelector('#mode').dataset.status,
          wind: doc.querySelector('#wind').innerText,
          provisional: !doc.querySelector('#wind-quality').hidden,
          imports: doc.querySelector('#imports strong').innerText,
          closure: doc.querySelector('#closure').innerText,
          note: doc.querySelector('#closure-note').hidden ? null : doc.querySelector('#closure-note').innerText,
          playbackDisabled: doc.querySelector('#play').disabled,
        };
      };
      try {
        return {
          difference: inspect([{...sample, residual: 16.968126}]),
          missing: inspect([sample]),
          empty: inspect([]),
        };
      } finally { render(original); }
    });
    assert.equal(scenarios.difference.closure, differenceLabel + ' · +16.97 MW');
    assert.match(scenarios.difference.note, /Arithmetic comparison only/);
    assert.equal(scenarios.missing.state, 'stale');
    assert.equal(scenarios.missing.wind, '0');
    assert(scenarios.missing.provisional);
    assert.equal(scenarios.missing.imports, '—');
    assert.equal(scenarios.missing.closure, 'Balance check unavailable');
    assert.equal(scenarios.missing.note, null);
    assert.equal(scenarios.empty.state, 'unavailable');
    assert.equal(scenarios.empty.wind, '—');
    assert(scenarios.empty.playbackDisabled);
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
