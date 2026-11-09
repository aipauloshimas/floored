// The shared Playwright fixture for the studio specs (smoke.spec.js, persistence.spec.js).
const base = require('@playwright/test');
const expect = base.expect;
const path = require('path');

// Every test fails on a page error, a console error, or anything the app caught into window.__ft.log. The studio swallows
// errors from its callbacks into that log, so a ReferenceError there would otherwise pass unseen.
// The studio keeps its settings on the server (Task 15), so the 3199 server would carry one test's look and phrase into the
// next one: each test starts from a server reset to defaults (no saved looks, no brand, the sample's settings cleared).
const test = base.test.extend({
  page: async ({ page, request, baseURL }, use) => {
    await resetServer(request, baseURL);
    const seen = [], allowed = [];
    // a test that breaks a request on purpose says which console error that causes: page.allowConsoleError(/regex/)
    page.allowConsoleError = (re) => allowed.push(re);
    page.on('pageerror', (e) => seen.push('pageerror: ' + e.message));
    page.on('console', (m) => { if (m.type() === 'error' && !allowed.some((re) => re.test(m.text()))) seen.push('console.error: ' + m.text()); });
    await use(page);
    const logged = await page.evaluate(() => (window.__ft && window.__ft.log) || []).catch(() => []);
    expect(seen, 'uncaught page errors').toEqual([]);
    expect(logged, 'errors the app caught into window.__ft.log').toEqual([]);
  }
});

// no Origin header on these requests, which the server accepts for mutations
async function resetServer(request, baseURL) {
  const looks = await (await request.get(baseURL + '/api/looks')).json();
  for (const l of looks) await request.delete(baseURL + '/api/looks/' + l.id);
  await request.put(baseURL + '/api/prefs', { data: { lastLook: 'original', brand: null, small: { on: false, text: '' } } });
  const takes = await (await request.get(baseURL + '/api/takes')).json();
  for (const t of (takes.takes || takes || [])) {
    const id = t.take ? t.take.id : t.id;
    if (id) await request.put(baseURL + '/api/takes/' + encodeURIComponent(id) + '/settings', { data: {} });
  }
}

const CLIP_1080 = path.join(__dirname, '.fixtures', 'clip_1080.mp4');

// the page's own copy of the engine data: the expected floor colour of every look comes from here, never hard-coded
async function readLooks(page) {
  return page.evaluate(() => window.FT_DATA.LOOKS.map((l) => {
    const pal = window.FT_DATA.PALETTES.find((p) => p.id === l.palette);
    const n = parseInt(pal.floor.replace('#', ''), 16);
    return { id: l.id, label: l.label, floor: 'rgb(' + [(n >> 16) & 255, (n >> 8) & 255, n & 255].join(', ') + ')' };
  }));
}

async function openSample(page, baseURL) {
  await page.goto((baseURL || '') + '/');
  await page.getByText('Try the sample take').click();
  await expect(page).toHaveURL(/#\/studio\/sample/);
  await expect(page.locator('.ft-row').first()).toBeVisible();
  await expect(page.locator('html')).toHaveAttribute('data-ready', '1');
}

module.exports = { test, expect, CLIP_1080, readLooks, openSample };
