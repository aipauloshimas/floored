'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { L, DATA, METRICS, LOOK_IDS, TAKE, TAKE_10S, settings, APP } = require('./load.js');
const { cases, hashOf } = require('./unaccented.js');

// ---------------------------------------------------------------- the accent marks get room, nothing else moves
test('an unaccented phrase lays out exactly as it did before the accent headroom', () => {
  const stored = JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', 'unaccented-layout.json'), 'utf8'));
  const all = cases();
  assert.equal(all.length, Object.keys(stored).length);
  const changed = all.filter(([key, take, s]) => hashOf(take, s) !== stored[key]).map((c) => c[0]);
  assert.deepEqual(changed, []);
});

test('only letters that carry a mark have a rise, in every font', () => {
  for (const [id, m] of Object.entries(METRICS)) {
    assert.ok(m.t, id + ' has no t table');
    for (const plain of 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,!?') assert.equal(m.t[plain], undefined, id + ' ' + plain);
    for (const marked of 'ÊÃÓŻŚĄ') if (marked !== 'Ą') assert.ok(m.t[marked] > 0.1, id + ' ' + marked + ' ' + m.t[marked]);
    assert.equal(m.t['Ą'], undefined, id + ': an ogonek hangs below the baseline, it adds nothing on top');
    assert.equal(m.t['Ç'], undefined, id + ': a cedilla hangs below the baseline, it adds nothing on top');
    for (const [ch, v] of Object.entries(m.t)) assert.ok(v >= 0.04 && v < 0.5 && L.keeps(ch), id + ' ' + ch + ' ' + v);
  }
});

test('only letters with a cedilla, ogonek or comma below have a depth, in every font', () => {
  for (const [id, m] of Object.entries(METRICS)) {
    assert.ok(m.b, id + ' has no b table');
    for (const plain of 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.,!?') assert.equal(m.b[plain], undefined, id + ' ' + plain);
    for (const above of 'ÊÃÓŻŚÁÀÔ') assert.equal(m.b[above], undefined, id + ' ' + above + ': marks above the letter add nothing below');
    for (const below of 'ÇĄĘŞŢŲĶĻŅŖ') assert.ok(m.b[below] > 0.06 && m.b[below] < 0.5, id + ' ' + below + ' ' + m.b[below]);
    for (const [ch, v] of Object.entries(m.b)) assert.ok(v >= 0.04 && v < 0.5 && L.keeps(ch), id + ' ' + ch + ' ' + v);
  }
  // a font without the glyph is drawn by Inter scaled by fbAdj: Gochi Hand has no Ą, so its depth is Inter's, times fbAdj
  assert.ok(METRICS.hand.b['Ą'] > 0.04);
  assert.ok(METRICS.hand.b['Ą'] < METRICS.condensed.b['Ą']);
});

// the top of the tallest accent in `text`, in px, from the same numbers the engine draws with: the font's rise (em) times
// the row's font-size. A row's cap top is its `top`, so the marks reach to top - rise.
function headPx(text, fontId, fontSize) {
  let em = 0;
  for (const ch of text) em = Math.max(em, METRICS[fontId].t[ch] || 0);
  return em * fontSize;
}

// how far the marks under the baseline of `text` reach below it, in px (same numbers as headPx, from the b table)
function lowPx(text, fontId, fontSize) {
  let em = 0;
  for (const ch of text) em = Math.max(em, METRICS[fontId].b[ch] || 0);
  return em * fontSize;
}

const PHRASES = [
  { phrase: 'Você não precisa de After Effects', hero: 'FREE', small: 'IN CLAUDE CODE' },
  { phrase: 'ŻÓŁĆ ŚĄŹ', hero: 'ŚĄŹ', small: 'IN CLAUDE CODE' },
  { phrase: 'Você não precisa de After Effects, ŻÓŁĆ ŚĄŹ', hero: 'AÇÃO', small: 'GRÁTIS NO CLAUDE' },
  { phrase: 'AÇÃO ŞEKER ĘĄ ŢĘ ŲĶĻŅ', hero: 'ŞEKER', small: 'ÇOK ŞEKER' }
];

// rows that are stacked in one plane, top to bottom. Left out: the hero column (rotated, its marks point sideways) and the
// small line, which sits over the wall's filler rows when the phrase is short and on a plate over the big word in giant
// and poster, by design (it is checked on its own below, against the rows that are not fillers).
function stack(rows) {
  const flat = rows.filter((r) => r.kind !== 'hero' && r.kind !== 'small').sort((a, b) => a.top - b.top);
  const groups = [];   // rows with the same top are one line (the part left of the hero column)
  for (const r of flat) {
    const g = groups[groups.length - 1];
    if (g && g.top === r.top) { g.rows.push(r); g.bottom = Math.max(g.bottom, r.top + L.CAP * r.s); } else groups.push({ top: r.top, bottom: r.top + L.CAP * r.s, rows: [r] });
  }
  return groups;
}

for (const P of PHRASES) {
  test('accent marks stay clear of the row above: ' + P.phrase, () => {
    let checked = 0;
    for (const look of LOOK_IDS) {
      for (const layout of ['wall', 'stripes', 'giant', 'poster']) {
        const s = settings(look, layout, P.phrase);
        s.text.hero = P.hero; s.text.small = P.small;
        const res = L.build(TAKE, s);
        const g = stack(res.rows);
        for (let i = 1; i < g.length; i++) {
          const head = Math.max.apply(null, g[i].rows.map((r) => headPx(r.text, res.fontId, r.fontSize)));
          const clear = g[i].top - head - g[i - 1].bottom;
          assert.ok(clear >= -0.011, look + '/' + layout + ': row at ' + g[i].top + ' reaches ' + (-clear).toFixed(1) + 'px into the row above (marks ' + head.toFixed(1) + 'px)');
          checked++;
        }
        const sm = res.rows.find((r) => r.kind === 'small');
        if (sm && !sm.plate) {
          const head = headPx(sm.text, res.fontId, sm.fontSize);
          const above = res.rows.filter((r) => r.kind !== 'hero' && r.kind !== 'filler' && r.kind !== 'small' && r.top < sm.top);
          assert.ok(above.length > 0);
          for (const r of above) assert.ok(sm.top - head >= r.top + L.CAP * r.s - 0.011, look + '/' + layout + ': the small line reaches into ' + r.id);
          checked++;
        }
      }
    }
    assert.ok(checked > 100, 'compared ' + checked + ' neighbours');
  });
}

for (const P of PHRASES) {
  test('marks below the baseline stay clear of the row below: ' + P.phrase, () => {
    let checked = 0, withLow = 0;
    for (const look of LOOK_IDS) {
      for (const layout of ['wall', 'stripes', 'giant', 'poster']) {
        const s = settings(look, layout, P.phrase);
        s.text.hero = P.hero; s.text.small = P.small;
        const res = L.build(TAKE, s);
        const g = stack(res.rows);
        const lowOf = (grp) => Math.max.apply(null, grp.rows.map((r) => lowPx(r.text, res.fontId, r.fontSize)));
        for (let i = 1; i < g.length; i++) {
          const low = lowOf(g[i - 1]);
          const clear = g[i].top - (g[i - 1].bottom + low);        // row i's cap top against the lowest mark of row i - 1
          assert.ok(clear >= -0.011, look + '/' + layout + ': the marks of the row at ' + g[i - 1].top + ' reach ' + (-clear).toFixed(1) + 'px into the row below (marks ' + low.toFixed(1) + 'px)');
          if (low > 0) withLow++;
          checked++;
        }
        const sm = res.rows.find((r) => r.kind === 'small');
        if (sm && !sm.plate) {
          for (const r of res.rows.filter((q) => q.kind !== 'hero' && q.kind !== 'filler' && q.kind !== 'small' && q.top < sm.top)) {
            assert.ok(sm.top >= r.top + L.CAP * r.s + lowPx(r.text, res.fontId, r.fontSize) - 0.011, look + '/' + layout + ': ' + r.id + ' hangs into the small line');
          }
        }
        if (sm && !sm.plate) {                                      // and the small line's own marks under it, against what is below
          const below = res.rows.filter((q) => q.kind !== 'hero' && q.kind !== 'filler' && q.kind !== 'small' && q.top > sm.top);
          for (const r of below) assert.ok(r.top >= sm.top + L.CAP * sm.s + lowPx(sm.text, res.fontId, sm.fontSize) - 0.011, look + '/' + layout + ': the small line hangs into ' + r.id);
        }
      }
    }
    assert.ok(checked > 100 && (withLow > 50) === /[ÇĄĘŞŢŲĶĻŅŖ]/.test(P.phrase + P.small), 'compared ' + checked + ' neighbours, ' + withLow + ' of them under marks');
  });
}

test('the marks under the baseline of a rotated hero word do not run into the rows on its right', () => {
  for (const look of LOOK_IDS) {
    const s = settings(look, 'wall', 'Você não precisa de After Effects');
    s.text.hero = 'AÇÃO';
    const res = L.build(TAKE, s);
    const h = res.hero, low = lowPx(h.text, res.fontId, h.size * res.unit);
    assert.ok(low > 100);
    const span = res.rows.filter((r) => r.kind !== 'hero' && r.kind !== 'left' && r.top < h.yBottom && r.top + L.CAP * r.s > h.yBottom - h.len);
    assert.ok(span.length >= 3, look + ' has no rows beside the hero');
    // a row starting right of the column starts past the cedilla's tip; one that starts left of it is the part that runs under the word
    for (const r of span) assert.ok(!(r.left > h.xRight && r.left < h.xRight + low - 0.011), look + ': ' + r.id + ' starts at ' + r.left + ', the cedilla reaches ' + (h.xRight + low));
    assert.ok(span.some((r) => r.left >= h.xRight + low - 0.011), look);
  }
});

test('the marks of a rotated hero word do not run into the line next to it', () => {
  for (const look of LOOK_IDS) {
    const s = settings(look, 'wall', 'Você não precisa de After Effects');
    s.text.hero = 'AÇÃO';
    const res = L.build(TAKE, s);
    const h = res.hero, xLeft = h.xRight - L.CAP * h.size, head = headPx(h.text, res.fontId, h.size * res.unit);
    assert.ok(head > 0);
    const left = res.rows.filter((r) => r.kind === 'left');
    assert.ok(left.length > 0, look + ' has no row beside the hero');
    for (const r of left) assert.ok(r.left + r.width <= xLeft - head + 0.011, look + ': ' + r.id + ' ends at ' + (r.left + r.width) + ', marks start at ' + (xLeft - head));
  }
});

// ---------------------------------------------------------------- the studio picks a hero the layout can find
function studioHelpers() {
  const src = fs.readFileSync(path.join(APP, 'web', 'js', 'store.js'), 'utf8');
  const a = src.indexOf('function normWord'), b = src.indexOf('function suggestionsFor');
  assert.ok(a > 0 && b > a, 'store.js text helpers not found');
  const fn = vm.runInThisContext('(function (window) {' + src.slice(a, b).replace(/export /g, '') + '\nreturn { normWord: normWord, tokens: tokens, autoHero: autoHero }; })');
  return fn({ FTLayout: L });
}

test('the hero the studio picks is a word the layout draws, even where "i" upper-cases to a dotted capital', () => {
  const { normWord, autoHero } = studioHelpers();
  const saved = String.prototype.toLocaleUpperCase;
  String.prototype.toLocaleUpperCase = function () { return this.replace(/i/g, 'İ').replace(/[^i]/g, (c) => c.toUpperCase()); };   // what a Turkish locale does
  try {
    for (const phrase of ['istanbul straße', 'istanbul ok', 'você não precisa', 'ŻÓŁĆ ŚĄŹ', "here's how."]) {
      const words = L.words(phrase), hero = autoHero(phrase);
      assert.ok(words.indexOf(hero) >= 0, phrase + ': hero "' + hero + '" is not one of ' + JSON.stringify(words));
      const s = settings('original', 'wall', phrase);
      s.text.hero = hero;
      const drawn = L.build(TAKE, s).rows.filter((r) => r.kind === 'hero');
      assert.equal(drawn.length, 1, phrase + ': the hero is drawn once');
      // the hero is found among the words, so it is not also drawn as a column of its own on top of the phrase
      assert.ok(L.build(TAKE, s).chunks.some((c) => c.text.split(' ').indexOf(hero) >= 0), phrase);
    }
    assert.equal(normWord('istanbul'), 'ISTANBUL');
    assert.equal(normWord('straße.'), 'STRASSE');
  } finally { String.prototype.toLocaleUpperCase = saved; }
});
