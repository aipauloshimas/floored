// The thumbnail the home screen makes of a clip while it uploads (capturePoster in app/web/js/api.js): a hidden video
// loads the clip, one frame is drawn, and the page gives up after a time limit. Run with `npx playwright test`.
const path = require('path');
const { test, expect, CLIP_1080 } = require('./fixture');

const CLIP_4K = path.join(__dirname, '.fixtures', 'clip_4k.mp4');
const LIMIT_MS = 4500;                         // the thumbnail's own time limit in api.js

// The thumbnail's time limit, set for one test before its page loads; every other timer keeps its time.
async function thumbnailLimit(page, ms) {
  await page.addInitScript(([limit, wanted]) => {
    const real = window.setTimeout;
    window.setTimeout = (fn, t, ...rest) => real(fn, t === limit ? wanted : t, ...rest);
  }, [LIMIT_MS, ms]);
}

// The page's own capturePoster(), given the clip through a file input of the test's own: the home screen's input
// would start an upload too.
async function thumbnailOf(page, clip) {
  await page.evaluate(() => {
    const input = document.createElement('input');
    input.type = 'file';
    input.id = 'thumbnail-clip';
    document.body.appendChild(input);
  });
  await page.locator('#thumbnail-clip').setInputFiles(clip);
  return page.evaluate(async () => {
    const m = await import('/js/api.js');
    return m.capturePoster(document.getElementById('thumbnail-clip').files[0]);
  });
}

test('a clip gets a thumbnail that shows it', async ({ page }) => {
  await thumbnailLimit(page, 60000);           // this test is about the picture: a slow computer gets the time it needs
  await page.goto('/');
  const data = await thumbnailOf(page, CLIP_1080);
  expect(data, 'the thumbnail').toMatch(/^data:image\/jpeg;base64,/);
  // the picture loads, stands tall like the clip, and is a frame of it: a blank frame has one colour
  const seen = await page.evaluate((src) => new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const c = document.createElement('canvas');
      c.width = img.naturalWidth; c.height = img.naturalHeight;
      const cx = c.getContext('2d');
      cx.drawImage(img, 0, 0);
      const colours = new Set();
      for (let y = 8; y < c.height; y += 16) {
        for (let x = 8; x < c.width; x += 16) {
          const p = cx.getImageData(x, y, 1, 1).data;
          colours.add((p[0] >> 4) + ',' + (p[1] >> 4) + ',' + (p[2] >> 4));
        }
      }
      resolve({ w: img.naturalWidth, h: img.naturalHeight, colours: colours.size });
    };
    img.onerror = () => reject(new Error('the thumbnail is not a picture the browser can show'));
    img.src = src;
  }), data);
  expect(seen.w, 'thumbnail width').toBeGreaterThan(0);
  expect(seen.h, 'thumbnail height').toBeGreaterThan(seen.w);
  expect(seen.colours, 'different colours in the thumbnail').toBeGreaterThanOrEqual(8);
});

test('a thumbnail that runs out of time lets go of the clip quietly', async ({ page }) => {
  // what a slow computer does: the time limit passes while the hidden video is still loading the clip
  await thumbnailLimit(page, 1);
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('/');
  const data = await thumbnailOf(page, CLIP_4K);
  // no thumbnail: the limit did pass first (if this fails, LIMIT_MS above no longer matches api.js)
  expect(data, 'the thumbnail when its time limit passes first').toBeNull();
  // A video that still loads a clip whose address was released asks for it again and again, and the browser logs
  // each failure from a quarter of a second on. A video that let go of the clip asks for nothing.
  await page.waitForTimeout(2000);
  expect(errors, 'what the browser logged after the thumbnail gave up').toEqual([]);
});
