'use strict';
// The film grain is meant to be deterministic: the studio at seek(t) and the exported frame n must lay the same noise,
// pixel for pixel, on a canvas of the same size. Task 24 (round 1) checked this in a real browser (the grain canvas read
// back in the studio and in the export page: identical at frames 14, 48 and 110) and found the engine innocent: the
// differences between the studio and the exported mp4 come from the video encoder, not from the engine. This test pins
// the engine side so that nobody can break it unseen.
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { APP, ENGINE } = require('./load.js');          // load.js has put data.js, metrics.js and layout.js on window

vm.runInThisContext(fs.readFileSync(path.join(ENGINE, 'engine.js'), 'utf8'), { filename: 'engine.js' });
const G = globalThis.window.Floored.grain;

const W = 540, H = 960;                                // the grain canvas, in the studio and in the export composition
// sha1 of the RGBA bytes of each noise frame at 540x960, taken from the engine before grainFill/grainIndex were split out
const PIXELS = [
  '4a165c8c9fdbc5700e8b010439e8395e28b13299',
  '6470aeaffa06cdcb0a73c88ae800fc42a4c225bf',
  'de960b088c3a5d58982ec9e3859743c47e756d44',
  '999daaba4abad3991f448cdffc653a16464c7cab',
  'c50cd1b5781170502594560aca23d1b2aa9c081b',
  '7264d4eecd1d3d4a349f885c59ad5f0014024bb5'
];
const sha = (bytes) => crypto.createHash('sha1').update(bytes).digest('hex');
const frame = (idx) => G.fill(new Uint8ClampedArray(W * H * 4), idx);   // a canvas ImageData.data is a Uint8ClampedArray

test('there are six grain frames and each one is the same bytes every time', () => {
  assert.equal(G.frames, 6);
  for (let i = 0; i < G.frames; i++) {
    assert.equal(sha(frame(i)), PIXELS[i], 'noise frame ' + i);
    assert.equal(sha(frame(i)), sha(frame(i)), 'noise frame ' + i + ' twice');
  }
  assert.equal(new Set(PIXELS).size, 6, 'the six frames differ from each other');
});

test('the grain frame is the film frame number modulo six, whatever the frame rate', () => {
  for (const fps of [24, 25, 30, 60, 24000 / 1001, 30000 / 1001]) {
    for (let n = 0; n < 400; n++) {
      assert.equal(G.index(n / fps, fps), n % 6, 'frame ' + n + ' at ' + fps + ' fps');
      // a seek that lands a little before or after the frame's own time still means that frame (no flicker to a neighbour)
      assert.equal(G.index((n + 0.3) / fps, fps), n % 6);
      assert.equal(G.index((n - 0.3) / fps, fps) + 0, n % 6);   // + 0: Math.round(-0.3) is -0, which indexes like 0
    }
  }
});

test('the instants the acceptance run compares map to the same grain in the studio and in the export', () => {
  // the export draws frame n at t = n / fps; the studio is seeked to that same t: frames 14, 48 and 110 of the 24 fps sample
  assert.deepEqual([14, 48, 110].map((n) => G.index(n / 24, 24)), [2, 0, 2]);
});

test('a negative time still picks a valid grain frame', () => {
  for (const t of [-0.04, -1, -3.7]) {
    const i = G.index(t, 24);
    assert.ok(Number.isInteger(i) && i >= 0 && i < 6, 'index ' + i + ' at t=' + t);
  }
});

test('the studio and the export composition give the grain canvas the same size', () => {
  const want = '<canvas class="ft-grain" width="' + W + '" height="' + H + '"></canvas>';
  const studio = fs.readFileSync(path.join(APP, 'web', 'js', 'preview.js'), 'utf8');
  const render = fs.readFileSync(path.join(ENGINE, 'composition.html'), 'utf8');
  assert.ok(studio.includes(want), 'preview.js builds a different grain canvas');
  assert.ok(render.includes(want), 'composition.html builds a different grain canvas');
});
