'use strict';
// Loads the engine's pure modules (data.js, metrics.js, layout.js) with vm, the way the browser does (window = the global
// object), and hands back what the tests need. They run in this realm so arrays they return compare with deepEqual.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const APP = path.resolve(__dirname, '..', '..', 'plugin', 'skills', 'floored', 'app');
const ENGINE = path.join(APP, 'web', 'engine');

function load() {
  globalThis.window = globalThis;
  for (const f of ['data.js', 'metrics.js', 'layout.js']) {
    vm.runInThisContext(fs.readFileSync(path.join(ENGINE, f), 'utf8'), { filename: f });
  }
  return globalThis.window;
}

const w = load();
const L = w.FTLayout;
const DATA = w.FT_DATA;
const METRICS = w.FT_METRICS;
const LOOK_IDS = DATA.LOOKS.map((l) => l.id);
const TAKE = JSON.parse(fs.readFileSync(path.join(APP, 'sample', 'take.json'), 'utf8'));
const TAKE_10S = Object.assign({}, TAKE, { dur: 10 });
const PHRASE = TAKE.transcript;

// settings(look, layout, phrase): a look's own settings with the layout and the phrase swapped in
function settings(look, layout, phrase) {
  const s = DATA.lookSettings(look, { source: 'typed', phrase: phrase == null ? PHRASE : phrase, hero: 'FREE', small: 'IN CLAUDE CODE' });
  if (layout) s.layout = layout;
  return s;
}
const S = settings('original', 'wall', PHRASE);

module.exports = { load, L, DATA, METRICS, LOOK_IDS, TAKE, TAKE_10S, S, settings, APP, ENGINE };
