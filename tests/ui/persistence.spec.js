// Studio persistence (Task 15): settings, the last look, the brand colours, the small line and "My looks" live on the
// server (prefs.json in FLOORED_HOME, settings/<take>.json in the workspace), not in the browser, so they survive a
// restart on another port (localStorage is per origin and would not).
//
// The restart test starts two servers of its own on a fresh workspace + home pair (ports 3197, then 3198). It cannot use
// the 3199 server Playwright starts: `serve` on a workspace that already has a live server just prints that server's URL
// and exits (Task 11), and stopping the 3199 one would break every other test. The fresh pair also keeps this test from
// seeing (or leaving) state in the shared one. Each server is stopped with `floored.py stop`, which kills only the pid
// in that workspace's own .server.json.
const { spawn, spawnSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { test, expect, CLIP_1080, openSample } = require('./fixture');

const ROOT = path.join(__dirname, '..', '..');
const SERVER = path.join(ROOT, 'plugin', 'skills', 'floored', 'app', 'floored.py');
const PY = (() => {
  const venv = process.platform === 'win32' ? path.join(ROOT, '.venv', 'Scripts', 'python.exe') : path.join(ROOT, '.venv', 'bin', 'python');
  return fs.existsSync(venv) ? venv : (process.platform === 'win32' ? 'python' : 'python3');
})();

function envFor(home) { return Object.assign({}, process.env, { FT_FAKE_MATTE: '1', FLOORED_HOME: home, PYTHONUTF8: '1' }); }

async function startServer(port, ws, home) {
  const child = spawn(PY, [SERVER, 'serve', '--workspace', ws, '--port', String(port)], { env: envFor(home), stdio: 'ignore', windowsHide: true });
  const url = 'http://127.0.0.1:' + port;
  const until = Date.now() + 40000;
  for (;;) {
    try { if ((await fetch(url + '/api/info')).ok) break; } catch (e) { /* not up yet */ }
    if (Date.now() > until || child.exitCode !== null) throw new Error('the server on ' + port + ' did not start');
    await new Promise((r) => setTimeout(r, 200));
  }
  return { url, child, ws, home };
}
async function stopServer(s) {
  spawnSync(PY, [SERVER, 'stop', '--workspace', s.ws], { env: envFor(s.home), encoding: 'utf8', windowsHide: true });
  const until = Date.now() + 10000;
  while (s.child.exitCode === null && Date.now() < until) await new Promise((r) => setTimeout(r, 100));
  if (s.child.exitCode === null && process.platform === 'win32') spawnSync('taskkill', ['/F', '/T', '/PID', String(s.child.pid)]);   // our own child only
  else if (s.child.exitCode === null) s.child.kill();
}

const getJSON = async (url) => (await fetch(url)).json();

// wait until the server holds what the page has shown (the page saves 400 ms after the last change)
async function savedLike(url, take, check) {
  await expect.poll(async () => check(await getJSON(url + '/api/takes/' + take + '/settings')), { timeout: 8000 }).toBe(true);
}

async function openSection(page, id) {
  const head = page.locator('#acc-' + id);
  if ((await head.getAttribute('aria-expanded')) !== 'true') await head.click();
  await expect(head).toHaveAttribute('aria-expanded', 'true');
}

async function saveAsMyLook(page, name) {
  await page.getByRole('button', { name: 'Save as my look' }).click();
  const dialog = page.getByRole('dialog', { name: 'Name your look' });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel('Look name').fill(name);
  await dialog.getByRole('button', { name: 'Save' }).click();
  await expect(dialog).toBeHidden();
  await expect(page.locator('.my-looks .look-card', { hasText: name })).toBeVisible();
}

test('settings survive a restart on another port', async ({ page }) => {
  const run = fs.mkdtempSync(path.join(os.tmpdir(), 'ft-restart-'));
  const ws = path.join(run, 'workspace'), home = path.join(run, 'home');
  fs.mkdirSync(ws); fs.mkdirSync(home);
  let a = null, b = null;
  try {
    a = await startServer(3197, ws, home);
    await openSample(page, a.url);

    // a look, a phrase, the brand colours, a small line, an effect
    const lookIds = await page.evaluate(() => window.FT_DATA.LOOKS.map((l) => l.id));
    const pick = lookIds[2];
    await page.locator('.panel .look-card[data-look="' + pick + '"]').click();
    await openSection(page, 'text');
    await page.getByRole('button', { name: 'Type it' }).click();
    await page.getByLabel('Your words').fill('Same words after a restart');
    await page.getByRole('switch', { name: 'Small line' }).click();          // the small line starts off (Task 16)
    await page.locator('input[aria-label="Small line"]').fill('MY SERIES');
    await openSection(page, 'colors');
    await page.locator('.swatch[data-id="brand"]').click();
    await page.getByLabel('Floor color').fill('#123456');
    await page.getByLabel('Words color').fill('#fedcba');
    await openSection(page, 'font');
    const fonts = await page.evaluate(() => Object.keys(window.FT_DATA.FONTS));
    const font = await page.evaluate((cur) => Object.keys(window.FT_DATA.FONTS).find((k) => k !== cur), await page.evaluate(() => window.__ft.settings().font));
    await page.locator('.tiles .tile[data-id="' + font + '"]').click();
    expect(fonts.length).toBeGreaterThan(1);
    // the phrase and the small line are typed fields: they reach the settings 400 ms after the last key
    await expect.poll(() => page.evaluate(() => window.__ft.settings().text.phrase)).toBe('Same words after a restart');
    await expect.poll(() => page.evaluate(() => window.__ft.settings().text.small)).toBe('MY SERIES');
    const before = await page.evaluate(() => window.__ft.settings());
    expect(before.text.phrase).toBe('Same words after a restart');
    expect(before.palette).toMatchObject({ id: 'brand', floor: '#123456', ink: '#fedcba' });

    // both stores have it on the server before we stop it
    await savedLike(a.url, 'sample', (s) => s.text && s.text.phrase === 'Same words after a restart' && s.font === font &&
      s.palette && s.palette.floor === '#123456' && s.text.small === 'MY SERIES');
    await expect.poll(async () => JSON.stringify((await getJSON(a.url + '/api/prefs')).brand)).toBe(JSON.stringify({ floor: '#123456', ink: '#fedcba' }));
    await saveAsMyLook(page, 'Series look');

    await page.goto('about:blank');
    await stopServer(a); a = null;
    b = await startServer(3198, ws, home);

    // another port: a fresh origin, so nothing could come from the browser
    await openSample(page, b.url);
    const after = await page.evaluate(() => window.__ft.settings());
    expect(after).toEqual(before);
    await expect(page.locator('.my-looks .look-card', { hasText: 'Series look' })).toBeVisible();
    const prefs = await getJSON(b.url + '/api/prefs');
    expect(prefs.brand).toEqual({ floor: '#123456', ink: '#fedcba' });
    expect(prefs.lastLook).toBe(pick);
    expect(prefs.small).toEqual({ on: true, text: 'MY SERIES' });
    // the brand colours come back in the colour fields too
    await openSection(page, 'colors');
    await expect(page.getByLabel('Floor color')).toHaveValue('#123456');
    await expect(page.getByLabel('Words color')).toHaveValue('#fedcba');
    // and the page really is on another origin
    expect(await page.evaluate(() => location.port)).toBe('3198');
  } finally {
    await page.goto('about:blank');          // the studio polls its server: a page left open on a stopped one logs refusals
    if (a) await stopServer(a);
    if (b) await stopServer(b);
    fs.rmSync(run, { recursive: true, force: true });
  }
});

test('save as my look, then apply it to another take', async ({ page }) => {
  await openSample(page);
  await openSection(page, 'text');
  await page.getByRole('button', { name: 'Type it' }).click();
  await page.getByLabel('Your words').fill('Words that stay with the sample');
  await openSection(page, 'colors');
  await page.locator('.swatch[data-id="brand"]').click();
  await page.getByLabel('Floor color').fill('#203a43');
  await page.getByLabel('Words color').fill('#ffd27a');
  await openSection(page, 'pace');
  await page.getByRole('button', { name: 'Dramatic' }).click();
  await expect.poll(() => page.evaluate(() => window.__ft.settings().pace)).toBe('dramatic');
  const saved = await page.evaluate(() => window.__ft.settings());
  await saveAsMyLook(page, 'Brand series');

  // the look is on the server, without the words
  const looks = await getJSON(page.url().split('#')[0] + 'api/looks');
  expect(looks.length).toBe(1);
  expect(looks[0].name).toBe('Brand series');
  expect(looks[0].settings.text).toBeUndefined();
  expect(looks[0].settings.palette).toMatchObject({ floor: '#203a43', ink: '#ffd27a' });

  // another take: new upload, goes through processing to its own studio
  await page.goto('/');
  await page.locator('input[type=file]').setInputFiles(CLIP_1080);
  await expect(page).toHaveURL(/#\/studio\//, { timeout: 80000 });
  await expect(page.locator('.ft-row').first()).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-ready', '1');
  const take2 = await page.evaluate(() => window.__ft.take().id);
  expect(take2).not.toBe('sample');
  const own = await page.evaluate(() => window.__ft.settings());
  expect(own.text.phrase).not.toBe('Words that stay with the sample');

  await page.locator('.my-looks .look-card', { hasText: 'Brand series' }).click();
  await expect.poll(() => page.evaluate(() => window.__ft.settings().palette.floor)).toBe('#203a43');
  const applied = await page.evaluate(() => window.__ft.settings());
  // everything except the words comes from the look...
  for (const k of ['look', 'font', 'layout', 'entrance', 'camera', 'pace', 'ending', 'fx']) expect(applied[k], k).toEqual(saved[k]);
  expect(applied.palette).toEqual(saved.palette);
  expect(applied.sound.sfx).toBe(saved.sound.sfx);
  // ...and the words stay the take's own
  expect(applied.text).toEqual(own.text);
  await expect(page.locator('.my-looks .look-card', { hasText: 'Brand series' })).toHaveAttribute('aria-pressed', 'true');
  // the take keeps it on the server
  await savedLike(page.url().split('#')[0].replace(/\/$/, ''), take2, (s) => s.palette && s.palette.floor === '#203a43' && s.text.phrase === own.text.phrase);
});

test('delete a saved look', async ({ page }) => {
  await openSample(page);
  await saveAsMyLook(page, 'Keep me');
  await saveAsMyLook(page, 'Temp look');
  const tile = (name) => page.locator('.my-looks .look-card', { hasText: name });
  await expect(page.locator('.my-looks .look-card')).toHaveCount(2);

  // Cancel in the confirm step keeps it
  await page.getByRole('button', { name: 'More for Temp look' }).click();
  await page.getByRole('menuitem', { name: 'Delete' }).click();
  const confirm = page.getByRole('alertdialog', { name: 'Delete this look?' });
  await expect(confirm).toBeVisible();
  await confirm.getByRole('button', { name: 'Cancel' }).click();
  await expect(confirm).toBeHidden();
  await expect(tile('Temp look')).toBeVisible();

  // Delete removes it, here and on the server, and it stays gone after a reload
  await page.getByRole('button', { name: 'More for Temp look' }).click();
  await page.getByRole('menuitem', { name: 'Delete' }).click();
  await page.getByRole('alertdialog', { name: 'Delete this look?' }).getByRole('button', { name: 'Delete' }).click();
  await expect(tile('Temp look')).toHaveCount(0);
  await expect(tile('Keep me')).toBeVisible();
  const base = page.url().split('#')[0];
  expect((await getJSON(base + 'api/looks')).map((l) => l.name)).toEqual(['Keep me']);
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-ready', '1');
  await expect(page.locator('.my-looks .look-card')).toHaveCount(1);
});

test('the name dialog: 30 characters, Cancel, and the same name replaces', async ({ page }) => {
  await openSample(page);
  await page.getByRole('button', { name: 'Save as my look' }).click();
  const dialog = page.getByRole('dialog', { name: 'Name your look' });
  const input = dialog.getByLabel('Look name');
  await expect(input).toBeFocused();
  await input.fill('x'.repeat(45));
  expect(await input.inputValue()).toHaveLength(30);
  await expect(dialog.getByRole('button', { name: 'Save' })).toBeEnabled();
  await input.fill('   ');
  await expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled();
  await dialog.getByRole('button', { name: 'Cancel' }).click();
  await expect(dialog).toBeHidden();
  await expect(page.locator('.my-looks .look-card')).toHaveCount(0);

  await saveAsMyLook(page, 'Series');
  await page.locator('.panel .look-card[data-look]').nth(3).click();
  await page.getByRole('button', { name: 'Save as my look' }).click();
  await dialog.getByLabel('Look name').fill('series');                    // Enter saves; same name, any case, replaces
  await page.keyboard.press('Enter');
  await expect(dialog).toBeHidden();
  await expect(page.locator('.my-looks .look-card')).toHaveCount(1);
  const base = page.url().split('#')[0];
  const looks = await getJSON(base + 'api/looks');
  expect(looks.length).toBe(1);
  expect(looks[0].settings.look).toBe(await page.evaluate(() => window.__ft.settings().look));
});

test('a change is saved even when the page goes away before the 400 ms are up', async ({ page }) => {
  await openSample(page);
  const base = page.url().split('#')[0];
  const ids = await page.evaluate(() => window.FT_DATA.LOOKS.map((l) => l.id));
  await page.locator('.panel .look-card[data-look="' + ids[4] + '"]').click();
  await page.goto('about:blank');
  await expect.poll(async () => (await getJSON(base + 'api/takes/sample/settings')).look, { timeout: 5000 }).toBe(ids[4]);
});

test('a new upload starts from the saved look chosen last', async ({ page }) => {
  await openSample(page);
  await openSection(page, 'colors');
  await page.locator('.swatch[data-id="brand"]').click();
  await page.getByLabel('Floor color').fill('#203a43');
  await page.getByLabel('Words color').fill('#ffd27a');
  await openSection(page, 'pace');
  await page.getByRole('button', { name: 'Dramatic' }).click();
  await expect.poll(() => page.evaluate(() => window.__ft.settings().pace)).toBe('dramatic');
  const saved = await page.evaluate(() => window.__ft.settings());
  await saveAsMyLook(page, 'Series look');
  const base = page.url().split('#')[0];
  const [mine] = await getJSON(base + 'api/looks');
  // pick it: it becomes the last look
  await page.locator('.my-looks .look-card', { hasText: 'Series look' }).click();
  await expect.poll(async () => (await getJSON(base + 'api/prefs')).lastLook).toBe('my:' + mine.id);

  await page.goto('/');
  await page.locator('input[type=file]').setInputFiles(CLIP_1080);
  await expect(page).toHaveURL(/#\/processing\//);
  await expect(page.getByRole('heading', { name: 'Pick a look while you wait' })).toBeVisible();
  // the processing screen only shows the saved look: it must not write the last look over it (it did, 400 ms after opening)
  await page.waitForTimeout(1000);
  expect((await getJSON(base + 'api/prefs')).lastLook).toBe('my:' + mine.id);
  await expect(page.locator('.look-card[aria-pressed="true"]')).toHaveCount(0);

  await expect(page).toHaveURL(/#\/studio\//, { timeout: 80000 });
  await expect(page.locator('html')).toHaveAttribute('data-ready', '1');
  expect(await page.evaluate(() => window.__ft.take().id)).not.toBe('sample');
  const s = await page.evaluate(() => window.__ft.settings());
  const { text: ignoredA, ...got } = s, { text: ignoredB, ...want } = saved;
  // the new take starts from the saved look: everything but the words (the voice switch depends on the take)
  delete got.sound.voice; delete want.sound.voice;
  expect(got).toEqual(want);
  expect(s.text.phrase).not.toBe(saved.text.phrase);
});

test('a settings file we could not read is never written over', async ({ page, request, baseURL }) => {
  // the sample take has a real saved file: Noir
  await openSample(page);
  const noir = (await page.evaluate(() => window.FT_DATA.LOOKS.map((l) => l.id)))[1];
  await page.locator('.panel .look-card[data-look="' + noir + '"]').click();
  await savedLike(baseURL, 'sample', (s) => s.look === noir);
  const before = await getJSON(baseURL + '/api/takes/sample/settings');

  // the next time the studio reads that file, the server fails once (not a 404)
  page.allowConsoleError(/503/);
  let failed = 0;
  await page.route('**/api/takes/sample/settings', async (route) => {
    if (route.request().method() === 'GET' && failed === 0) { failed++; return route.fulfill({ status: 503, contentType: 'application/json', body: '{"error":"busy"}' }); }
    return route.continue();
  });
  await openSample(page);
  expect(failed).toBe(1);
  await expect(page.locator('.toast')).toContainText('Couldn’t load your settings for this take');
  // the studio is open on defaults; a change must not overwrite the real file
  const other = (await page.evaluate(() => window.FT_DATA.LOOKS.map((l) => l.id)))[4];
  await page.locator('.panel .look-card[data-look="' + other + '"]').click();
  await page.waitForTimeout(1200);
  expect(await getJSON(baseURL + '/api/takes/sample/settings')).toEqual(before);
  await page.goto('about:blank');
  await page.waitForTimeout(300);
  expect(await getJSON(baseURL + '/api/takes/sample/settings')).toEqual(before);

  // after a reload the file reads fine again, and saving works
  await openSample(page);
  expect(await page.evaluate(() => window.__ft.settings().look)).toBe(noir);
  await page.locator('.panel .look-card[data-look="' + other + '"]').click();
  await savedLike(baseURL, 'sample', (s) => s.look === other);
});

test('words typed just before leaving the studio are saved, and the dead studio then does nothing', async ({ page, baseURL }) => {
  await openSample(page);
  await openSection(page, 'text');
  await page.getByRole('button', { name: 'Type it' }).click();
  await page.getByLabel('Your words').fill('Typed on the way out');
  await page.getByRole('switch', { name: 'Small line' }).click();            // the small line starts off (Task 16)
  await page.locator('input[aria-label="Small line"]').fill('LAST SECOND');
  await page.evaluate(() => { location.hash = '#/'; });          // both 400 ms typing debounces are still queued
  await expect(page.getByText('Try the sample take')).toBeVisible();
  // what was typed is applied and saved for that take
  await expect.poll(async () => {
    const t = (await getJSON(baseURL + '/api/takes/sample/settings')).text || {};
    return [t.phrase, t.small];
  }, { timeout: 5000 }).toEqual(['Typed on the way out', 'LAST SECOND']);
  await expect.poll(async () => (await getJSON(baseURL + '/api/prefs')).small.text, { timeout: 5000 }).toBe('LAST SECOND');

  // from here the dead studio does nothing: no more writes, no accent change (the fixture also fails on any error it throws)
  await page.waitForTimeout(300);
  const settings = await getJSON(baseURL + '/api/takes/sample/settings');
  const prefs = await getJSON(baseURL + '/api/prefs');
  const accent = await page.evaluate(() => document.documentElement.style.getPropertyValue('--accent'));
  await page.waitForTimeout(1500);
  expect(await getJSON(baseURL + '/api/takes/sample/settings')).toEqual(settings);
  expect(await getJSON(baseURL + '/api/prefs')).toEqual(prefs);
  expect(await page.evaluate(() => document.documentElement.style.getPropertyValue('--accent'))).toBe(accent);
});
