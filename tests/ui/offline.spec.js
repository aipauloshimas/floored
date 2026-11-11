// When the studio's local server is gone (it exits after 2 hours idle, or the computer slept), the page says so, keeps what
// the creator changed, and sends it when the server answers again. The dead server is simulated with page.route(...abort):
// the suite shares ONE server on port 3199, so it is never stopped.
const { test, expect, openSample } = require('./fixture');

const API = '**/api/**';
const dead = (route) => route.abort();
const BANNER_TEXT = 'The studio stopped. Go back to Claude and say: open floored again.';
const banner = (page) => page.getByRole('status').filter({ hasText: 'The studio stopped' });

test.beforeEach(({ page }) => { page.allowConsoleError(/Failed to load resource|ERR_FAILED|net::ERR/); });

test('the banner shows on the home screen while the server cannot be reached, and goes away when it answers', async ({ page }) => {
  await page.route(API, dead);
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Stand on your own words.' })).toBeVisible();
  await expect(banner(page)).toBeVisible();
  await expect(banner(page)).toHaveText(BANNER_TEXT);
  await page.unroute(API, dead);
  await expect(banner(page)).toBeHidden({ timeout: 8000 });     // it asks again every 3 s
});

test('a change made while the server is gone is saved once the server is back', async ({ page }) => {
  await openSample(page);
  await expect(banner(page)).toBeHidden();
  await page.route(API, dead);
  await page.locator('.panel .look-card[data-look="sage-red"]').or(page.locator('.panel .look-card').nth(2)).first().click();
  const look = await page.evaluate(() => window.__ft.settings().look);
  await expect(banner(page)).toBeVisible();
  await expect(banner(page)).toHaveText(BANNER_TEXT);
  // still gone a few seconds later: the banner stays (it is not a toast)
  await page.waitForTimeout(4500);
  await expect(banner(page)).toBeVisible();
  const saved = page.waitForRequest((r) => r.method() === 'PUT' && /\/api\/takes\/sample\/settings$/.test(r.url()), { timeout: 12000 });
  await page.unroute(API, dead);
  const req = await saved;
  expect(JSON.parse(req.postData()).look).toBe(look);
  await expect(banner(page)).toBeHidden({ timeout: 8000 });
  // the server really has it
  await expect.poll(async () => (await (await page.request.get('/api/takes/sample/settings')).json()).look).toBe(look);
});

test('a failed save says the change is kept, not that it is lost', async ({ page }) => {
  await openSample(page);
  await page.route(API, dead);
  await page.locator('.panel .look-card').nth(2).click();
  const toast = page.locator('.toast.show.error');
  await expect(toast).toBeVisible();
  await expect(toast).not.toContainText('not saved');
  await expect(toast).toContainText('saved when the studio is back');
});

test('with the banner up the Export dialog does not offer a Try again that cannot work', async ({ page }) => {
  await openSample(page);
  await page.getByRole('button', { name: 'Export' }).click();
  const dialog = page.getByRole('dialog', { name: 'Export your intro' });
  await expect(dialog).toBeVisible();
  await page.route(API, dead);
  await dialog.getByRole('button', { name: 'Render', exact: true }).click();
  await expect(dialog.getByText('The render did not finish')).toBeVisible();
  await expect(banner(page)).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Try again' })).toHaveCount(0);
  await expect(dialog).not.toContainText('Your settings are safe');
  await expect(dialog).not.toContainText('Is it still running');
  await expect(dialog).toContainText('kept on this page');
  await expect(dialog).toContainText('saved when the studio is back');
  // back again: the dialog offers Try again
  await page.unroute(API, dead);
  await expect(banner(page)).toBeHidden({ timeout: 8000 });
  await expect(dialog.getByRole('button', { name: 'Try again' })).toBeVisible();
});

for (const vp of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
  test('the banner fits at ' + vp.width + 'px: no sideways scroll, the Export button stays reachable', async ({ page }) => {
    await page.setViewportSize(vp);
    await openSample(page);
    await page.route(API, dead);
    await page.locator('.panel .look-card').nth(2).click();
    await expect(banner(page)).toBeVisible();
    const m = await page.evaluate(() => {
      const b = document.querySelector('[role=status].ft-banner').getBoundingClientRect();
      const e = [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === 'Export').getBoundingClientRect();
      return { bottom: b.bottom, top: b.top, exportTop: e.top, sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth };
    });
    expect(m.top).toBe(0);
    expect(m.exportTop).toBeGreaterThanOrEqual(m.bottom - 0.5);
    expect(m.sw).toBeLessThanOrEqual(m.cw);
  });
}
