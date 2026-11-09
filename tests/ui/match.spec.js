// Preview vs export (Task 24, design 15.3): "every ready look exports, and the export matches the studio preview at three
// instants". For each of the 6 looks the test opens the sample, picks the look, photographs the studio stage at t = 0.6, 2.0
// and 4.6 (window.__ft.seek), presses the real Export button and waits for the render, then pulls the same three frames out
// of the exported mp4. Both sides are scaled to 540x960 with ffmpeg and compared with ffmpeg's `ssim` filter ("All:", as
// tests/py/imgcmp.py does). The bar is SSIM >= 0.95 and is a design threshold: never loosen it. A look under the bar fails
// the test and the numbers and PNGs say where.
//
// SLOW (6 real renders, about 2 to 7 min each on a shared PC): it is not in `npx playwright test`. Run it with `npm run test:match`
// (playwright.match.config.js; see the notes there). Output lands in FT_MATCH_OUT (the config prints nothing; the path is
// <tmp>/ft-match-*/out unless you set it): studio-<look>-<t>.png, export-<look>-<t>.png, <look>.mp4 and match-results.json.
//
// The instants: 0.6 and 4.6 are not frame times at 24 fps. The export frame is the one at or before t (frame 14 = 0.583 s,
// 48 = 2.0 s, 110 = 4.583 s) and the studio is asked for that very frame time, so the comparison is one frame against the
// same frame, not against 17 ms of motion in between. The instant used is recorded next to every score.
const { spawnSync } = require('child_process');
const fs = require('fs');
const path = require('path');
const { test, expect, openSample } = require('./fixture');

const MIN_SSIM = 0.95;                       // design 15.3; never loosen
const INSTANTS = [0.6, 2.0, 4.6];
const W = 540, H = 960;
const OUT = process.env.FT_MATCH_OUT || path.join(require('os').tmpdir(), 'ft-match-out');
const RESULTS = path.join(OUT, 'match-results.json');

// the six looks, read from the engine's own data file (so a new look is picked up without editing this spec)
function lookIds() {
  const src = fs.readFileSync(path.join(__dirname, '..', '..', 'plugin', 'skills', 'floored', 'app', 'web', 'engine', 'data.js'), 'utf8');
  const win = {};
  new Function('window', src)(win);
  return win.FT_DATA.LOOKS.map((l) => l.id);
}
const ONLY = (process.env.FT_MATCH_LOOKS || '').split(',').map((s) => s.trim()).filter(Boolean);
const LOOKS = lookIds().filter((id) => !ONLY.length || ONLY.includes(id));

function ffmpeg(args) {
  const r = spawnSync('ffmpeg', ['-hide_banner', '-nostdin', '-loglevel', 'info', '-y', ...args], { encoding: 'utf8', windowsHide: true });
  if (r.status !== 0) throw new Error('ffmpeg failed: ' + String(r.stderr).slice(-500));
  return r.stderr;
}
function ssim(a, b) {
  const err = ffmpeg(['-i', a, '-i', b, '-lavfi',
    `[0:v]scale=${W}:${H}:flags=lanczos,format=rgb24[a];[1:v]scale=${W}:${H}:flags=lanczos,format=rgb24[b];[a][b]ssim`, '-f', 'null', '-']);
  const m = /All:([0-9.]+)/.exec(err);
  if (!m) throw new Error('ffmpeg printed no SSIM: ' + err.slice(-300));
  return parseFloat(m[1]);
}
function exportFrame(mp4, n, png) {
  ffmpeg(['-i', mp4, '-vf', `select=eq(n\\,${n})`, '-vsync', '0', '-frames:v', '1', png]);
  if (!fs.existsSync(png)) throw new Error('no frame ' + n + ' in ' + mp4);
  return png;
}
function record(entry) {
  let all = {};
  try { all = JSON.parse(fs.readFileSync(RESULTS, 'utf8')); } catch (e) { /* first look */ }
  all[entry.look] = entry;
  fs.writeFileSync(RESULTS, JSON.stringify(all, null, 2));
}

test.use({ deviceScaleFactor: 2 });
fs.mkdirSync(OUT, { recursive: true });

for (const look of LOOKS) {
  test(`${look}: the export matches the studio at ${INSTANTS.join(', ')} s`, async ({ page, baseURL }) => {
    await openSample(page, baseURL);
    const fps = await page.evaluate(() => window.__ft.take().fps);
    await page.locator('.panel .look-card[data-look="' + look + '"]').click();
    await expect.poll(() => page.evaluate(() => window.__ft.settings().look)).toBe(look);
    // Photograph the stage as the engine drew it: 540x960 CSS px at device scale 2 is 1080x1920 real pixels (the export's
    // own size), with no rounded corners or shadow. The studio fits the stage to the window with a fractional scale, which
    // would blur the comparison; the !important rules pin it, and survive the studio's own resize handler.
    await page.addStyleTag({ content: '.stage{width:540px !important;height:960px !important;border-radius:0 !important;box-shadow:none !important}'
      + '.stage-col{width:540px !important}.stage .ft-root{transform:scale(0.5) !important}' });
    const stage = page.locator('.stage');
    await expect.poll(async () => { const b = await stage.boundingBox(); return b ? Math.round(b.width) + 'x' + Math.round(b.height) : ''; }).toBe('540x960');

    const shots = [];
    for (const t of INSTANTS) {
      const n = Math.floor(t * fps + 1e-6);
      const ts = n / fps;
      await page.evaluate((x) => window.__ft.seek(x), ts);
      // seeking the person's alpha video is slow (it can take seconds on a busy laptop): the picture is only the right one
      // once both videos have finished their seek
      await page.waitForFunction((x) => ['.ft-pv', '.ft-sv'].every((q) => {
        const v = document.querySelector(q);
        return !v || (!v.seeking && v.readyState >= 2 && Math.abs(v.currentTime - x) < 0.02);
      }), ts, { timeout: 60000 });
      await page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
      await page.waitForTimeout(300);                       // the compositor shows the new video frame
      const png = path.join(OUT, `studio-${look}-${t}.png`);
      await stage.screenshot({ path: png, animations: 'disabled' });
      shots.push({ t, n, ts, png });
    }

    // the real Export button, then Render
    await page.getByRole('button', { name: 'Export' }).click();
    const dialog = page.getByRole('dialog', { name: 'Export your intro' });
    await expect(dialog).toBeVisible();
    const started = Date.now();
    await dialog.getByRole('button', { name: 'Render' }).click();
    await expect(dialog.locator('.result-title')).toHaveText('Your intro is ready', { timeout: 25 * 60 * 1000 });
    const renderSec = Math.round((Date.now() - started) / 1000);
    const mp4 = await dialog.locator('code.path').getAttribute('title');
    expect(mp4 && fs.existsSync(mp4), 'the export file exists: ' + mp4).toBeTruthy();
    const kept = path.join(OUT, `${look}.mp4`);
    fs.copyFileSync(mp4, kept);

    const scores = [];
    for (const s of shots) {
      const exp = exportFrame(kept, s.n, path.join(OUT, `export-${look}-${s.t}.png`));
      scores.push({ t: s.t, frame: s.n, at: +s.ts.toFixed(4), ssim: +ssim(s.png, exp).toFixed(4) });
    }
    record({ look, export: mp4, renderSec, minSsim: MIN_SSIM, scores });
    console.log(look + ' SSIM ' + scores.map((s) => `t=${s.t} (frame ${s.frame}) ${s.ssim}`).join(', ') + ` [render ${renderSec}s]`);
    for (const s of scores) expect(s.ssim, `${look} at t=${s.t}: SSIM ${s.ssim}, studio-${look}-${s.t}.png vs export-${look}-${s.t}.png in ${OUT}`).toBeGreaterThanOrEqual(MIN_SSIM);
  });
}
