// Task 17: the words and numbers the creator reads (filming guide, wait times, output line) and a layout that works at
// 1440×900, in the Claude app's ~680 px side pane and on a phone. Run with `npx playwright test`.
// Set FT_SHOTS_DIR=<folder> to also save the review screenshots (the last test; skipped otherwise).
const fs = require('fs');
const path = require('path');
const { test, expect, openSample } = require('./fixture');

const CLIP_1080 = path.join(__dirname, '.fixtures', 'clip_1080.mp4');
const CLIP_4K =path.join(__dirname, '.fixtures', 'clip_4k.mp4');
const ROOT = path.join(__dirname, '..', '..');
const FILMING_MD = path.join(ROOT, 'plugin', 'skills', 'floored', 'reference', 'filming.md');
const SAMPLE_POSTER = path.join(ROOT, 'plugin', 'skills', 'floored', 'app', 'sample', 'poster.jpg');
const JARGON = /RVM|k0|\btier\b|proxy|onnx|matte|alpha|prototype/i;
const VIEWPORTS = [{ w: 1440, h: 900 }, { w: 680, h: 900 }, { w: 390, h: 844 }];

const bodyText = (page) => page.evaluate(() => document.body.innerText);
const noSideScroll = (page) => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);

// every visible piece of text outside the engine's stage that is set smaller than 12 px
async function smallLabels(page) {
  return page.evaluate(() => {
    const bad = [];
    for (const el of document.querySelectorAll('body *')) {
      if (el.closest('.stage, .ft-root, .sr-only, script, style, svg, [hidden]')) continue;
      if (![...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
      const cs = getComputedStyle(el), r = el.getBoundingClientRect();
      if (cs.display === 'none' || cs.visibility === 'hidden' || !r.width || !r.height) continue;
      if (parseFloat(cs.fontSize) < 12) bad.push(el.tagName.toLowerCase() + '.' + el.className + ' ' + cs.fontSize + ' "' + el.textContent.trim().slice(0, 30) + '"');
    }
    return bad;
  });
}

// a take the page believes in, without running the pipeline: GET /api/takes/<id> answers with `take` and `status`
async function mockTake(page, id, take, status) {
  await page.route('**/takes/' + id + '/poster.jpg', (route) => route.fulfill({ status: 200, contentType: 'image/jpeg', body: fs.readFileSync(SAMPLE_POSTER) }));
  await page.route('**/api/takes/' + id, (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({ take: Object.assign({ id, name: 'Mock take', w: 1080, h: 1920, fps: 24, dur: 5, frames: 120, warnings: [] }, take), status })
  }));
}
// the export API with a render the test steers: POST /api/export starts job j1, GET /api/exports/j1 answers with `state`
async function stubExport(page, state) {
  await page.route('**/api/export', (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ id: 'j1' }) }));
  await page.route('**/api/exports/j1', (route) => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify(state.stage === 'done'
      ? { stage: 'done', progress: 1, file: '/stub/out.mp4', path: 'C:\\Users\\you\\floored\\intro.mp4' }
      : state.stage === 'error' ? { stage: 'error', progress: 0, message: 'The render did not finish. Try again.' }
      : { stage: state.stage, progress: state.progress })
  }));
  await page.route('**/stub/out.mp4', (route) => route.fulfill({ status: 200, contentType: 'video/mp4', body: fs.readFileSync(CLIP_1080) }));
}
const cutting = (extra) => Object.assign({ stage: 'cutting', progress: 0.3, overall: 0.25, message: 'Cutting you out' }, extra);
const notChromium = (page) => page.addInitScript(() => { Object.defineProperty(navigator, 'userAgentData', { get: () => undefined }); });

test.describe('copy', () => {
  test('the filming guide on the home screen has the numbers filming.md has', async ({ page }) => {
    await page.goto('/');
    const guide = await page.evaluate(async () => (await import('/js/copy.js')).FILMING);
    const md = fs.readFileSync(FILMING_MD, 'utf8');
    const how = page.locator('.how-card');
    await expect(how).toBeVisible();
    for (const r of guide.rules) {
      expect(md, 'filming.md has "' + r.title + '"').toContain(r.title);
      expect(md, 'filming.md has "' + r.text + '"').toContain(r.text);
      await expect(how).toContainText(r.title);
      await expect(how).toContainText(r.text);
    }
    // the guide is about where the camera goes and how to stand, nothing else
    expect(guide.ai).toBeUndefined();
    expect(md).not.toMatch(/\bAI\b/);
    await expect(how).not.toContainText(/\bAI\b/);
    // the numbers the lead fixed
    const all = guide.rules.map((r) => r.title + ' ' + r.text).join(' ');
    for (const n of ['3 m up', '45–50°', '1×', '20%', '3 to 8 seconds']) {
      expect(all, n).toContain(n);
      expect(md, n).toContain(n);
    }
  });

  test('the sample tile says AI-generated sample', async ({ page }) => {
    await page.goto('/');
    const tile = page.locator('.sample-tile');
    await expect(tile).toContainText('AI-generated sample');
    await expect(tile).toContainText('Try the sample take');
    await tile.click();
    await expect(page).toHaveURL(/#\/studio\/sample/);
  });

  test('frame rates read as people say them', async ({ page }) => {
    await page.goto('/');
    const got = await page.evaluate(async () => {
      const c = await import('/js/copy.js');
      return ['24000/1001', '30000/1001', '60000/1001', '24/1', '30', 30, 25, 50, 59.94, '23.976', 29.97,
        'garbage', '30/0', '', null, undefined, 0, -3, 'NaN', '12abc'].map((v) => c.fpsLabel(v));
    });
    expect(got).toEqual(['23.976', '29.97', '59.94', '24', '30', '30', '25', '50', '59.94', '23.976', '29.97',
      '', '', '', '', '', '', '', '', '']);
  });

  test('the output line and the estimates come from the take', async ({ page }) => {
    await page.goto('/');
    const got = await page.evaluate(async () => {
      const c = await import('/js/copy.js');
      return {
        lines: [
          c.outputLine({ out: { w: 1080, h: 1920, fpsStr: '24000/1001' } }),
          c.outputLine({ out: { w: 2160, h: 3840, fpsStr: '30' } }),
          c.outputLine({ out: { w: 1080, h: 1920, fpsStr: '25' } }),
          c.outputLine({ out: { w: 1080, h: 1920, fpsStr: '50' } }),
          c.outputLine({ out: { w: 1080, h: 1920, fpsStr: '60000/1001' } }),
          c.outputLine({ out: { w: 1080, h: 1920, fps: 59.94 } }),
          c.outputLine({ out: { w: 1080, h: 1920, fps: 23.976 } }),                        // fpsStr missing: out.fps stands in
          c.outputLine({ out: { w: 1080, h: 1920, fpsStr: 'garbage', fps: 23.976 } }),     // fpsStr unreadable: same
          c.outputLine({ out: { w: 1080, h: 1920, fpsStr: 'garbage', fps: 'nonsense' } }), // nothing readable: no false claim
          c.outputLine({ out: { w: 1080, h: 1920, fpsStr: 'garbage' }, fps: 24 }),         // `out` exists: the stage's fps is not the output's
          c.outputLine({ w: 1080, h: 1920, fps: 24 })                                      // the sample: no `out`
        ],
        result: c.resultLine({ out: { w: 1080, h: 1920, fpsStr: 'garbage' } }),
        est: [c.exportEstimateText(24, 2.7, true), c.exportEstimateText(150, 2.7, true), c.exportEstimateText(121, 1.3, false), c.exportEstimateText(1, 1.3, false)],
        running: [c.exportRunningText(24, 2.7, true), c.exportRunningText(24, 1.3, false)]
      };
    });
    expect(got.lines).toEqual([
      'MP4 · 1080 × 1920 · 23.976 fps · matches your take',
      'MP4 · 2160 × 3840 · 30 fps · matches your take',
      'MP4 · 1080 × 1920 · 25 fps · matches your take',
      'MP4 · 1080 × 1920 · 50 fps · matches your take',
      'MP4 · 1080 × 1920 · 59.94 fps · matches your take',
      'MP4 · 1080 × 1920 · 59.94 fps · matches your take',
      'MP4 · 1080 × 1920 · 23.976 fps · matches your take',
      'MP4 · 1080 × 1920 · 23.976 fps · matches your take',
      'MP4 · 1080 × 1920',
      'MP4 · 1080 × 1920',
      'MP4 · 1080 × 1920 · 24 fps · matches your take'
    ]);
    expect(got.result).toBe('MP4 · 1080 × 1920');
    expect(got.est).toEqual(['4K export: about 2 min', '4K export: about 7 min', 'Export: about 3 min', 'Export: about 1 min']);
    expect(got.running).toEqual(['Rendering your intro. A 4K render takes longer, about 2 min.', 'Rendering your intro. This usually takes a few minutes.']);
  });

  for (const [label, status, want] of [
    ['190 s left', cutting({ eta: 190, etaGuess: false }), 'About 4 min left'],
    ['exactly 3 min', cutting({ eta: 180, etaGuess: false }), 'About 3 min left'],
    ['40 s left', cutting({ eta: 40, etaGuess: false }), 'Less than a minute left'],
    ['a guess', cutting({ eta: 400, etaGuess: true }), 'About 7 min (first run, rough guess)']
  ]) {
    test('processing shows the wait: ' + label, async ({ page }) => {
      await mockTake(page, 'mock-eta', {}, status);
      await page.goto('/#/processing/mock-eta');
      await expect(page.locator('.step[data-state="active"]')).toContainText(want);
    });
  }

  test('processing shows no wait outside the cutting stage', async ({ page }) => {
    await mockTake(page, 'mock-eta2', {}, { stage: 'measuring', progress: 0.5, overall: 0.8, message: '', eta: 300, etaGuess: false });
    await page.goto('/#/processing/mock-eta2');
    await expect(page.locator('.step[data-state="active"]')).toContainText('50%');
    expect(await page.locator('.steps').innerText()).not.toMatch(/min|minute/i);
  });

  test('every take warning is shown with its message', async ({ page }) => {
    const warnings = [
      { code: 'edge', message: 'Part of you touches the edge of the frame. Step back a little.' },
      { code: 'moved', message: 'Your feet move during the clip, so the words may not stay lined up with you.' },
      { code: 'long', message: 'This clip is just over 10 seconds. It still works, but 8 seconds or less looks best.' }
    ];
    await mockTake(page, 'mock-warn', { warnings }, cutting({ eta: 100, etaGuess: false }));
    await page.goto('/#/processing/mock-warn');
    for (const w of warnings) await expect(page.locator('.proc-side')).toContainText(w.message);
  });

  test('the studio lists the warning of a take', async ({ page }) => {
    await openSample(page);
    await page.locator('.take-chip').click();
    await expect(page.locator('.popover')).toContainText(/Your body touches the edge of the frame/);
  });

  test('no jargon on screen', async ({ page }) => {
    const seen = [];
    const scan = async (what) => { seen.push(what); expect(await bodyText(page), what).not.toMatch(JARGON); };
    await page.goto('/');
    await scan('home');
    await mockTake(page, 'mock-jargon', { warnings: [{ code: 'edge', message: 'Part of you touches the edge of the frame.' }] }, cutting({ eta: 100, etaGuess: true }));
    await page.goto('/#/processing/mock-jargon');
    await expect(page.locator('.step[data-state="active"]')).toBeVisible();
    await scan('processing');
    await openSample(page);
    await scan('studio');
    // the take chip's notes
    await page.locator('.take-chip').click();
    await expect(page.locator('.popover')).toBeVisible();
    await scan('warnings popover');
    await page.keyboard.press('Escape');
    await expect(page.locator('.popover')).toBeHidden();
    // the panel is a single-open accordion: open every section in turn and scan after each one
    const heads = page.locator('button[id^="acc-"]');
    const n = await heads.count();
    expect(n, 'panel sections').toBeGreaterThanOrEqual(10);
    for (let i = 0; i < n; i++) {
      const head = heads.nth(i), id = await head.getAttribute('id');
      if ((await head.getAttribute('aria-expanded')) !== 'true') await head.click();
      await expect(head).toHaveAttribute('aria-expanded', 'true');
      await scan('section ' + id);
    }
    expect(seen.filter((x) => x.startsWith('section ')).length, 'every section scanned').toBe(n);
    // the export dialog in all its faces, the render steered through a stubbed API
    const state = { stage: 'writing', progress: 0 };
    await stubExport(page, state);
    await page.getByRole('button', { name: 'Export' }).click();
    const dialog = page.getByRole('dialog', { name: 'Export your intro' });
    await expect(dialog).toBeVisible();
    await scan('export idle');
    await dialog.getByRole('button', { name: 'Render', exact: true }).click();
    await expect(dialog).toHaveAttribute('data-view', 'running');
    await expect(dialog.locator('.step[data-state="active"]')).toContainText('Setting things up');
    await scan('export running (preparing)');
    state.stage = 'rendering'; state.progress = 0.4;
    await expect(dialog.locator('.step[data-state="active"]')).toContainText('40%', { timeout: 5000 });
    await scan('export running (rendering)');
    state.stage = 'sound'; state.progress = 0.9;
    await expect(dialog.locator('.step[data-state="active"]')).toContainText('Adding your voice and effects', { timeout: 5000 });
    await scan('export running (sound)');
    state.stage = 'done';
    await expect(dialog).toHaveAttribute('data-view', 'done', { timeout: 10000 });
    await scan('export done');
    await dialog.getByRole('button', { name: 'Render again' }).click();
    await expect(dialog).toHaveAttribute('data-view', 'idle');
    state.stage = 'error';
    await dialog.getByRole('button', { name: 'Render', exact: true }).click();
    await expect(dialog).toHaveAttribute('data-view', 'error', { timeout: 10000 });
    await scan('export error');
  });

  test('no prototype badge in the header', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.topbar')).not.toContainText(/prototype/i);
    await expect(page.locator('.pill')).toHaveCount(0);
  });
});

test.describe('layout', () => {
  for (const vp of VIEWPORTS) {
    test(`studio at ${vp.w}×${vp.h}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.w, height: vp.h });
      await openSample(page);
      expect(await noSideScroll(page), 'no horizontal scroll').toBeLessThanOrEqual(0);
      const stage = await page.locator('.stage').evaluate((el) => {
        const r = el.getBoundingClientRect();
        const w = Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0)), h = Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
        return (w * h) / (r.width * r.height);
      });
      expect(stage, 'the stage is at least 90 % in view').toBeGreaterThanOrEqual(0.9);
      const exp = await page.getByRole('button', { name: 'Export' }).evaluate((el) => {
        const r = el.getBoundingClientRect(), hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        return { left: r.left, right: r.right, bottom: r.bottom, reachable: !!hit && (hit === el || el.contains(hit)), vw: innerWidth, vh: innerHeight };
      });
      expect(exp.left, 'Export starts inside the screen').toBeGreaterThanOrEqual(0);
      expect(exp.right, 'Export ends inside the screen').toBeLessThanOrEqual(exp.vw);
      expect(exp.bottom).toBeLessThanOrEqual(exp.vh);
      expect(exp.reachable, 'nothing covers Export').toBe(true);
      expect(await smallLabels(page), 'labels under 12 px').toEqual([]);
    });

    test(`home, processing and the export dialog at ${vp.w}×${vp.h}`, async ({ page }) => {
      await page.setViewportSize({ width: vp.w, height: vp.h });
      await page.goto('/');
      await expect(page.getByRole('heading', { name: 'Stand on your own words.' })).toBeVisible();
      expect(await noSideScroll(page), 'home: no horizontal scroll').toBeLessThanOrEqual(0);
      expect(await smallLabels(page), 'home: labels under 12 px').toEqual([]);
      await mockTake(page, 'mock-lay', { warnings: [{ code: 'edge', message: 'Part of you touches the edge of the frame. Step back a little or zoom out so there is room on every side.' }] }, cutting({ eta: 100, etaGuess: true }));
      await page.goto('/#/processing/mock-lay');
      await expect(page.locator('.step[data-state="active"]')).toBeVisible();
      expect(await noSideScroll(page), 'processing: no horizontal scroll').toBeLessThanOrEqual(0);
      expect(await smallLabels(page), 'processing: labels under 12 px').toEqual([]);
      await openSample(page);
      await page.getByRole('button', { name: 'Export' }).click();
      const dialog = page.getByRole('dialog', { name: 'Export your intro' });
      await expect(dialog).toBeVisible();
      expect(await noSideScroll(page), 'export: no horizontal scroll').toBeLessThanOrEqual(0);
      expect(await smallLabels(page), 'export: labels under 12 px').toEqual([]);
      const box = await dialog.boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(vp.w);
      await expect(dialog.getByRole('button', { name: 'Render' })).toBeInViewport();
    });
  }

  // the bar for a browser that cannot play the cut-out video must fit every screen, narrow ones too
  for (const vp of VIEWPORTS) {
    test(`the browser notice fits at ${vp.w} px`, async ({ page }) => {
      await notChromium(page);
      await page.setViewportSize({ width: vp.w, height: vp.h });
      await page.goto('/');
      await expect(page.locator('.browser-notice')).toBeVisible();
      expect(await noSideScroll(page), 'home with the notice').toBeLessThanOrEqual(0);
      await expect(page.getByRole('heading', { name: 'Stand on your own words.' })).toBeInViewport({ ratio: 0.5 });
      expect(await smallLabels(page), 'home notice labels').toEqual([]);
      await mockTake(page, 'mock-notice', {}, cutting({ eta: 100, etaGuess: false }));
      await page.goto('/#/processing/mock-notice');
      await expect(page.locator('.step[data-state="active"]')).toBeVisible();
      expect(await noSideScroll(page), 'processing with the notice').toBeLessThanOrEqual(0);
      await openSample(page);
      expect(await noSideScroll(page), 'studio with the notice').toBeLessThanOrEqual(0);
      await expect(page.getByRole('button', { name: 'Export' })).toBeInViewport();
    });
  }
});

test.describe('a 4K take', () => {
  test('previews from its smaller copy and exports at 2160 × 3840 with an honest estimate', async ({ page }) => {
    const media = [];
    page.on('request', (r) => { if (/\/takes\/[^/]+\/(person|shadow|audio)[^/]*$/.test(r.url())) media.push(r.url().split('/').pop()); });
    await page.goto('/');
    await page.locator('input[type=file]').setInputFiles(CLIP_4K);
    await expect(page).toHaveURL(/#\/studio\//, { timeout: 85000 });
    await expect(page.locator('.ft-row').first()).toBeVisible();
    const take = await page.evaluate(() => window.__ft.take());
    expect(take.out.w).toBe(2160);
    expect(take.files.preview).toBe('person_proxy.webm');
    expect(media).toContain('person_proxy.webm');
    expect(media).not.toContain('person.webm');
    await page.getByRole('button', { name: 'Export' }).click();
    await expect(page.locator('.format-line')).toContainText('MP4 · 2160 × 3840 · 24 fps · matches your take');
    const info = await (await page.request.get('/api/info')).json();
    const mins = Math.ceil(take.frames * info.estimates.renderSecPerFrame['2'] / 60);
    await expect(page.locator('.format-estimate')).toHaveText('4K export: about ' + mins + ' min');
    expect(await bodyText(page), '4K export dialog').not.toMatch(JARGON);
    // the running view says the 4K wait too, and nothing technical
    const state = { stage: 'rendering', progress: 0.2 };
    await stubExport(page, state);
    const dialog = page.getByRole('dialog', { name: 'Export your intro' });
    await dialog.getByRole('button', { name: 'Render', exact: true }).click();
    await expect(dialog).toHaveAttribute('data-view', 'running');
    await expect(dialog.locator('.lede')).toHaveText('Rendering your intro. A 4K render takes longer, about ' + mins + ' min.');
    expect(await bodyText(page), '4K export running').not.toMatch(JARGON);
    state.stage = 'error';
    await expect(dialog).toHaveAttribute('data-view', 'error', { timeout: 10000 });
    expect(await bodyText(page), '4K export error').not.toMatch(JARGON);
  });

  test('a 1080 take has its own estimate, not the 4K one', async ({ page }) => {
    await openSample(page);
    await page.getByRole('button', { name: 'Export' }).click();
    await expect(page.locator('.format-line')).toContainText('MP4 · 1080 × 1920 · 24 fps · matches your take');
    const take = await page.evaluate(() => window.__ft.take());
    const info = await (await page.request.get('/api/info')).json();
    const mins = Math.max(1, Math.ceil(take.frames * info.estimates.renderSecPerFrame['1'] / 60));
    await expect(page.locator('.format-estimate')).toHaveText('Export: about ' + mins + ' min');
    await expect(page.locator('.format-estimate')).not.toContainText('4K');
  });

  test('the estimate follows what /api/info says', async ({ page }) => {
    await page.route('**/api/info', async (route) => {
      const res = await route.fetch();
      const body = await res.json();
      body.estimates.renderSecPerFrame['1'] = 6;                 // a slow machine
      await route.fulfill({ response: res, json: body });
    });
    await openSample(page);
    await page.getByRole('button', { name: 'Export' }).click();
    const take = await page.evaluate(() => window.__ft.take());
    const mins = Math.ceil(take.frames * 6 / 60);
    await expect(page.locator('.format-estimate')).toHaveText('Export: about ' + mins + ' min');
  });
});

test('screenshots for the taste pass', async ({ page }) => {
  const dir = process.env.FT_SHOTS_DIR;
  test.skip(!dir, 'set FT_SHOTS_DIR to save the review screenshots');
  test.setTimeout(240000);
  fs.mkdirSync(dir, { recursive: true });
  const shot = async (name) => { await page.waitForTimeout(600); await page.screenshot({ path: path.join(dir, name + '.png') }); };
  const warn = [{ code: 'edge', message: 'Part of you touches the edge of the frame around 1.3 s and 2.6 s. Step back a little or zoom out so there is room on every side.' }];

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await expect(page.locator('.how-card')).toBeVisible();
  await shot('home-1440x900');
  await mockTake(page, 'mock-shot', { warnings: warn }, cutting({ eta: 190, etaGuess: false }));
  await page.goto('/#/processing/mock-shot');
  await expect(page.locator('.step[data-state="active"]')).toContainText('About 4 min left');
  await shot('processing-eta-1440x900');
  await page.setViewportSize({ width: 390, height: 844 });
  await shot('processing-eta-390x844');
  await page.setViewportSize({ width: 680, height: 900 });
  await openSample(page);
  await shot('studio-680x900');
  await page.getByRole('button', { name: 'Export' }).click();
  await expect(page.getByRole('dialog', { name: 'Export your intro' })).toBeVisible();
  await shot('export-1080-680x900');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.keyboard.press('Escape');
  await expect(page.locator('.modal-backdrop')).toBeHidden();
  await shot('studio-390x844');

  await page.goto('/');
  await page.locator('input[type=file]').setInputFiles(CLIP_4K);
  await expect(page).toHaveURL(/#\/studio\//, { timeout: 85000 });
  await expect(page.locator('.ft-row').first()).toBeVisible();
  await page.setViewportSize({ width: 680, height: 900 });
  await page.getByRole('button', { name: 'Export' }).click();
  await expect(page.locator('.format-estimate')).toBeVisible();
  await shot('export-4k-680x900');

  await notChromium(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await page.reload();
  await expect(page.locator('.browser-notice')).toBeVisible();
  await shot('home-notice-1440x900');
  await page.setViewportSize({ width: 390, height: 844 });
  await shot('home-notice-390x844');
  await page.setViewportSize({ width: 680, height: 900 });
  await page.goto('/#/processing/mock-shot');
  await expect(page.locator('.step[data-state="active"]')).toBeVisible();
  await shot('processing-notice-680x900');
  await openSample(page);
  await shot('studio-notice-680x900');
});
