/* floored layout: pure functions, no DOM, no canvas. Needs FT_METRICS (metrics.js) and FT_DATA (data.js: font letter
   spacing) loaded first. Lays out the rows: coverage samples, x_range, build,
   build_left_of_col and fillers, for chunks, fonts, 4 layouts and the pace timing.

   window.FTLayout = {
     build(take, settings) -> { theta, fontId, unit, rows, chunks, hero, timing }
     width(str, fontId, fontSize) -> px
     capWidth(str, fontId, s) -> px of `str` at CAP size s (font-size = s * unit)
     unit(fontId), nudge(fontId, fontSize), rise(str, fontId, fontSize), depth(str, fontId, fontSize), words(phrase), leftOut(phrase), dropped(phrase), report(phrase), keeps(ch), chunk(words, maxChars),
     camState(id, u), inOut(u), backOut(p), clamp01, lerp, PACES, THETA, CAP, ...
   }
   Everything is deterministic: the same (take, settings) always gives the same layout. */
(function (root) {
  'use strict';

  var CAP = 0.86;                       // row box height = CAP * s (Anton's cap height)
  var P = 2000, OX = 540, OY = 150;     // the camera's perspective (px) and its vanishing point
  var GAP = 0.06;                       // filler gap between rows, in cap sizes
  var THETA = { wall: 29, stripes: 29, giant: 16, poster: 6 };
  // designed slots, in entry order: [top, s, leadX, dir]
  var SLOTS = [[-480, 360, -600, -1], [-150, 360, -600, 1], [180, 400, -600, -1], [-1020, 560, -480, -1],
               [650, 560, -900, 1], [1155, 520, -1250, -1], [-1560, 600, -300, 1], [1640, 520, -1300, 1]];
  var PACES = {
    fast:     { T0: 0.15, STAG: 0.07, SLIDE: 0.45, FILL: 0.045, SMALL: 0.12, CAM: 3.2, E: 0.45 },
    smooth:   { T0: 0.30, STAG: 0.11, SLIDE: 0.60, FILL: 0.07,  SMALL: 0.17, CAM: 4.0, E: 0.60 },
    dramatic: { T0: 0.45, STAG: 0.18, SLIDE: 0.80, FILL: 0.10,  SMALL: 0.22, CAM: 4.6, E: 0.80 },
    speech:   { T0: null, STAG: null, SLIDE: 0.50, FILL: 0.07,  SMALL: 0.17, CAM: 4.0, E: 0.60 }
  };

  function clamp01(u) { return u < 0 ? 0 : (u > 1 ? 1 : u); }
  function clamp(v, a, b) { return v < a ? a : (v > b ? b : v); }
  function lerp(a, b, u) { return a + (b - a) * u; }
  function inOut(u) { return u < 0.5 ? 2 * u * u : 1 - Math.pow(-2 * u + 2, 2) / 2; }   // power1.inOut
  function backOut(p) { p -= 1; return p * p * (2.3 * p + 1.3) + 1; }                    // back.out(1.3)
  function mod(a, n) { return ((a % n) + n) % n; }
  function r2(v) { return Math.round(v * 100) / 100; }
  function r4(v) { return Math.round(v * 10000) / 10000; }

  // ---- cameras (spike numbers). u = eased progress 0..1. Used for the coverage here and for painting in engine.js
  var CAMS = {
    pull:  { S: [1, 0.48],    A: [20, 45], ax: [545, 545], ay: [1240, 1120], spin: [0, 0] },
    crane: { S: [1.8, 0.5],   A: [12, 42], ax: [545, 545], ay: [1300, 1130], spin: [0, 0] },
    orbit: { S: [0.66, 0.58], A: [36, 36], ax: [545, 545], ay: [1150, 1150], spin: [0, 80] },
    push:  { S: [0.55, 1.1],  A: [42, 30], ax: [545, 545], ay: [1120, 1260], spin: [0, 0] },
    still: { S: [0.62, 0.62], A: [38, 38], ax: [545, 545], ay: [1150, 1150], spin: [0, 0] }
  };
  var CAM_IDS = ['pull', 'crane', 'orbit', 'push', 'still'];
  function camState(id, u) {
    var c = CAMS[id] || CAMS.still;
    return { S: lerp(c.S[0], c.S[1], u), A: lerp(c.A[0], c.A[1], u), ax: lerp(c.ax[0], c.ax[1], u),
             ay: lerp(c.ay[0], c.ay[1], u), spin: lerp(c.spin[0], c.spin[1], u) };
  }

  // screen point (X, Y) -> para coordinates (the rotated text plane), for camera state c and rotation theta
  function screenToPara(X, Y, c, theta) {
    var A = c.A * Math.PI / 180;
    var v = P * (Y - c.ay) / (P * Math.cos(A) + (Y - OY) * Math.sin(A));   // v = S * y
    if (P - v * Math.sin(A) <= 50) return null;                              // behind the horizon
    var sx = (X - OX) * (P - v * Math.sin(A)) / P - (c.ax - OX);
    var x = sx / c.S, y = v / c.S;
    var th = (theta - c.spin) * Math.PI / 180;
    return [x * Math.cos(th) - y * Math.sin(th), x * Math.sin(th) + y * Math.cos(th)];
  }

  // para-space samples of what all five cameras see, cached per theta
  var COV = {};
  function coverage(theta) {
    if (COV[theta]) return COV[theta];
    var xs = [], ys = [];
    CAM_IDS.forEach(function (id) {
      var n = id === 'still' ? 0 : 20;
      for (var i = 0; i <= n; i++) {
        var cs = camState(id, i * 0.05);
        for (var X = -40; X <= 1120; X += 40) {
          for (var Y = -40; Y <= 1960; Y += 40) {
            var p = screenToPara(X, Y, cs, theta);
            if (p) { xs.push(p[0]); ys.push(p[1]); }
          }
        }
      }
    });
    var ymin = Infinity, ymax = -Infinity;
    for (var k = 0; k < ys.length; k++) { if (ys[k] < ymin) ymin = ys[k]; if (ys[k] > ymax) ymax = ys[k]; }
    COV[theta] = { xs: Float64Array.from(xs), ys: Float64Array.from(ys), YMIN: ymin - 100, YMAX: ymax + 100 };
    return COV[theta];
  }
  function xRange(cov, top, bottom, margin) {
    if (margin == null) margin = 260;
    var lo = Infinity, hi = -Infinity, y0 = top - 120, y1 = bottom + 120, ys = cov.ys, xs = cov.xs;
    for (var i = 0; i < ys.length; i++) {
      var y = ys[i];
      if (y >= y0 && y <= y1) { var x = xs[i]; if (x < lo) lo = x; if (x > hi) hi = x; }
    }
    return lo === Infinity ? null : [lo - margin, hi + margin];
  }

  // ---- fonts and text (metrics only)
  function fontInfo(fontId) {
    var M = root.FT_METRICS && root.FT_METRICS[fontId];
    var F = root.FT_DATA && root.FT_DATA.FONTS && root.FT_DATA.FONTS[fontId];
    if (!M || !F) throw new Error('FTLayout: unknown font "' + fontId + '" (need metrics.js and data.js)');
    return { id: fontId, m: M, ls: F.ls || 0, unit: CAP / M.capH, cache: {} };
  }
  // advance of `str` in em of the font-size: sum of w[ch] (fallback when missing) + ls per character
  function emw(str, fi) {
    var c = fi.cache[str];
    if (c !== undefined) return c;
    var w = fi.m.w, fb = fi.m.fallback, sum = 0, n = 0;
    for (var ch of str) { var a = w[ch]; sum += (a === undefined ? fb : a); n++; }
    c = sum + fi.ls * n;
    fi.cache[str] = c;
    return c;
  }
  function width(str, fontId, fontSize) { return fontSize * emw(str, fontInfo(fontId)); }
  function capWidth(str, fontId, s) { var fi = fontInfo(fontId); return s * fi.unit * emw(str, fi); }
  function unit(fontId) { return CAP / fontInfo(fontId).m.capH; }
  // shift to add to a row's `top` so that its cap top sits exactly on `top` (line-height = capH)
  function nudge(fontId, fontSize) {
    var m = fontInfo(fontId).m;
    return -(((m.capH - (m.asc + m.desc)) / 2 + m.asc - m.capH) * fontSize);
  }

  // how far the marks of an accented letter in `str` reach above the cap top, in px at `fontSize` (0 for unmarked text).
  // FT_METRICS[font].t is generated from the glyphs (dev/gen_metrics.py); a row's cap top sits on its `top`, so the marks
  // occupy [top - rise, top]. Rows are spaced so that this never reaches the row above.
  function riseEm(str, fi) {
    var t = fi.m.t, r = 0;
    if (!t) return 0;
    for (var ch of str) { var v = t[ch]; if (v > r) r = v; }
    return r;
  }
  function rise(str, fontId, fontSize) { return riseEm(String(str), fontInfo(fontId)) * fontSize; }
  // ... and how far the marks that hang below the baseline (cedilla, ogonek, comma below) reach under it: FT_METRICS[font].b
  function depthEm(str, fi) {
    var b = fi.m.b, r = 0;
    if (!b) return 0;
    for (var ch of str) { var v = b[ch]; if (v > r) r = v; }
    return r;
  }
  function depth(str, fontId, fontSize) { return depthEm(String(str), fontInfo(fontId)) * fontSize; }

  // ---- the text the floor can draw: Basic Latin, Latin-1, Latin Extended-A and ’ ‘ “ ” – — … € (dev/gen_metrics.py CHARSET,
  // minus U+00AD and U+0149). Every font table in metrics.js has a width for each of them; a font that lacks the glyph
  // is drawn by Inter. Anything else (emoji, Cyrillic, CJK...) is left out: report() says which words went whole and which characters went alone.
  var KEEP_MARKS = [0x2018, 0x2019, 0x201C, 0x201D, 0x2013, 0x2014, 0x2026, 0x20AC];
  var INVISIBLE = /[\p{M}\p{Cf}]/u;                      // stray combining marks, variation selectors, zero-width and soft hyphen
  function keepsCode(c) {
    return (c >= 0x20 && c <= 0x7E) || (c >= 0xA0 && c <= 0x17F && c !== 0xAD && c !== 0x149) || KEEP_MARKS.indexOf(c) >= 0;
  }
  function keeps(ch) { return keepsCode(String(ch).codePointAt(0)); }
  function allKept(str) { for (var ch of str) if (!keepsCode(ch.codePointAt(0))) return false; return true; }
  // upper-case without a locale (so "i" never becomes "İ"): ß -> SS; a letter whose capital the fonts lack (µ) stays as it is
  function upper(ch) { var u = ch.toUpperCase(); return allKept(u) ? u : ch; }
  function tidy(str) { return String(str == null ? '' : str).normalize('NFC').replace(/'/g, '’'); }
  // One pass over `phrase`, per whitespace-separated word. A word that needs a letter the fonts lack (Cyrillic, Greek, Arabic,
  // CJK, Vietnamese tone letters...) is left out whole, so the floor never shows a wrong word ("TING" for "Tiếng"); the same
  // goes for a combining mark that sits on a letter and joins nothing (x + acute). Anything else the fonts lack (emoji,
  // symbols, a mark after nothing) is removed alone. A mark or joiner inside a removed emoji (variation selector, zero-width
  // joiner, skin tone mark) is invisible and not reported. Returns
  //   kept  the words the floor draws (upper-cased, no trailing . , ; :), in the order typed
  //   words the typed words left out whole (trailing . , ; : cut), each once, in the order typed
  //   chars the characters removed alone from words that stay, each once, in order
  var VARIATION = /[\uFE00-\uFE0F\u{E0100}-\u{E01EF}]/u, MARK = /\p{M}/u, LETTER = /\p{L}/u;
  function report(phrase) {
    var kept = [], left = [], chars = [];
    tidy(phrase).split(/\s+/).forEach(function (w) {
      var out = '', whole = false, lost = [], prev = 'none', prevLetter = false;   // prev: the last base character: none | kept | left
      for (var ch of w) {
        if (INVISIBLE.test(ch)) {
          if (MARK.test(ch) && !VARIATION.test(ch)) {
            if (prev === 'kept' && prevLetter) whole = true;                    // a mark on a letter the fonts cannot compose
            else if (prev !== 'left') lost.push(ch);                            // a mark that joins nothing
          }
          continue;
        }
        prevLetter = LETTER.test(ch);
        if (keeps(ch) || allKept(ch.toUpperCase())) { prev = 'kept'; out += upper(ch); continue; }
        prev = 'left';
        if (prevLetter) whole = true; else lost.push(ch);
      }
      if (whole) {
        var shown = w.replace(/[.,;:]+$/, '');
        if (shown && left.indexOf(shown) < 0) left.push(shown);
        return;
      }
      lost.forEach(function (ch) { if (chars.indexOf(ch) < 0) chars.push(ch); });
      out = out.replace(/[.,;:]+$/, '');                                        // no trailing periods on screen
      if (out) kept.push(out);
    });
    return { kept: kept, words: left, chars: chars };
  }
  function words(phrase) { return report(phrase).kept; }
  function leftOut(phrase) { return report(phrase).words; }
  function dropped(phrase) { return report(phrase).chars; }
  function strip(s) { return s.replace(/[^\p{L}\p{N}]/gu, ''); }
  function same(a, b) { var x = strip(a), y = strip(b); return x.length > 0 && x === y; }

  // greedy chunks: one word, plus the next one when both together (with the space) fit in maxChars
  function chunk(ws, maxChars) {
    var out = [], i = 0;
    while (i < ws.length) {
      var c = { first: i, last: i, words: [ws[i]], text: ws[i] };
      if (i + 1 < ws.length && ws[i].length + 1 + ws[i + 1].length <= maxChars) {
        c.last = i + 1; c.words.push(ws[i + 1]); c.text = ws[i] + ' ' + ws[i + 1]; i += 2;
      } else i += 1;
      out.push(c);
    }
    return out;
  }
  function makeChunks(ws) {
    var c = chunk(ws, 7);
    if (c.length > 8) c = chunk(ws, 12);
    return c;
  }

  // ---- pace and ending timing
  function makeTiming(take, settings) {
    var pace = PACES[settings.pace] ? settings.pace : 'smooth';
    var tw = (take && take.words) || [];
    var speech = pace === 'speech' && tw.length > 0;
    var C = PACES[pace === 'speech' && !speech ? 'smooth' : pace];
    var dur = take && take.dur > 0 ? take.dur : 5;
    var ending = settings.ending || 'cut';
    var E = ending === 'cut' ? 0 : C.E;
    var te = dur - E;
    var Tc = clamp(Math.min(C.CAM, te - 0.2), 1.5, 6);
    var Tcam = settings.camera === 'orbit' ? Math.min(Tc + 0.5, te) : Tc;
    return { pace: pace, speech: speech, T0: C.T0, STAG: C.STAG, SLIDE: C.SLIDE, FILL: C.FILL, SMALL: C.SMALL, camBase: C.CAM,
             E: E, dur: dur, te: te, Tc: Tc, Tcam: Tcam, ending: ending, camera: settings.camera || 'pull',
             fillStart: null, lastEntry: null, smallStart: null };
  }

  // ---- the layouts
  function makeCtx(take, settings, timing, fontId, layoutId) {
    var fi = fontInfo(fontId);
    var txt = settings.text || {};
    var ws = words(txt.phrase);
    var hero = words(txt.hero).join(' ');
    var small = words(txt.small);
    var theta = THETA[layoutId];
    var ctx = {
      take: take, settings: settings, timing: timing, fi: fi, words: ws, n: ws.length, hero: hero, small: small,
      theta: theta, unit: fi.unit, chunks: makeChunks(ws), layoutId: layoutId
    };
    ctx.cw = function (str) { return emw(str, fi) * fi.unit; };       // width of str at cap size 1
    ctx.sp = ctx.cw(' ');
    ctx.head = function (str, s) { return riseEm(str, fi) * fi.unit * s; };               // marks above a row of `str` at cap size s, px
    var phraseRise = riseEm(ws.join(' '), fi);
    ctx.headAll = function (s) { return phraseRise * fi.unit * s; };                       // ... for a row built from any of the phrase's words
    ctx.low = function (str, s) { return depthEm(str, fi) * fi.unit * s; };                // marks below the baseline of a row of `str`, px
    var phraseDepth = depthEm(ws.join(' '), fi);
    ctx.lowAll = function (s) { return phraseDepth * fi.unit * s; };
    ctx.tw = (take && take.words) || [];
    ctx.exact = settings.text && settings.text.source === 'speech' && ctx.tw.length === ws.length;
    // start time of each entry, `firsts` = index of the first phrase word of each entry (entry order)
    ctx.designedTimes = function (firsts) {
      var T = timing, m = firsts.length, out = [], k;
      if (T.speech) {
        var w0 = ctx.tw[0].start, wL = ctx.tw[ctx.tw.length - 1].start;
        for (k = 0; k < m; k++) {
          if (ctx.exact && firsts[k] != null && ctx.tw[firsts[k]]) out.push(ctx.tw[firsts[k]].start);
          else out.push(m > 1 ? w0 + (wL - w0) * k / (m - 1) : w0);
        }
      } else {
        for (k = 0; k < m; k++) out.push(T.T0 + k * T.STAG);
      }
      return out;
    };
    ctx.rowIdx = 0;
    ctx.mkRow = function (o) {
      var s = o.s, x = 0, ws2 = [], i;
      for (i = 0; i < o.list.length; i++) { ws2.push({ text: o.list[i], x: r2(x) }); x += (ctx.cw(o.list[i]) + ctx.sp) * s; }
      var w = o.list.length ? x - ctx.sp * s : 0;
      var lf = o.leadFrom == null ? 0 : o.leadFrom, lt = o.leadTo == null ? Math.max(0, o.list.length - 1) : o.leadTo;
      var lcx = ws2.length ? (ws2[lf].x + ws2[lt].x + ctx.cw(ws2[lt].text) * s) / 2 : 0;
      return {
        id: o.id, kind: o.kind, text: o.list.join(' '), words: ws2, left: r2(o.left), top: r2(o.top), s: s,
        fontSize: r4(s * fi.unit), rot: o.rot || 0, dir: o.dir, tin: null, off: Math.round(w + 1600),
        depth: r4(Math.max(0, (-o.top - 1600) / 1000)), color: o.color || 'ink', order: 0, width: r2(w),
        leadFrom: lf, leadTo: lt, leadCx: r2(lcx)
      };
    };
    return ctx;
  }

  // build(): a row built around `lead` placed at leadX, filled right and left with the phrase continuing cyclically
  // until it covers the camera's x range
  function buildFill(ctx, cov, col, lead, leadX, s, top, k0) {
    var bottom = top + CAP * s, rng = xRange(cov, top, bottom);
    if (!rng) return null;
    var lo = rng[0], hi = rng[1], n = ctx.n;
    if (col && top < col.yBottom && bottom > col.yTop) {
      lo = Math.max(lo, col.xRight + 40 + (col.low || 0));
      if (col.low > 0) leadX = Math.max(leadX, col.xRight + 40 + col.low);       // the lead word starts clear of the hero's cedilla too
    }
    var list = lead.slice(), rightEnd = leadX + ctx.cw(list.join(' ')) * s, j = k0 + lead.length, guard = 0, nxt, prv;
    while (rightEnd < hi && guard++ < 600) { nxt = ctx.words[mod(j, n)]; list.push(nxt); rightEnd += (ctx.sp + ctx.cw(nxt)) * s; j++; }
    var left = leadX, pre = 0; j = k0 - 1; guard = 0;
    while (left > lo && guard++ < 600) { prv = ctx.words[mod(j, n)]; list.unshift(prv); pre++; left -= (ctx.sp + ctx.cw(prv)) * s; j--; }
    return { list: list, left: left, top: top, s: s, leadFrom: pre, leadTo: pre + lead.length - 1 };
  }
  // build_left_of_col(): the part of a row left of the hero column, ending 40 px before it
  function buildLeftOfCol(ctx, cov, col, s, top, k0, rowLeft) {
    var bottom = top + CAP * s, rng = xRange(cov, top, bottom);
    var end = Math.min(col.xLeft - 40 - (col.head || 0), rowLeft - ctx.sp * s);
    if (!rng || rng[0] >= end) return null;
    var list = [], left = end + ctx.sp * s, j = k0, prv, guard = 0;
    while (left > rng[0] && guard++ < 600) { prv = ctx.words[mod(j, ctx.n)]; list.unshift(prv); left -= (ctx.sp + ctx.cw(prv)) * s; j--; }
    return { list: list, left: left, top: top, s: s };
  }

  function smallRow(ctx, left, top, dir) {
    if (!ctx.small.length) return null;
    return ctx.mkRow({ id: 'small', kind: 'small', list: ctx.small, left: left, top: top, s: 110, dir: dir == null ? -1 : dir, color: 'small' });
  }

  // after the rows have their times: the small line types in after the last entry, and must end 0.3 s before te
  function placeSmall(ctx, rows, sm) {
    var T = ctx.timing, last = 0, i;
    for (i = 0; i < rows.length; i++) if (rows[i].tin != null && rows[i].tin > last) last = rows[i].tin;
    T.lastEntry = r2(last);
    if (!sm) return;
    var start = last + 0.25, nw = sm.words.length;
    start = Math.min(start, T.te - 0.3 - T.SMALL * (nw - 1));
    start = Math.max(start, 0);
    sm.tin = r2(start);
    sm.step = T.SMALL;
    T.smallStart = sm.tin;
    rows.push(sm);
  }

  // items = [{top, s, head, low}] in any order; returns each one's top, in the same order. Going down the stack, an item with
  // marks above it (head > 0), or under a row whose marks hang below its baseline (low > 0), needs low + head + GAP * s of clear
  // space between the row above's baseline and its own cap top; if it has less, it moves down by the difference and so does
  // everything under it. Items without marks, under rows without marks, never move on their own.
  function makeRoom(items) {
    var order = items.map(function (it, i) { return i; }).sort(function (a, b) { return items[a].top - items[b].top || a - b; });
    var out = items.map(function (it) { return it.top; }), shift = 0, prevBottom = -Infinity, prevLow = 0;
    order.forEach(function (i) {
      var it = items[i], t = it.top + shift;
      if (it.head > 0 || prevLow > 0) {
        var need = prevBottom + prevLow + GAP * it.s + (it.head || 0);
        if (t < need) { shift += need - t; t = need; }
      }
      out[i] = t;
      prevBottom = t + CAP * it.s;
      prevLow = it.low || 0;
    });
    return out;
  }

  function layoutWall(ctx) {
    var T = ctx.timing, cov = coverage(ctx.theta), rows = [], i;
    var col = null, heroRow = null;
    if (ctx.hero) {
      col = { s: 700, xRight: -640, yBottom: 640 };
      col.xLeft = col.xRight - CAP * col.s;
      col.head = ctx.head(ctx.hero, col.s);          // the rotated word's marks point left, into the line beside it
      col.low = ctx.low(ctx.hero, col.s);            // ... and the ones under its baseline point right
      col.len = ctx.cw(ctx.hero) * col.s;
      col.yTop = col.yBottom - col.len;
    }
    var ch = ctx.chunks, nd = Math.min(SLOTS.length, ch.length);
    var times = ctx.designedTimes(ch.map(function (c) { return c.first; }));
    var designed = [];
    // the designed slots and the small line are one stack top to bottom: a row whose accent marks would reach into the row
    // above is pushed down, with everything below it (nothing moves when no letter carries a mark)
    var stackIn = [], stackTops;
    for (i = 0; i < nd; i++) stackIn.push({ top: SLOTS[i][0], s: SLOTS[i][1], head: ctx.headAll(SLOTS[i][1]), low: ctx.lowAll(SLOTS[i][1]) });
    if (ctx.small.length) stackIn.push({ top: 540, s: 110, head: ctx.head(ctx.small.join(' '), 110), low: ctx.low(ctx.small.join(' '), 110) });
    stackTops = makeRoom(stackIn);
    for (i = 0; i < nd; i++) {
      var sl = SLOTS[i], top = stackTops[i], s = sl[1], lx = sl[2], dir = sl[3];
      var f = buildFill(ctx, cov, col, ch[i].words, lx, s, top, ch[i].first);
      if (!f) continue;
      var r = ctx.mkRow({ id: 'c' + i, kind: 'designed', list: f.list, left: f.left, top: top, s: s, dir: dir, leadFrom: f.leadFrom, leadTo: f.leadTo });
      r.tin = r2(times[i]); r.chunk = i;
      rows.push(r); designed.push(r);
      if (col && top < col.yBottom && top + CAP * s > col.yTop) {
        var l = buildLeftOfCol(ctx, cov, col, s, top, ch[i].first - 1, f.left);
        if (l) {
          var lr = ctx.mkRow({ id: 'c' + i + '-l', kind: 'left', list: l.list, left: l.left, top: top, s: s, dir: -1 });
          lr.tin = r2(times[i] + 0.05); lr.chunk = i;
          rows.push(lr); designed.push(lr);
        }
      }
    }
    // the hero column: reads upward, right edge at x = xRight, bottom at yBottom; enters 0.1 s before its chunk
    if (col) {
      var hc = -1;
      for (i = 0; i < ch.length && hc < 0; i++) for (var q = 0; q < ch[i].words.length; q++) if (same(ch[i].words[q], ctx.hero)) { hc = i; break; }
      heroRow = ctx.mkRow({ id: 'hero', kind: 'hero', list: [ctx.hero], left: col.xLeft, top: col.yBottom, s: col.s, rot: -90, dir: -1 });
      heroRow.tin = r2(Math.max(0, (hc >= 0 ? times[hc] : times[0] != null ? times[0] : T.T0 || 0) - 0.1));
      rows.push(heroRow); designed.push(heroRow);
    }
    var lastDesigned = 0;
    for (i = 0; i < designed.length; i++) if (designed[i].tin > lastDesigned) lastDesigned = designed[i].tin;

    // fillers above and below until every camera's whole view is covered
    var topEdge = Infinity, bottomEdge = -Infinity;
    var topS = 0, bottomS = 0;
    rows.forEach(function (rw) { if (rw.kind === 'hero') return; if (rw.top < topEdge) { topEdge = rw.top; topS = rw.s; } if (rw.top + CAP * rw.s > bottomEdge) { bottomEdge = rw.top + CAP * rw.s; bottomS = rw.s; } });
    var fillers = [];
    if (isFinite(topEdge) && ctx.n > 0) {
      var k = 2, y = topEdge, ix = 0, s2, fr;
      while (y > cov.YMIN && ix < 60) {
        s2 = Math.min(700, 420 + 70 * ix);
        y -= (CAP + GAP) * s2 + ctx.headAll(topS) + ctx.lowAll(s2);   // the row below keeps room for its marks above, this one for those below
        topS = s2;
        fr = buildFill(ctx, cov, col, [ctx.words[mod(k, ctx.n)]], 300 + 180 * ix, s2, y, k);
        if (fr) fillers.push(ctx.mkRow({ id: 'u' + ix, kind: 'filler', list: fr.list, left: fr.left, top: y, s: s2, dir: ix % 2 === 0 ? 1 : -1, leadFrom: fr.leadFrom, leadTo: fr.leadTo }));
        k += 3; ix++;
      }
      var hd = ctx.headAll(520);
      var ld = ctx.lowAll(520);
      y = bottomEdge + ctx.lowAll(bottomS) + GAP * 520 + hd; ix = 0;
      while (y < cov.YMAX && ix < 60) {
        fr = buildFill(ctx, cov, col, [ctx.words[mod(k, ctx.n)]], -1300 - 150 * ix, 520, y, k);
        if (fr) fillers.push(ctx.mkRow({ id: 'd' + ix, kind: 'filler', list: fr.list, left: fr.left, top: y, s: 520, dir: ix % 2 ? 1 : -1, leadFrom: fr.leadFrom, leadTo: fr.leadTo }));
        y += (CAP + GAP) * 520 + hd + ld; k += 3; ix++;
      }
    }
    var base = T.speech ? 0.2 : lastDesigned + 0.1;
    T.fillStart = r2(base);
    fillers.map(function (rw, i0) { return [Math.abs(rw.top + CAP * rw.s / 2), i0, rw]; })
      .sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; })
      .forEach(function (e, nIdx) { e[2].tin = r2(base + T.FILL * nIdx); rows.push(e[2]); });

    var sm = smallRow(ctx, -60, stackTops[nd]);          // the small line is the last stack item (when there is one)
    placeSmall(ctx, rows, sm);
    return { rows: rows, col: col };
  }

  function layoutStripes(ctx) {
    var T = ctx.timing, cov = coverage(ctx.theta), rows = [], pitch = 300 * (CAP + 1.6), j;
    if (ctx.n === 0) return { rows: rows };
    var js = [];
    for (j = -60; j <= 60; j++) {
      var top = -150 + j * pitch;
      if (top + CAP * 300 >= cov.YMIN && top <= cov.YMAX) js.push(j);
    }
    js.sort(function (a, b) { return Math.abs(a) - Math.abs(b) || a - b; });
    var nd = Math.min(js.length, Math.max(1, ctx.chunks.length));
    var times = ctx.designedTimes(js.slice(0, nd).map(function (jj, m) { return ctx.chunks[m] ? ctx.chunks[m].first : null; }));
    var lastDesigned = 0;
    js.forEach(function (jj, m) {
      var topJ = -150 + jj * pitch, k0 = mod(jj * 3, ctx.n);
      var f = buildFill(ctx, cov, null, [ctx.words[k0]], -600 + 220 * jj, 300, topJ, k0);
      if (!f) return;
      var r = ctx.mkRow({ id: 'b' + jj, kind: 'band', list: f.list, left: f.left, top: topJ, s: 300, dir: mod(jj, 2) === 0 ? 1 : -1, leadFrom: f.leadFrom, leadTo: f.leadTo });
      r.band = jj;
      if (m < nd) { r.tin = r2(times[m]); if (r.tin > lastDesigned) lastDesigned = r.tin; }
      rows.push(r);
    });
    var base = T.speech ? 0.2 : lastDesigned + 0.1, nIdx = 0;
    T.fillStart = r2(base);
    rows.forEach(function (r) { if (r.tin == null) { r.tin = r2(base + T.FILL * nIdx); r.extra = true; nIdx++; } });
    var sm = smallRow(ctx, -60, -150 + CAP * 300 + ctx.lowAll(300) + 60);      // clear of the marks that hang under band 0
    placeSmall(ctx, rows, sm);
    return { rows: rows };
  }

  function layoutGiant(ctx) {
    var rows = [], ws = ctx.words, n = ctx.n;
    if (n === 0) return { rows: rows };
    var hi = -1, i, text;
    if (ctx.hero) { for (i = 0; i < n; i++) if (same(ws[i], ctx.hero)) { hi = i; break; } text = ctx.hero; }
    else { hi = 0; for (i = 1; i < n; i++) if (ws[i].length > ws[hi].length) hi = i; text = ws[hi]; }
    var cw1 = ctx.cw(text), G = clamp(2400 / cw1, 700, 1600);
    var gw = cw1 * G, gLeft = -0.42 * gw, gTop = -CAP * G * 0.35;
    var before = hi >= 0 ? ws.slice(0, hi) : ws.slice(), after = hi >= 0 ? ws.slice(hi + 1) : [];
    // the words around the giant one go in short stacked lines that fit the view (one long row ran off-frame)
    var GAP = 30, WL = 1500;
    function stack(list, first0) {
      return chunk(list, 12).map(function (c) {
        var s = clamp(WL / ctx.cw(c.text), 140, 300);
        return { list: c.words, s: s, w: ctx.cw(c.text) * s, first: first0 + c.first };
      });
    }
    var above = stack(before, 0), below = stack(after, hi + 1), lw = 0, y, k;
    above.concat(below).forEach(function (l) { lw = Math.max(lw, l.w); });
    var lLeft = -0.42 * lw, entries = [];
    for (y = gTop - 60 - ctx.head(text, G), k = above.length - 1; k >= 0; k--) { y -= ctx.low(above[k].list.join(' '), above[k].s) + CAP * above[k].s; above[k].top = y; y -= GAP + ctx.head(above[k].list.join(' '), above[k].s); }
    above.forEach(function (l, m) { entries.push({ id: 'above' + m, kind: 'line', list: l.list, top: l.top, s: l.s, first: l.first, dir: m % 2 ? 1 : -1, left: lLeft }); });
    entries.push({ id: 'giant', kind: 'giant', list: [text], top: gTop, s: G, first: hi >= 0 ? hi : 0, dir: 1, big: true, left: gLeft });
    y = gTop + CAP * G + ctx.low(text, G) + 60;
    below.forEach(function (l, m) { y += ctx.head(l.list.join(' '), l.s); entries.push({ id: 'below' + m, kind: 'line', list: l.list, top: y, s: l.s, first: l.first, dir: m % 2 ? 1 : -1, left: lLeft }); y += CAP * l.s + ctx.low(l.list.join(' '), l.s) + GAP; });
    var times = ctx.designedTimes(entries.map(function (e) { return e.first; }));
    entries.forEach(function (e, m) {
      var r = ctx.mkRow({ id: e.id, kind: e.kind, list: e.list, left: e.left, top: e.top, s: e.s, dir: e.dir });
      if (e.big) r.off = Math.round(1.5 * (r.width + 1600));
      r.tin = r2(times[m]);
      rows.push(r);
    });
    // the small line sits by the feet (always in view) on a floor-coloured plate over the giant word
    var sm = smallRow(ctx, -60, 540);
    if (sm) sm.plate = true;
    ctx.timing.fillStart = null;
    placeSmall(ctx, rows, sm);
    return { rows: rows };
  }

  function layoutPoster(ctx) {
    var rows = [], lines = chunk(ctx.words, 12), Wp = 1700, i;
    if (!lines.length) return { rows: rows };
    var ss = lines.map(function (c) { return clamp(Wp / ctx.cw(c.text), 180, 900); });
    var H = 0;
    var hs = lines.map(function (c, m) { return ctx.head(c.text, ss[m]); });
    var ls = lines.map(function (c, m) { return ctx.low(c.text, ss[m]); });
    for (i = 0; i < lines.length; i++) H += CAP * ss[i] + (i < lines.length - 1 ? 0.08 * ss[i] + ls[i] + hs[i + 1] : 0);
    var left = -Wp / 2 + 120, top0 = -0.38 * H, y = top0;
    var times = ctx.designedTimes(lines.map(function (c) { return c.first; }));
    lines.forEach(function (c, m) {
      if (m > 0) y += hs[m];                               // room for this line's marks under the line before
      var r = ctx.mkRow({ id: 'l' + m, kind: 'line', list: c.words, left: left, top: y, s: ss[m], dir: m % 2 === 0 ? -1 : 1 });
      r.tin = r2(times[m]);
      rows.push(r);
      y += CAP * ss[m] + 0.08 * ss[m] + ls[m];
    });
    var sm = smallRow(ctx, -60, 540);   // by the feet, as in giant: under the block it falls out of frame
    if (sm) sm.plate = true;
    ctx.timing.fillStart = null;
    placeSmall(ctx, rows, sm);
    return { rows: rows, lines: lines };
  }

  var LAYOUTS = { wall: layoutWall, stripes: layoutStripes, giant: layoutGiant, poster: layoutPoster };

  function build(take, settings) {
    settings = settings || {};
    var layoutId = LAYOUTS[settings.layout] ? settings.layout : 'wall';
    var fontId = settings.font || 'condensed';
    var timing = makeTiming(take, settings);
    var ctx = makeCtx(take, settings, timing, fontId, layoutId);
    var res = ctx.n || layoutId === 'giant' ? LAYOUTS[layoutId](ctx) : { rows: [] };
    var rows = res.rows;
    // entry rank, small line last
    var idx = rows.map(function (r, i) { return i; });
    idx.sort(function (a, b) {
      var ra = rows[a], rb = rows[b];
      var sa = ra.kind === 'small' ? 1 : 0, sb = rb.kind === 'small' ? 1 : 0;
      return sa - sb || ra.tin - rb.tin || a - b;
    });
    idx.forEach(function (ri, rank) { rows[ri].order = rank; });
    var chunks = (layoutId === 'poster' ? (res.lines || []) : ctx.chunks).map(function (c) {
      return { text: c.text, first: c.first, last: c.last };
    });
    var hero = null;
    if (layoutId === 'wall' && res.col) hero = { text: ctx.hero, size: res.col.s, xRight: res.col.xRight, yBottom: res.col.yBottom, len: r2(res.col.len) };
    else if (layoutId === 'giant') hero = rows.filter(function (r) { return r.kind === 'giant'; }).map(function (r) { return { text: r.text, size: r.s }; })[0] || null;
    // JSON round trip keeps the result plain data (no functions, no shared refs)
    return { theta: ctx.theta, fontId: fontId, layout: layoutId, unit: r4(ctx.unit), words: ctx.words, rows: rows, chunks: chunks, hero: hero, timing: timing };
  }

  root.FTLayout = {
    build: build, width: width, capWidth: capWidth, unit: unit, nudge: nudge, rise: rise, depth: depth, words: words, leftOut: leftOut, dropped: dropped, report: report, keeps: keeps,
    chunk: chunk, makeChunks: makeChunks,
    camState: camState, screenToPara: screenToPara, coverage: coverage, xRange: xRange, inOut: inOut, backOut: backOut,
    clamp01: clamp01, clamp: clamp, lerp: lerp, PACES: PACES, THETA: THETA, CAP: CAP, SLOTS: SLOTS, CAM_IDS: CAM_IDS, CAMS: CAMS
  };
})(typeof window !== 'undefined' ? window : this);
