'use strict';
// The unaccented phrases whose layout must never change when accent headroom is added: cases() lists them as
// [key, take, settings]; hashOf() fingerprints a build. dev/gen_layout_baseline.js stored the fingerprints from the engine
// as it was before the headroom (commit 0fa343e); tests/js/headroom.test.js compares today's engine against them.
const crypto = require('node:crypto');
const { L, DATA, LOOK_IDS, TAKE, TAKE_10S, settings } = require('./load.js');

const PHRASES = [TAKE.transcript].concat(DATA.SUGGESTIONS, ['FREE', 'This text is on the floor and every word of it is free to use in your own videos.']);
const LAYOUTS = ['wall', 'stripes', 'giant', 'poster'];

function cases() {
  const out = [];
  LOOK_IDS.forEach((look) => LAYOUTS.forEach((layout) => PHRASES.forEach((phrase, p) => {
    const base = settings(look, layout, phrase);
    out.push([look + '/' + layout + '/' + p + '/default', TAKE, base]);
    const bare = JSON.parse(JSON.stringify(base));
    bare.text.hero = ''; bare.text.small = '';
    out.push([look + '/' + layout + '/' + p + '/bare', TAKE_10S, bare]);
    const sp = JSON.parse(JSON.stringify(base));
    sp.pace = 'speech'; sp.text.source = 'speech';
    out.push([look + '/' + layout + '/' + p + '/speech', TAKE_10S, sp]);
  })));
  return out;
}

function hashOf(take, s) {
  return crypto.createHash('sha1').update(JSON.stringify(L.build(take, s))).digest('hex').slice(0, 12);
}

module.exports = { cases, hashOf, PHRASES, LAYOUTS };
