'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { L, DATA, METRICS, LOOK_IDS, TAKE, TAKE_10S, S, settings } = require('./load.js');

test('upper-casing is locale-free and keeps accents', () => {
  assert.deepEqual(L.words('você é ação'), ['VOCÊ', 'É', 'AÇÃO']);
  assert.deepEqual(L.words('istanbul straße'), ['ISTANBUL', 'STRASSE']);
});

test('emoji and symbols outside the charset are left out', () => {
  assert.deepEqual(L.words('🔥 free ✨'), ['FREE']);
  assert.deepEqual(L.dropped('🔥 free ✨'), ['🔥', '✨']);
});

test('trailing punctuation dropped, apostrophe curled', () => {
  assert.deepEqual(L.words("Here's how."), ['HERE’S', 'HOW']);
});

test('decomposed accents are composed first, invisible characters are not reported', () => {
  const u = String.fromCharCode;      // written as code units: combining marks and soft hyphens are invisible in an editor
  assert.deepEqual(L.words('voce' + u(0x302) + ' c' + u(0x327) + 'a' + u(0x303) + 'o'), ['VOCÊ', 'ÇÃO']);
  assert.deepEqual(L.words('so' + u(0xad) + 'ft'), ['SOFT']);
  assert.deepEqual(L.dropped(u(0x2764, 0xfe0f) + ' love'), [u(0x2764)]);
});

test('a combining mark that joins nothing is reported, one inside a left-out character is not', () => {
  const u = String.fromCharCode;
  assert.deepEqual(L.words('x' + u(0x301)), ['X']);
  assert.deepEqual(L.dropped('x' + u(0x301)), [u(0x301)]);                       // "x" + acute: no such letter, the mark is lost
  assert.deepEqual(L.dropped('voce' + u(0x302) + ' ok'), []);                     // composes into ê: nothing lost
  assert.deepEqual(L.dropped(u(0x2764, 0xfe0f, 0x200d, 0x2728) + ' hi'), [u(0x2764), u(0x2728)]);   // variation selector and joiner: invisible
  assert.deepEqual(L.dropped(u(0x1f44d, 0x1f3fd) + ' ok'), [u(0x1f44d), u(0x1f3fd)]);
  assert.deepEqual(L.dropped('x' + u(0x301, 0x301) + ' y' + u(0x301)), [u(0x301)]);                 // each reported once
});

test('Polish and other Latin Extended-A letters are kept', () => {
  assert.deepEqual(L.words('żółć łódź'), ['ŻÓŁĆ', 'ŁÓDŹ']);
  assert.deepEqual(L.dropped('żółć łódź'), []);
});

test('a lower-case letter whose capital is outside the charset stays as it is', () => {
  assert.deepEqual(L.words('µm'), ['µM']);
});

test('the kept characters are exactly the ones every font table measures', () => {
  const cps = [];
  for (let c = 0x20; c <= 0x17f; c++) cps.push(c);
  cps.push(0x2018, 0x2019, 0x201c, 0x201d, 0x2013, 0x2014, 0x2026, 0x20ac, 0x2022, 0x3b1, 0x1f525);
  for (const font of Object.keys(DATA.FONTS)) {
    for (const c of cps) {
      const ch = String.fromCodePoint(c);
      assert.equal(L.keeps(ch), METRICS[font].w[ch] !== undefined, font + ' U+' + c.toString(16));
    }
  }
});

test('hero is upper-cased the same way as the words', () => {
  const s = settings('original', 'wall', 'você precisa de ação');
  s.text.hero = 'ação';
  assert.equal(L.build(TAKE, s).hero.text, 'AÇÃO');
});

test('every look x layout builds finite rows', () => {
  for (const look of LOOK_IDS) for (const layout of ['wall', 'stripes', 'giant', 'poster'])
    for (const phrase of ['Você não precisa de After Effects', 'Żółć łódź', 'FREE', 'inconstitucionalissimamente incrível']) {
      const d = L.build(TAKE, settings(look, layout, phrase));
      assert.ok(d.rows.length > 0);
      for (const r of d.rows) assert.ok([r.left, r.top, r.s, r.fontSize].every(Number.isFinite));
    }
});

test('every font measures accented text with finite widths', () => {
  for (const font of Object.keys(DATA.FONTS)) {
    const w = L.width('ŻÓŁĆ VOCÊ AÇÃO ŚŹŃ', font, 100);
    assert.ok(Number.isFinite(w) && w > 0, font);
  }
});

test('build is deterministic', () => assert.deepEqual(L.build(TAKE, S), L.build(TAKE, S)));

test('a 10 s take: the camera move keeps its length', () => assert.ok(L.build(TAKE_10S, S).timing.Tc <= 4.6));
