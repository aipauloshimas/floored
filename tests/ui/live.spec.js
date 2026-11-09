// Live suggestions, the small-line default, the dropped-characters notice, the browser notice and font preloading (Task 16).
// The shared fixture's guard stays on: any page error, console error or __ft.log entry fails the test.
const { test, expect, CLIP_1080, readLooks, openSample } = require('./fixture');

// what `ft suggest` does: POST the hook suggestions into the take (no Origin header, which the server accepts)
async function suggest(request, baseURL, id, suggestions, smallSuggestions) {
  const r = await request.post(baseURL + '/api/takes/' + encodeURIComponent(id) + '/suggestions',
    { data: { suggestions, smallSuggestions: smallSuggestions || [] } });
  expect(r.ok(), 'POST suggestions').toBeTruthy();
  return (await r.json()).rev;
}

async function openTextSection(page, view) {
  await page.locator('#acc-text').click();
  if (view) await page.getByRole('button', { name: view }).click();
}

test('suggestions from Claude appear without a reload', async ({ page, request, baseURL }) => {
  await openSample(page, baseURL);
  await openTextSection(page, 'Suggestions');
  const before = await page.evaluate(() => window.__ft.take().suggestionsRev || 0);
  const phraseBefore = await page.evaluate(() => window.__ft.settings().text.phrase);
  const stamp = Date.now();
  const one = 'Fresh idea ' + stamp, two = 'Second idea ' + stamp;
  const rev = await suggest(request, baseURL, 'sample', [one, two], ['IN THE TERMINAL']);
  expect(rev).toBeGreaterThan(before);
  // the studio polls every 3 s: the tab shows them well inside 5 s, without a reload
  await expect(page.locator('.text-view .chip.wide', { hasText: one })).toBeVisible({ timeout: 5000 });
  await expect(page.locator('.text-view .chip.wide', { hasText: two })).toBeVisible();
  await expect(page.locator('.toast.show')).toHaveText('New ideas from Claude');
  // the sample has speech: the creator's words stay
  expect(await page.evaluate(() => window.__ft.settings().text.phrase)).toBe(phraseBefore);
  expect(await page.evaluate(() => window.__ft.take().suggestionsRev)).toBe(rev);
});

test('a speechless take adopts the first suggestion, until the creator edits the text', async ({ page, request, baseURL }) => {
  await page.goto('/');
  await page.locator('input[type=file]').setInputFiles(CLIP_1080);
  await expect(page).toHaveURL(/#\/studio\//, { timeout: 80000 });
  await expect(page.locator('.ft-row').first()).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-ready', '1');
  const id = await page.evaluate(() => window.__ft.take().id);
  expect(await page.evaluate(() => window.__ft.take().words.length), 'the test clip has no speech').toBe(0);
  expect(await page.evaluate(() => !!window.__ft.settings().text.edited)).toBe(false);

  const stamp = Date.now();
  const first = 'Claude idea ' + stamp;
  await suggest(request, baseURL, id, [first, 'Another idea ' + stamp]);
  await expect.poll(() => page.evaluate(() => window.__ft.settings().text.phrase), { timeout: 6000 }).toBe(first);
  const s = await page.evaluate(() => window.__ft.settings());
  expect(s.text.source).toBe('suggested');
  expect(s.text.edited || false).toBe(false);          // adopting is not an edit by the creator
  await expect(page.locator('.toast.show')).toHaveText('New ideas from Claude');

  // the creator types their own words: later ideas are offered, never swapped in
  await openTextSection(page, 'Type it');
  await page.getByLabel('Your words').fill('My own words');
  await expect.poll(() => page.evaluate(() => window.__ft.settings().text.phrase)).toBe('My own words');
  expect(await page.evaluate(() => window.__ft.settings().text.edited)).toBe(true);
  const rev = await suggest(request, baseURL, id, ['Later idea ' + stamp]);
  await expect.poll(() => page.evaluate(() => window.__ft.take().suggestionsRev), { timeout: 6000 }).toBe(rev);
  expect(await page.evaluate(() => window.__ft.settings().text.phrase)).toBe('My own words');
});

test('the studio polls while it is open and stops when it is left', async ({ page, baseURL }) => {
  const hits = [];
  page.on('request', (r) => { if (r.method() === 'GET' && /\/api\/takes\/sample$/.test(new URL(r.url()).pathname)) hits.push(Date.now()); });
  await openSample(page, baseURL);
  const opened = hits.length;
  await expect.poll(() => hits.length, { timeout: 8000 }).toBeGreaterThan(opened + 1);
  await page.evaluate(() => { location.hash = '#/'; });
  await expect(page.getByRole('heading', { name: 'Stand on your own words.' })).toBeVisible();
  await page.waitForTimeout(200);
  const left = hits.length;
  await page.waitForTimeout(4500);
  expect(hits.length, 'no requests after leaving the studio').toBe(left);
});

test('the small line is off by default and remembers its text', async ({ page, request, baseURL }) => {
  await openSample(page, baseURL);
  expect(await page.evaluate(() => window.__ft.settings().text.small), 'off by default').toBe('');
  await openTextSection(page);
  const sw = page.getByRole('switch', { name: 'Small line' });
  await expect(sw).toHaveAttribute('aria-checked', 'false');
  const field = page.getByLabel('Small line', { exact: true }).and(page.locator('input'));
  await expect(field).toBeDisabled();
  // no hard-coded default: the field starts from Claude's first small suggestion (the sample ships one)
  const suggested = await page.evaluate(() => window.__ft.take().smallSuggestions[0]);
  expect(suggested).toBeTruthy();
  await expect(field).toHaveValue(suggested);

  await sw.click();
  await expect(sw).toHaveAttribute('aria-checked', 'true');
  await expect.poll(() => page.evaluate(() => window.__ft.settings().text.small)).toBe(suggested);
  await field.fill('MY SERIES');
  await expect.poll(() => page.evaluate(() => window.__ft.settings().text.small)).toBe('MY SERIES');
  await expect.poll(async () => (await (await request.get(baseURL + '/api/prefs')).json()).small, { timeout: 5000 })
    .toEqual({ on: true, text: 'MY SERIES' });
  await sw.click();
  await expect(sw).toHaveAttribute('aria-checked', 'false');
  await expect.poll(async () => (await (await request.get(baseURL + '/api/prefs')).json()).small, { timeout: 5000 })
    .toEqual({ on: false, text: 'MY SERIES' });

  // a new take starts with the small line off, and the field remembers the words
  await page.goto('/');
  await page.locator('input[type=file]').setInputFiles(CLIP_1080);
  await expect(page).toHaveURL(/#\/studio\//, { timeout: 80000 });
  await expect(page.locator('.ft-row').first()).toBeVisible();
  expect(await page.evaluate(() => window.__ft.settings().text.small)).toBe('');
  await openTextSection(page);
  await expect(page.getByRole('switch', { name: 'Small line' })).toHaveAttribute('aria-checked', 'false');
  await expect(field).toHaveValue('MY SERIES');
});

test('characters the floor fonts cannot draw are named', async ({ page, baseURL }) => {
  await openSample(page, baseURL);
  await openTextSection(page, 'Type it');
  const note = page.locator('[data-dropped]');
  await expect(note).toBeHidden();
  await page.getByLabel('Your words').fill('free 🔥 ✨ 🔥 text');
  await expect(note).toBeVisible();
  await expect(note).toHaveText("Left out: 🔥 ✨ (emoji and symbols don't fit the floor fonts).");
  // an emoji is not offered as a hero word (it would be an empty chip)
  await expect.poll(() => page.locator('[data-hero]').evaluateAll((els) => els.map((e) => e.textContent))).toEqual(['None', 'FREE', 'TEXT']);
  await page.getByLabel('Your words').fill('free text');
  await expect(note).toBeHidden();
});

test('switching looks never shows an empty floor', async ({ page, baseURL }) => {
  await openSample(page, baseURL);
  const looks = await readLooks(page);
  expect(looks.length).toBe(6);
  for (const look of looks.concat(looks.slice().reverse())) {
    // sample the floor on every frame for 300 ms after the click
    const seen = await page.evaluate((id) => new Promise((resolve) => {
      const out = { minRows: Infinity, family: '', weight: '', loaded: false };
      const t0 = performance.now();
      document.querySelector('.panel .look-card[data-look="' + id + '"]').click();
      (function tick() {
        const rows = document.querySelectorAll('.ft-row');
        out.minRows = Math.min(out.minRows, rows.length);
        if (performance.now() - t0 < 300) { requestAnimationFrame(tick); return; }
        const st = rows.length ? getComputedStyle(rows[0]) : null;
        if (st) {
          out.family = st.fontFamily.split(',')[0].replace(/["']/g, '').trim();
          out.weight = st.fontWeight;
          out.loaded = Array.from(document.fonts).some((f) => f.family.replace(/["']/g, '') === out.family && f.status === 'loaded');
        }
        resolve(out);
      })();
    }), look.id);
    expect(seen.minRows, look.id + ': the floor kept its rows through the switch').toBeGreaterThan(0);
    expect(seen.family, look.id + ': row font').toMatch(/^FT /);
    expect(seen.loaded, look.id + ': the row font (' + seen.family + ') is loaded within 300 ms').toBe(true);
  }
  // and the font a look draws with is the font its row uses
  const ok = await page.evaluate(() => {
    const cur = window.__ft.settings().font;
    const row = document.querySelector('.ft-row');
    return getComputedStyle(row).fontFamily.indexOf(window.FT_DATA.FONTS[cur].family) >= 0;
  });
  expect(ok).toBe(true);
});

test('look tiles draw with the engine font stack, Inter behind the look font', async ({ page, baseURL }) => {
  await openSample(page, baseURL);
  const fams = await page.locator('.panel .look-card .look-word').evaluateAll((els) => els.map((e) => getComputedStyle(e).fontFamily));
  expect(fams.length).toBe(6);
  for (const f of fams) expect(f).toMatch(/^"FT [A-Za-z]+", "FT Inter"$/);
  // preloaded: no tile is still waiting on its font
  await expect(page.locator('.panel .look-art.is-loading')).toHaveCount(0);
  const state = await page.evaluate(() => Array.from(document.fonts).filter((f) => /^"?FT /.test(f.family)).map((f) => f.family.replace(/"/g, '') + ':' + f.status));
  expect(state.filter((s) => /^FT Inter:/.test(s)).length).toBeGreaterThan(0);
  for (const s of state) expect(s, 'preloaded font').toMatch(/:loaded$/);
});

test('non-Chromium notice: on every screen, with Copy and Get Chrome', async ({ page, baseURL }) => {
  // an ordinary Chromium shows nothing, on the home screen or in the studio
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Stand on your own words.' })).toBeVisible();
  await expect(page.locator('.browser-notice')).toHaveCount(0);
  await openSample(page, baseURL);
  await expect(page.locator('.browser-notice')).toHaveCount(0);

  await page.context().grantPermissions(['clipboard-read', 'clipboard-write'], { origin: new URL(baseURL).origin }).catch(() => {});
  await page.addInitScript(() => { Object.defineProperty(Navigator.prototype, 'userAgentData', { get() { return undefined; }, configurable: true }); });
  const message = "Open this page in Chrome or Edge. This browser can't play the cut-out video yet.";
  const above = (sel) => page.evaluate((q) => {
    const n = document.querySelector('.browser-notice'), t = document.querySelector(q);
    return n.getBoundingClientRect().bottom <= t.getBoundingClientRect().top + 1;
  }, sel);

  // home
  await page.goto('/');
  await page.reload();
  const home = page.locator('.browser-notice');
  await expect(home).toHaveCount(1);
  await expect(home).toBeVisible();
  await expect(home).toContainText(message);
  await expect(home.locator('.notice-url')).toHaveText(/^http:\/\/127\.0\.0\.1:3199\//);
  expect(await above('.home .topbar'), 'above the home top bar').toBe(true);
  const link = home.getByRole('link', { name: 'Get Chrome' });
  await expect(link).toHaveAttribute('href', 'https://www.google.com/chrome/');
  await expect(link).toHaveAttribute('target', '_blank');
  await expect(link).toHaveAttribute('rel', /noopener/);

  // studio
  await page.goto('/#/studio/sample');
  await page.reload();
  const notice = page.locator('.browser-notice');
  await expect(notice).toHaveCount(1);
  await expect(notice).toBeVisible();
  await expect(notice).toContainText(message);
  await expect(notice.locator('.notice-url')).toHaveText(/^http:\/\/127\.0\.0\.1:3199\/#\/studio\/sample/);
  expect(await above('.studio .topbar'), 'above the studio top bar').toBe(true);
  await expect(notice.getByRole('link', { name: 'Get Chrome' })).toHaveAttribute('href', 'https://www.google.com/chrome/');
  await notice.getByRole('button', { name: 'Copy' }).click();
  await expect(notice.getByRole('button', { name: 'Copied' })).toBeVisible();
  const clip = await page.evaluate(() => navigator.clipboard.readText()).catch(() => null);
  if (clip != null) expect(clip).toMatch(/^http:\/\/127\.0\.0\.1:3199\/#\/studio\/sample/);

  // export (the studio with the dialog open) keeps it
  await expect(page.locator('html')).toHaveAttribute('data-ready', '1');
  await page.getByRole('button', { name: 'Export' }).click();
  await expect(page.getByRole('dialog', { name: 'Export your intro' })).toBeVisible();
  expect(await page.evaluate(() => window.__ft.screen())).toBe('export');
  await expect(page.locator('.browser-notice')).toHaveCount(1);
});

// a take with no speech: the upload fixture (the same clip the adoption test uses)
async function openSpeechless(page) {
  await page.goto('/');
  await page.locator('input[type=file]').setInputFiles(CLIP_1080);
  await expect(page).toHaveURL(/#\/studio\//, { timeout: 80000 });
  await expect(page.locator('.ft-row').first()).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-ready', '1');
  const id = await page.evaluate(() => window.__ft.take().id);
  expect(await page.evaluate(() => window.__ft.take().words.length), 'the test clip has no speech').toBe(0);
  return id;
}

test('typing wins over a suggestion that arrives while the creator is writing', async ({ page, request, baseURL }) => {
  const id = await openSpeechless(page);
  const originalPhrase = await page.evaluate(() => window.__ft.settings().text.phrase);
  await openTextSection(page, 'Type it');
  const area = page.getByLabel('Your words');
  await area.click();
  await page.keyboard.press('Control+A');
  await page.keyboard.type('Mine');
  // the first key marks the text as edited at once, not 400 ms later
  expect(await page.evaluate(() => window.__ft.studio.S.text.edited)).toBe(true);
  const idea = 'Claude idea ' + Date.now();
  const t0 = Date.now();
  await suggest(request, baseURL, id, [idea, 'Other idea']);
  await page.evaluate(() => window.__ft.studio.poll());     // a poll lands inside the typing debounce
  expect(Date.now() - t0, 'the poll came well inside the 400 ms debounce').toBeLessThan(300);
  expect(await page.evaluate(() => window.__ft.take().suggestions[0]), 'the idea reached the take').toBe(idea);
  await expect(area).toHaveValue('Mine');
  await expect.poll(() => page.evaluate(() => window.__ft.settings().text.phrase)).toBe('Mine');
  await page.waitForTimeout(600);
  const s = await page.evaluate(() => window.__ft.settings());
  expect(s.text.phrase).toBe('Mine');
  expect(s.text.source).toBe('typed');
  expect(s.text.phrase).not.toBe(originalPhrase);
  await expect(area).toHaveValue('Mine');
});

test('a suggestion waits while the words field has focus, and goes in once the creator leaves it untouched', async ({ page, request, baseURL }) => {
  const id = await openSpeechless(page);
  await openTextSection(page, 'Type it');
  const area = page.getByLabel('Your words');
  await area.focus();                                            // the field is in hand, nothing typed
  const idea = 'Claude idea ' + Date.now();
  await suggest(request, baseURL, id, [idea]);
  await page.evaluate(() => window.__ft.studio.poll());
  expect(await page.evaluate(() => window.__ft.take().suggestions[0])).toBe(idea);
  expect(await page.evaluate(() => window.__ft.settings().text.phrase), 'no adoption while the field has focus').not.toBe(idea);
  await area.blur();
  await expect.poll(() => page.evaluate(() => window.__ft.settings().text.phrase), { timeout: 6000 }).toBe(idea);
  expect(await page.evaluate(() => !!window.__ft.settings().text.edited)).toBe(false);
});

test('a suggestion waits while the export dialog is open, and is adopted when it closes', async ({ page, request, baseURL }) => {
  const id = await openSpeechless(page);
  const before = await page.evaluate(() => window.__ft.settings().text.phrase);
  await page.getByRole('button', { name: 'Export' }).click();
  const dialog = page.getByRole('dialog', { name: 'Export your intro' });
  await expect(dialog).toBeVisible();
  const idea = 'Claude idea ' + Date.now();
  await suggest(request, baseURL, id, [idea, 'Another one']);
  await page.evaluate(() => window.__ft.studio.poll());
  // the list is fresh, the floor and the settings did not move
  expect(await page.evaluate(() => window.__ft.take().suggestions[0])).toBe(idea);
  await page.waitForTimeout(400);
  expect(await page.evaluate(() => window.__ft.settings().text.phrase), 'no restart under the open dialog').toBe(before);
  await page.evaluate(() => window.__ft.studio.poll());
  expect(await page.evaluate(() => window.__ft.settings().text.phrase)).toBe(before);
  await page.getByRole('button', { name: 'Close' }).click();
  await expect(dialog).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.__ft.settings().text.phrase), { timeout: 3000 }).toBe(idea);
  expect(await page.evaluate(() => window.__ft.settings().text.source)).toBe('suggested');
});

test('a request that hangs is given up after 10 s and live ideas keep coming', async ({ page, request, baseURL }) => {
  test.setTimeout(60000);
  await openSample(page, baseURL);
  await openTextSection(page, 'Suggestions');
  let n = 0;
  await page.route('**/api/takes/sample', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    n++;
    if (n === 1) return;                                          // the first poll never gets an answer
    return route.continue();
  });
  await expect.poll(() => n, { timeout: 6000 }).toBe(1);          // the hung request is out
  const idea = 'After the hang ' + Date.now();
  await suggest(request, baseURL, 'sample', [idea]);
  // 10 s timeout, then the next 3 s tick asks again and the idea shows
  await expect(page.locator('.text-view .chip.wide', { hasText: idea })).toBeVisible({ timeout: 22000 });
  expect(n).toBeGreaterThanOrEqual(2);
});
