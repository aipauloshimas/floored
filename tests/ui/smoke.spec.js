// Studio smoke tests: they pin what the creator sees, so app/web/studio.js could be split into modules (Task 14) and
// Tasks 15-17 can change it safely. Run with `npx playwright test` (see playwright.config.js).
const { test, expect, CLIP_1080, readLooks, openSample } = require('./fixture');

test('home → sample → studio shows the floor', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Stand on your own words.' })).toBeVisible();
  await page.getByText('Try the sample take').click();
  await expect(page.locator('.ft-row').first()).toBeVisible();
  expect(await page.evaluate(() => window.__ft.screen())).toBe('studio');
  expect(await page.evaluate(() => window.__ft.take().id)).toBe('sample');
});

test('every ready look paints rows in its floor colour', async ({ page }) => {
  await openSample(page);
  const looks = await readLooks(page);
  expect(looks.length).toBe(6);
  const tiles = page.locator('.panel .look-card');
  await expect(tiles).toHaveCount(6);
  for (const look of looks) {
    await page.locator('.panel .look-card[data-look="' + look.id + '"]').click();
    await expect(page.locator('.panel .look-card[data-look="' + look.id + '"]')).toHaveAttribute('aria-pressed', 'true');
    await expect.poll(() => page.evaluate(() => window.__ft.settings().look), { message: look.id + ' look is the current one' }).toBe(look.id);
    // the engine repaints after the settings change: rows must exist and the root carries the look's floor
    await expect.poll(() => page.locator('.ft-row').count(), { message: look.id + ' rows' }).toBeGreaterThan(0);
    await expect.poll(() => page.locator('.ft-root').evaluate((el) => getComputedStyle(el).backgroundColor), { message: look.id + ' floor' })
      .toBe(look.floor);
  }
});

test('typing a phrase updates the floor', async ({ page }) => {
  await openSample(page);
  await page.locator('#acc-text').click();
  await page.getByRole('button', { name: 'Type it' }).click();
  const area = page.getByLabel('Your words');
  await area.fill('Stand on your words');
  await expect.poll(() => page.evaluate(() => window.__ft.settings().text.phrase)).toBe('Stand on your words');
  await expect.poll(() => page.locator('.ft-floor').evaluate((el) => el.textContent.toUpperCase().replace(/\s+/g, ' ')))
    .toContain('STAND');
  await expect.poll(() => page.locator('.ft-floor').evaluate((el) => el.textContent.toUpperCase())).toContain('WORDS');
  await expect(page.locator('.ft-row').first()).toBeVisible();
});

test('an upload goes through processing to the studio', async ({ page }) => {
  await page.goto('/');
  await page.locator('input[type=file]').setInputFiles(CLIP_1080);
  await expect(page).toHaveURL(/#\/processing\//);
  await expect(page.getByRole('heading', { name: 'Pick a look while you wait' })).toBeVisible();
  expect(await page.evaluate(() => window.__ft.screen())).toBe('processing');
  await expect(page.locator('.look-card')).toHaveCount(6);
  await expect(page).toHaveURL(/#\/studio\//, { timeout: 80000 });
  await expect(page.locator('.ft-row').first()).toBeVisible();
  expect(await page.evaluate(() => window.__ft.screen())).toBe('studio');
});

test('the export dialog shows the output line', async ({ page }) => {
  await openSample(page);
  await page.getByRole('button', { name: 'Export' }).click();
  await expect(page.getByRole('dialog', { name: 'Export your intro' })).toBeVisible();
  await expect(page.locator('.format-line')).toContainText(/MP4 · 1080 × 1920 · 24 fps/);
  expect(await page.evaluate(() => window.__ft.screen())).toBe('export');
});

test('the test hook seeks the live preview', async ({ page }) => {
  await openSample(page);
  await page.evaluate(() => window.__ft.seek(2));
  expect(await page.evaluate(() => window.__ft.studio.preview.time())).toBeCloseTo(2, 1);
  expect(await page.evaluate(() => typeof window.__ft.settings().look)).toBe('string');
});

test('the export dialog closes with Escape, the Close button and the backdrop, and reopens', async ({ page }) => {
  await openSample(page);
  const dialog = page.getByRole('dialog', { name: 'Export your intro' });
  const open = async () => {
    await page.getByRole('button', { name: 'Export' }).click();
    await expect(dialog).toBeVisible();
    await expect(page).toHaveURL(/#\/export\/sample/);
  };
  const closed = async (how) => {
    await expect(dialog, how + ': dialog hidden').toBeHidden();
    await expect(page, how + ': back in the studio').toHaveURL(/#\/studio\/sample$/);
    expect(await page.evaluate(() => window.__ft.screen()), how).toBe('studio');
  };
  await open();
  await page.keyboard.press('Escape');
  await closed('Escape');
  await open();
  await dialog.getByRole('button', { name: 'Close' }).click();
  await closed('Close button');
  await open();
  await page.locator('.modal-backdrop').click({ position: { x: 4, y: 4 } });
  await closed('backdrop');
  await open();
  await page.keyboard.press('Escape');
  await closed('Escape again');
});
