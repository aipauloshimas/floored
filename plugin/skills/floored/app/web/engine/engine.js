/* floored engine: fills the scene skeleton of app/SPEC.md and paints it. Needs data.js, metrics.js and layout.js
   loaded first (scripts, in that order) and engine.css.

   window.Floored = {
     create(rootEl, take, settings, opts)      -> Promise<engine>   live: resolves once the font has loaded
     createSync(rootEl, take, settings, opts)  -> engine            render: builds now (layout needs no font load)
     prepareFont(settings, opts)               -> Promise           injects @font-face and loads the font (extra, see REPORT)
     preloadFonts(base)                        -> Promise           injects and loads all six look fonts and Inter (the studio, at start-up)
   }
   opts = { mode: 'live' | 'render', fontsBase: '/engine/fonts/' | 'assets/engine/fonts/', layout?: layoutData() }
   engine: duration, paint(t), set(settings) -> Promise, layoutData(), events(), info(), destroy()

   paint(t) is a pure function of (t, settings, layout): every style value is computed from t alone and compared with
   what was written last, so seeking 3.0 -> 1.0 -> 3.0 leaves the identical DOM. The engine never plays, pauses or
   seeks a video: it only transforms wrappers and toggles visibility. No Date.now, no unseeded Math.random. */
(function (root) {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';
  var CAPK = 0.86;                                   // row box height = CAPK * s
  var SHX = -0.6, SY = -0.35, DX = 30, DY = 10;      // shadow matrix (spike)
  var BASE_RENDER = 'assets/engine/fonts/', BASE_LIVE = '/engine/fonts/';
  var ENTRANCES = { slide: 1, drop: 1, rise: 1, type: 1, pop: 1, wipe: 1 };
  var ENDINGS = { cut: 1, exit: 1, dive: 1, sink: 1 };
  var uidSeq = 0;

  function FL() { return root.FTLayout; }
  function FD() { return root.FT_DATA; }
  function clamp01(u) { return u < 0 ? 0 : (u > 1 ? 1 : u); }
  function smooth01(u) { u = clamp01(u); return u * u * (3 - 2 * u); }
  function r2(v) { return Math.round(v * 100) / 100; }
  function r3(v) { return Math.round(v * 1000) / 1000; }
  function r4(v) { return Math.round(v * 10000) / 10000; }
  function backOutS(p, s) { p -= 1; return p * p * ((s + 1) * p + s) + 1; }          // gsap back.out(s)
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function hexRgb(h) {
    h = String(h || '#808080').replace('#', '');
    if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    var n = parseInt(h, 16);
    if (isNaN(n)) n = 0x808080;
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  // ---- settings with every field present
  function normalize(s) {
    var D = FD(), P0 = D.PALETTES[0];
    s = clone(s || {});
    s.text = s.text || {};
    s.text.phrase = s.text.phrase == null ? '' : String(s.text.phrase);
    s.text.hero = s.text.hero == null ? '' : String(s.text.hero);
    s.text.small = s.text.small == null ? '' : String(s.text.small);
    s.text.source = s.text.source || 'typed';
    s.palette = s.palette || {};
    s.palette.floor = s.palette.floor || P0.floor;
    s.palette.ink = s.palette.ink || P0.ink;
    s.palette.small = s.palette.small || P0.small;
    if (!D.FONTS[s.font]) s.font = 'condensed';
    if (!FL().THETA[s.layout]) s.layout = 'wall';
    if (!ENTRANCES[s.entrance]) s.entrance = 'slide';
    if (!FL().CAMS[s.camera]) s.camera = 'pull';
    if (!FL().PACES[s.pace]) s.pace = 'smooth';
    if (!ENDINGS[s.ending]) s.ending = 'cut';
    var fx = s.fx || {};
    s.fx = { shadow: !!fx.shadow, blur: !!fx.blur, focus: !!fx.focus, grain: !!fx.grain, vignette: !!fx.vignette, texture: !!fx.texture };
    s.sound = s.sound || { voice: true, sfx: true };
    return s;
  }

  // ---- fonts
  function baseOf(opts) { return (opts && opts.fontsBase) || (opts && opts.mode === 'render' ? BASE_RENDER : BASE_LIVE); }
  // Every row is drawn with the stack "FT <font>", "FT Inter": a character the font lacks (Gochi Hand has no Latin Extended-A,
  // a few fonts lack rare letters) falls to Inter. The Inter face is scaled by CSS size-adjust so its cap height matches the
  // font's, the same factor metrics.js (fbAdj) used for the widths of those characters. One page draws one font at a time;
  // injecting another font rewrites the Inter rule.
  var INTER_FAMILY = 'FT Inter', INTER_FILE = 'inter.woff2';
  function stackOf(F) { return '"' + F.family + '", "' + INTER_FAMILY + '"'; }
  function injectFace(fontId, base) {
    var F = FD().FONTS[fontId], id = 'ft-font-' + fontId, st;
    if (!F || document.getElementById(id)) return;
    st = document.createElement('style');
    st.id = id;
    st.textContent = '@font-face{font-family:"' + F.family + '";src:url("' + base + F.file + '") format("woff2");font-weight:' +
      (F.weightRange || F.weight || 400) + ';font-style:normal;font-display:block}';
    document.head.appendChild(st);
  }
  function injectInter(adj, base) {
    var css = '@font-face{font-family:"' + INTER_FAMILY + '";src:url("' + base + INTER_FILE + '") format("woff2");font-weight:100 900;' +
      'font-style:normal;font-display:block;size-adjust:' + Math.round(adj * 10000) / 100 + '%}';
    var st = document.getElementById('ft-font-inter');
    if (!st) { st = document.createElement('style'); st.id = 'ft-font-inter'; document.head.appendChild(st); }
    if (st.textContent !== css) st.textContent = css;
  }
  function injectFont(fontId, base) {
    var F = FD().FONTS[fontId];
    if (!F) return;
    injectFace(fontId, base);
    var M = root.FT_METRICS && root.FT_METRICS[fontId];
    injectInter(M && M.fbAdj ? M.fbAdj : 1, base);
  }
  function loadFont(fontId, base) {
    var F = FD().FONTS[fontId];
    if (!F) return Promise.resolve();
    try {
      injectFont(fontId, base);
      if (document.fonts && document.fonts.load) {
        // both faces are fetched now: Inter would otherwise load the first time a fallback glyph is painted, too late for a render
        var sample = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
        return Promise.all([document.fonts.load((F.weight || 400) + ' 100px "' + F.family + '"', sample),
                            document.fonts.load((F.weight || 400) + ' 100px "' + INTER_FAMILY + '"', sample)]).then(function () {}, function () {});
      }
    } catch (e) { /* fall through */ }
    return Promise.resolve();
  }
  // Every look font and Inter, fetched up front (the studio calls this once at start-up): switching looks, and the look
  // tiles, never wait on a font. Resolves when every load has settled, a missing file included.
  var SAMPLE = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789';
  function preloadFonts(base) {
    base = base || BASE_LIVE;
    var fonts = FD().FONTS, weights = {}, jobs = [];
    function load(spec) {
      try { if (document.fonts && document.fonts.load) jobs.push(document.fonts.load(spec, SAMPLE).then(function () {}, function () {})); }
      catch (e) { /* a font the browser will not parse is skipped */ }
    }
    if (!document.getElementById('ft-font-inter')) injectInter(1, base);
    Object.keys(fonts).forEach(function (id) {
      var F = fonts[id], w = F.weight || 400;
      injectFace(id, base);
      weights[w] = true;
      load(w + ' 100px "' + F.family + '"');
    });
    Object.keys(weights).forEach(function (w) { load(w + ' 100px "' + INTER_FAMILY + '"'); });
    return Promise.all(jobs).then(function () {});
  }
  function prepareFont(settings, opts) { return loadFont(normalize(settings).font, baseOf(opts)); }

  // ---- floor texture tile: feTurbulence (baseFrequency 0.9, 2 octaves, seed 7) desaturated into alpha.
  // mix-blend-mode cannot see the floor colour from inside the 3D plane, so multiply is emulated with a black overlay
  // whose alpha is 1 - noise, screen with a white overlay whose alpha is noise (same result against a flat floor).
  function texTile(light) {
    var C = light ? 0 : 1, a = light ? '-0.3333' : '0.3333', b = light ? 1 : 0;
    var svg = "<svg xmlns='http://www.w3.org/2000/svg' width='600' height='600'><filter id='n' x='0' y='0' width='100%' height='100%' " +
      "color-interpolation-filters='sRGB'><feTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' seed='7' stitchTiles='stitch'/>" +
      "<feColorMatrix type='matrix' values='0 0 0 0 " + C + " 0 0 0 0 " + C + " 0 0 0 0 " + C + " " + a + " " + a + " " + a + " 0 " + b + "'/></filter>" +
      "<rect width='600' height='600' filter='url(%23n)'/></svg>";
    return 'url("data:image/svg+xml;utf8,' + svg.replace(/</g, '%3C').replace(/>/g, '%3E') + '")';
  }

  // entrance order of a row's words: lead words left to right, then outward alternating right / left
  function entranceOrder(r) {
    var n = r.words.length, out = [], a, b, i, lo, hi, right = true;
    if (!n) return out;
    a = Math.max(0, Math.min(n - 1, r.leadFrom || 0));
    b = Math.max(a, Math.min(n - 1, r.leadTo == null ? n - 1 : r.leadTo));
    for (i = a; i <= b; i++) out.push(i);
    lo = a - 1; hi = b + 1;
    while (lo >= 0 || hi < n) {
      if (right) { if (hi < n) out.push(hi++); else out.push(lo--); }
      else { if (lo >= 0) out.push(lo--); else out.push(hi++); }
      right = !right;
    }
    return out;
  }

  // ============================================================================================ the engine
  function Engine(rootEl, take, settings, opts) {
    this.rootEl = rootEl;
    this.take = take;
    this.opts = opts || {};
    this.mode = this.opts.mode === 'render' ? 'render' : 'live';
    this.fontsBase = baseOf(this.opts);
    this.settings = normalize(settings);
    this.uid = 'ftb' + (++uidSeq) + '-';
    this.duration = take.dur;
    this.fps = take.fps > 0 ? take.fps : 24;
    this.t = 0;
    this._c = {};            // last value written per scene property
    this._noise = [];        // lazily built grain frames
    this._gi = -1;
    this._seq = 0;
    this.rows = [];
    this._grab();
    this._styleTake();
    this.layout = this.opts.layout || FL().build(take, this.settings);
    this._buildRows();
    this._styleStatic();
    this.ready = loadFont(this.settings.font, this.fontsBase);
    this.paint(0);
  }

  Engine.prototype._grab = function () {
    var r = this.rootEl, el = {};
    function q(sel) { return r.querySelector(sel); }
    el.world = q('.ft-world'); el.cam = q('.ft-cam'); el.floor = q('.ft-floor'); el.tex = q('.ft-tex'); el.para = q('.ft-para');
    el.ao = q('.ft-ao'); el.sw = q('.ft-sw'); el.pw = q('.ft-pw'); el.vig = q('.ft-vig'); el.grain = q('.ft-grain'); el.flash = q('.ft-flash');
    el.defs = q('.ft-defs defs');
    ['world', 'floor', 'para', 'pw'].forEach(function (k) { if (!el[k]) throw new Error('Floored: scene skeleton incomplete, .ft-' + k + ' is missing'); });
    if (!el.defs) {
      var svg = q('.ft-defs');
      if (!svg) { svg = document.createElementNS(NS, 'svg'); svg.setAttribute('class', 'ft-defs'); svg.setAttribute('width', '0'); svg.setAttribute('height', '0'); r.appendChild(svg); }
      el.defs = document.createElementNS(NS, 'defs'); svg.appendChild(el.defs);
    }
    this.el = el;
  };

  // geometry that depends on the take only: shadow matrix, contact shadow, wrapper sizes
  Engine.prototype._styleTake = function () {
    var tk = this.take, el = this.el, w = tk.w || 1080, h = tk.h || 1920, k0 = tk.k0, f = tk.feet;
    var a = k0, c = k0 * SHX, d = k0 * SY, e = DX - a * f.x - c * f.y, g = DY - d * f.y;
    el.pw.style.width = w + 'px'; el.pw.style.height = h + 'px';
    if (el.sw) {
      el.sw.style.width = w + 'px'; el.sw.style.height = h + 'px';
      el.sw.style.transform = 'matrix(' + [a, 0, c, d, e, g].map(r4).join(',') + ')';
    }
    if (el.ao) {
      var aw = tk.aoWidth || 300, ah = 0.42 * aw;
      el.ao.style.width = aw + 'px'; el.ao.style.height = ah + 'px';
      el.ao.style.left = (-aw / 2) + 'px'; el.ao.style.top = (-ah / 2) + 'px';
    }
  };

  // colours, vignette, texture: rewritten whenever settings change
  Engine.prototype._styleStatic = function () {
    var S = this.settings, P = S.palette, el = this.el, rs = this.rootEl.style;
    rs.setProperty('--ft-floor', P.floor); rs.setProperty('--ft-ink', P.ink); rs.setProperty('--ft-small', P.small);
    var fl = hexRgb(P.floor);
    if (el.vig) {
      var dk = fl.map(function (v) { return Math.round(v * 0.3); });
      el.vig.style.background = 'radial-gradient(120% 85% at 56% 46%, transparent 52%, rgba(' + dk.join(',') + ', 0.22) 100%)';
    }
    if (el.tex) {
      var lum = (0.2126 * fl[0] + 0.7152 * fl[1] + 0.0722 * fl[2]) / 255, dark = lum < 0.2;
      el.tex.style.backgroundImage = texTile(!dark);
      this._texOp = dark ? '0.08' : '0.14';
    }
    this._c = {};                                      // force the next paint to rewrite the scene layers
    this._gi = -1;
  };

  // ---- rows
  Engine.prototype._buildRows = function () {
    var self = this, lay = this.layout, S = this.settings, fx = S.fx, T = lay.timing, D = FD(), F = D.FONTS[S.font], M = root.FT_METRICS[S.font];
    var Lm = FL(), el = this.el, mode = S.entrance, id0 = this.uid;
    var para = el.para, defs = el.defs;
    para.textContent = '';
    while (defs.firstChild) defs.removeChild(defs.firstChild);
    this.rows = [];
    var dmap = { slide: T.SLIDE, drop: 0.9 * T.SLIDE, rise: T.SLIDE, wipe: 1.1 * T.SLIDE };
    var cov = Lm.coverage(lay.theta), maxDist = 1;
    lay.rows.forEach(function (r) { var cy = r.rot ? r.top - r.width / 2 : r.top + 0.43 * r.s; if (Math.abs(cy) > maxDist) maxDist = Math.abs(cy); });

    lay.rows.forEach(function (r, idx) {
      var nudge = Lm.nudge(S.font, r.fontSize);
      var div = document.createElement('div');
      div.className = 'ft-row' + (r.kind === 'small' ? ' ft-small' : '') + (r.plate ? ' ft-plate' : '');
      div.setAttribute('data-ft-id', r.id);
      var st = div.style;
      st.fontFamily = stackOf(F); st.fontWeight = String(F.weight || 400); st.fontSize = r.fontSize + 'px';
      st.lineHeight = String(M.capH); st.letterSpacing = (F.ls || 0) + 'em';
      var spans = [];
      r.words.forEach(function (w, i) {
        var sp = document.createElement('span');
        sp.className = 'ft-w'; sp.textContent = w.text;
        div.appendChild(sp); spans.push(sp);
        if (i < r.words.length - 1) div.appendChild(document.createTextNode(' '));
      });
      var wrap = null;
      if (r.rot) {                                     // hero column: rotated wrapper, the row sits inside at (0, nudge)
        wrap = document.createElement('div');
        wrap.className = 'ft-rot';
        wrap.style.left = r.left + 'px'; wrap.style.top = r.top + 'px'; wrap.style.transform = 'rotate(' + r.rot + 'deg)';
        st.left = '0px'; st.top = nudge + 'px';
        wrap.appendChild(div); para.appendChild(wrap);
      } else {
        st.left = r.left + 'px'; st.top = (r.top + nudge) + 'px';
        para.appendChild(div);
      }

      var m = r.kind === 'small' ? 'small' : mode;
      var R = {
        r: r, el: div, wrap: wrap, words: spans, mode: m, nudge: nudge, c: {}, wc: [], dirty: false,
        D: dmap[m] || 0, exitDur: 0, exitDelay: 0, fe: null, furl: '', pw: false, rank: null, delay: 0, tEnd: 0
      };
      // exit ending: rows nearest the feet leave last
      if (T.ending === 'exit' && T.E > 0) {
        var cy = r.rot ? r.top - r.width / 2 : r.top + 0.43 * r.s, dn = Math.min(1, Math.abs(cy) / maxDist);
        R.exitDelay = (1 - dn) * 0.35 * T.E; R.exitDur = 0.65 * T.E;
      }
      // per-word entrances (type, pop) and the small line
      if (m === 'type' || m === 'pop' || m === 'small') {
        R.pw = true;
        var order = entranceOrder(r), rank = [], i;
        if (m === 'small') order = r.words.map(function (w, i2) { return i2; });
        for (i = 0; i < order.length; i++) rank[order[i]] = i;
        R.rank = rank;
        R.delay = m === 'type' ? 0.045 : (m === 'pop' ? 0.03 : (r.step || T.SMALL));
        R.tEnd = r.tin + R.delay * Math.max(0, r.words.length - 1) + (m === 'type' ? 0.08 : (m === 'pop' ? 0.35 : 0));
        for (i = 0; i < r.words.length; i++) R.wc.push({ v: null, tf: null });
      }
      // transform origins
      if (m === 'drop') div.style.transformOrigin = r.leadCx + 'px ' + r3(0.43 * r.s - nudge) + 'px';
      else if (m === 'rise') div.style.transformOrigin = '0px ' + r3(CAPK * r.s - nudge) + 'px';
      // wipe: sweep the clip across the part of the row any camera can see
      if (m === 'wipe') {
        var a0 = 0, a1 = r.width;
        if (!r.rot) {
          var rng = Lm.xRange(cov, r.top, r.top + CAPK * r.s, 0);
          if (rng) { a0 = Math.max(0, rng[0] - r.left); a1 = Math.min(r.width, rng[1] - r.left); if (a1 <= a0) { a0 = 0; a1 = r.width; } }
        }
        R.wa0 = a0; R.wa1 = a1;
      }
      // one blur filter per row that can ever blur (as the spike)
      if (fx.blur || (fx.focus && r.depth > 0)) {
        var f = document.createElementNS(NS, 'filter'), fb = document.createElementNS(NS, 'feGaussianBlur');
        f.setAttribute('id', id0 + idx);
        f.setAttribute('x', '-60%'); f.setAttribute('y', '-40%'); f.setAttribute('width', '220%'); f.setAttribute('height', '180%');
        f.setAttribute('color-interpolation-filters', 'sRGB');
        fb.setAttribute('stdDeviation', '0 0');
        f.appendChild(fb); defs.appendChild(f);
        R.fe = fb; R.furl = 'url(#' + id0 + idx + ')';
      }
      self.rows.push(R);
    });
  };

  // cached write of one row's style
  Engine.prototype._put = function (R, vis, tf, op, bx, by, clip) {
    var s = R.el.style, c = R.c, v = vis ? 'visible' : 'hidden', i;
    if (!vis) {
      if (c.v === 'hidden' && c.clean) return;           // already in the canonical hidden state
      s.visibility = 'hidden'; c.v = 'hidden';
      // a hidden row carries no leftovers of its visible life: the DOM stays a pure function of t
      s.transform = ''; s.opacity = ''; s.clipPath = ''; s.filter = '';
      c.tf = c.op = c.cp = c.fl = undefined;
      if (R.fe) { R.fe.setAttribute('stdDeviation', '0 0'); c.fe = '0 0'; }
      if (R.pw && R.dirty) {
        for (i = 0; i < R.words.length; i++) { R.words[i].style.visibility = ''; R.words[i].style.transform = ''; R.wc[i].v = undefined; R.wc[i].tf = undefined; }
        R.dirty = false;
      }
      c.clean = true;
      return;
    }
    c.clean = false;
    if (c.v !== v) { s.visibility = v; c.v = v; }
    if (c.tf !== tf) { s.transform = tf; c.tf = tf; }
    if (c.op !== op) { s.opacity = op; c.op = op; }
    if (c.cp !== clip) { s.clipPath = clip; c.cp = clip; }
    if (R.fe) {
      var fl = 'none', fe = '0 0';          // blur off = filter unreferenced AND its sigma back at 0, so the DOM is a function of t
      if (bx > 0.25 || by > 0.25) { fe = r2(bx) + ' ' + r2(by); fl = R.furl; }
      if (c.fe !== fe) { R.fe.setAttribute('stdDeviation', fe); c.fe = fe; }
      if (c.fl !== fl) { s.filter = fl; c.fl = fl; }
    }
  };

  // position along the row's own axis (px): slide entrance + exit ending
  function posX(R, t, te) {
    var r = R.r, x = 0, p, q;
    if (R.mode === 'slide') {
      p = (t - r.tin) / R.D;
      if (p < 1) x = r.dir * r.off * (1 - FL().backOut(p < 0 ? 0 : p));
    }
    if (R.exitDur > 0) {
      q = (t - te - R.exitDelay) / R.exitDur;
      if (q > 0) { if (q > 1) q = 1; x -= r.dir * r.off * q * q; }
    }
    return x;
  }

  Engine.prototype._wipeClip = function (R, pp) {
    var W = R.r.width, xb;
    if (R.r.dir > 0) { xb = R.wa1 + (R.wa0 - R.wa1) * pp; return 'inset(-100% 0px -100% ' + r3(xb) + 'px)'; }
    xb = R.wa0 + (R.wa1 - R.wa0) * pp;
    return 'inset(-100% ' + r3(W - xb) + 'px -100% 0px)';
  };

  Engine.prototype._words = function (R, t) {
    var r = R.r, n = R.words.length, i, tw, p, sc, vis, tf, c, w;
    if (t >= R.tEnd) {                                  // settled: words back to the stylesheet default (visible, no transform)
      if (R.dirty) {
        for (i = 0; i < n; i++) { w = R.words[i].style; w.visibility = ''; w.transform = ''; R.wc[i].v = undefined; R.wc[i].tf = undefined; }
        R.dirty = false;
      }
      return;
    }
    R.dirty = true;
    for (i = 0; i < n; i++) {
      tw = r.tin + R.delay * R.rank[i]; tf = 'none';
      if (t < tw) vis = 'hidden';
      else {
        vis = 'visible';
        if (R.mode === 'type') { p = clamp01((t - tw) / 0.08); sc = 1.06 - 0.06 * p; if (p < 1) tf = 'scale(' + r4(sc) + ')'; }
        else if (R.mode === 'pop') { p = clamp01((t - tw) / 0.35); if (p < 1) tf = 'scale(' + r4(backOutS(p, 2.2)) + ')'; }
      }
      c = R.wc[i];
      if (c.v !== vis) { R.words[i].style.visibility = vis; c.v = vis; }
      if (c.tf !== tf) { R.words[i].style.transform = tf; c.tf = tf; }
    }
  };

  Engine.prototype._row = function (R, t, X) {
    var r = R.r, T = X.T, mode = R.mode, fx = X.fx, bx = 0, by = 0, sc = 1, sy = 1, op = 1, clip = 'none', p, x, xp, d;
    if (t < r.tin) { this._put(R, false); return; }
    if (R.exitDur > 0 && (t - T.te - R.exitDelay) / R.exitDur >= 1) { this._put(R, false); return; }   // slid out
    x = posX(R, t, T.te);
    if (fx.blur && (mode === 'slide' || R.exitDur > 0)) {
      xp = posX(R, t - X.DT, T.te);
      bx = Math.min(90, Math.abs(x - xp) * 0.18);
    }
    if (mode === 'drop') {
      p = (t - r.tin) / R.D;
      if (p < 1) {
        sc = 1 + 1.4 * (1 - FL().backOut(p)); op = clamp01(p / 0.25);
        if (fx.blur) { d = 14 * (1 - p) * (1 - p); bx += d; by += d; }
      }
    } else if (mode === 'rise') {
      p = (t - r.tin) / R.D;
      if (p < 1) { sy = Math.max(0.0001, FL().backOut(p)); op = clamp01(p / 0.15); }
    } else if (mode === 'wipe') {
      p = (t - r.tin) / R.D;
      if (p < 1) { var pp = 1 - Math.pow(1 - p, 3); x += r.dir * 120 * (1 - pp); clip = this._wipeClip(R, pp); }
    }
    if (fx.focus && r.depth > 0) { d = r.depth * 2.4 * X.fp; if (d > 0) { bx += d; by += d; } }
    var tf = '';
    if (x !== 0) tf = 'translateX(' + r3(x) + 'px)';
    if (sc !== 1) tf += (tf ? ' ' : '') + 'scale(' + r4(sc) + ')';
    if (sy !== 1) tf += (tf ? ' ' : '') + 'scaleY(' + r4(sy) + ')';
    if (!tf) tf = 'none';
    this._put(R, true, tf, op >= 1 ? '1' : String(r3(op)), bx, by, clip);
    if (R.pw) this._words(R, t);
  };

  Engine.prototype._set = function (key, el, prop, val) {
    if (!el) return;
    var c = this._c;
    if (c[key] !== val) { el.style[prop] = val; c[key] = val; }
  };

  // Grain: GRAIN_FRAMES seeded noise frames, picked by film frame number. Both are pure (no state, no clock), so the studio
  // at seek(t) and the render at frame n lay the same noise on a canvas of the same size (tests/js/grain.test.js pins it).
  var GRAIN_FRAMES = 6;
  function grainIndex(t, fps) { var gi = Math.round(t * fps) % GRAIN_FRAMES; return gi < 0 ? gi + GRAIN_FRAMES : gi; }
  function grainFill(d, idx) {                         // d: RGBA bytes of the grain canvas, filled in place
    var rnd = mulberry32(7000 + idx * 977), i, v;
    for (i = 0; i < d.length; i += 4) {
      v = 128 + (rnd() + rnd() + rnd() - 1.5) * 120;
      d[i] = d[i + 1] = d[i + 2] = v < 0 ? 0 : (v > 255 ? 255 : v); d[i + 3] = 255;
    }
    return d;
  }

  Engine.prototype._grainFrame = function (idx) {
    var cv = this.el.grain;
    if (!cv || !cv.getContext) return;
    var ctx = cv.getContext('2d'), W = cv.width, H = cv.height;
    if (!this._noise[idx]) {
      var img = ctx.createImageData(W, H);
      grainFill(img.data, idx);
      this._noise[idx] = img;
    }
    ctx.putImageData(this._noise[idx], 0, 0);
  };

  // ---- paint
  Engine.prototype.paint = function (t) {
    t = +t || 0;
    this.t = t;
    var Lm = FL(), S = this.settings, lay = this.layout, T = lay.timing, fx = S.fx, tk = this.take, el = this.el, i;
    var u = Lm.inOut(clamp01(t / T.Tcam)), c = Lm.camState(S.camera, u);
    var q = (T.E > 0 && t > T.te) ? clamp01((t - T.te) / T.E) : 0, ending = T.ending;
    var Sf = c.S, Af = c.A, paraOp = 1, shK = 1;
    if (ending === 'sink' && q > 0) { Sf = c.S * (1 - 0.75 * q * q); Af = c.A + 15 * q; paraOp = 1 - Math.pow(q, 1.5); shK = 1 - q; }
    this._set('floor', el.floor, 'transform', 'translate3d(' + r3(c.ax) + 'px,' + r3(c.ay) + 'px,0) rotateX(' + r3(Af) + 'deg) scale(' + r4(Sf) + ')');
    this._set('para', el.para, 'transform', 'rotate(' + r3(-lay.theta + c.spin) + 'deg)');
    this._set('paraOp', el.para, 'opacity', paraOp >= 1 ? '1' : String(r4(paraOp)));
    var k = c.S * tk.k0;                                 // the person keeps the camera's own scale
    this._set('pw', el.pw, 'transform', 'translate(' + r3(c.ax - tk.feet.x * k) + 'px,' + r3(c.ay - tk.feet.y * k) + 'px) scale(' + r4(k) + ')');
    this._set('swOp', el.sw, 'opacity', fx.shadow ? String(r4(0.36 * shK)) : '0');
    this._set('aoOp', el.ao, 'opacity', fx.shadow ? String(r4(shK)) : '0');
    // dive: 2D zoom of the whole scene into the head, white flash at the end
    var wtf = 'none', wfl = 'none', flash = '0';
    if (ending === 'dive' && q > 0) {
      var hx = c.ax, hy = c.ay - 0.82 * tk.height * k, q2 = q * q, m = 1 + 5 * q * q * q;
      wtf = 'translate(' + r3((540 - hx) * q2) + 'px,' + r3((860 - hy) * q2) + 'px) translate(' + r3(hx) + 'px,' + r3(hy) + 'px) scale(' + r4(m) +
        ') translate(' + r3(-hx) + 'px,' + r3(-hy) + 'px)';
      wfl = 'blur(' + r3((fx.blur ? 12 : 6) * q2) + 'px)';
      flash = String(r3(smooth01((q - 0.55) / 0.45)));
    }
    this._set('worldTf', el.world, 'transform', wtf);
    this._set('worldFl', el.world, 'filter', wfl);
    this._set('flash', el.flash, 'opacity', flash);
    // effects
    this._set('vig', el.vig, 'opacity', fx.vignette ? '1' : '0');
    // sink: the 8000 px texture plane fades with the floor text, else its far edge shows as a hard line once the floor shrinks
    this._set('tex', el.tex, 'opacity', fx.texture ? (paraOp >= 1 ? this._texOp : String(r4(+this._texOp * paraOp))) : '0');
    if (fx.grain) {
      this._set('grainOp', el.grain, 'opacity', '0.12');
      var gi = grainIndex(t, this.fps);
      if (this._gi !== gi) { this._grainFrame(gi); this._gi = gi; }
    } else this._set('grainOp', el.grain, 'opacity', '0');
    // rows
    var X = { T: T, fx: fx, DT: 1 / this.fps, fp: 1 - smooth01((t - 1.4) / 1.2) };
    for (i = 0; i < this.rows.length; i++) this._row(this.rows[i], t, X);
  };

  // ---- settings
  Engine.prototype.set = function (settings) {
    var old = this.settings, nu = normalize(settings), self = this, mySeq = ++this._seq;
    var relayout = !same(old.text, nu.text) || old.font !== nu.font || old.layout !== nu.layout || old.pace !== nu.pace ||
                   old.ending !== nu.ending || old.camera !== nu.camera;
    var rebuild = relayout || old.entrance !== nu.entrance || old.fx.blur !== nu.fx.blur || old.fx.focus !== nu.fx.focus;
    this.settings = nu;
    if (relayout) this.layout = FL().build(this.take, nu);
    if (rebuild) this._buildRows();
    this._styleStatic();
    this.paint(this.t);
    return loadFont(nu.font, this.fontsBase).then(function () {
      if (self._seq === mySeq) { self._c = {}; self.paint(self.t); }
      return self;
    });
  };

  Engine.prototype.layoutData = function () { return clone(this.layout); };

  Engine.prototype.info = function () {
    var lay = this.layout, T = lay.timing, M = root.FT_METRICS[this.settings.font] || {}, F = FD().FONTS[this.settings.font] || {};
    return {
      chunks: lay.chunks.map(function (c) { return c.text; }), rowCount: lay.rows.length, Tc: T.Tc, te: T.te, E: T.E,
      ending: T.ending, camera: T.camera, pace: T.pace, speech: T.speech, theta: lay.theta, layout: lay.layout,
      font: { id: this.settings.font, family: F.family, ls: F.ls || 0, capH: M.capH, asc: M.asc, desc: M.desc, fallback: M.fallback, unit: lay.unit }
    };
  };

  // sound events for sfx.py: [{t, kind, gain}] sorted by t
  Engine.prototype.events = function () {
    var S = this.settings, lay = this.layout, T = lay.timing, mode = S.entrance, ev = [], self = this;
    var D = { slide: T.SLIDE, drop: 0.9 * T.SLIDE, rise: T.SLIDE, wipe: 1.1 * T.SLIDE };
    var whoosh = !!D[mode], land = mode === 'slide' || mode === 'drop' || mode === 'rise';
    var words = [], firstFiller = null, small = null;
    function add(t, kind, gain) { ev.push({ t: r3(Math.max(0, t)), kind: kind, gain: gain }); }
    lay.rows.forEach(function (r) {
      var k = r.kind;
      if (k === 'small') { small = r; return; }
      if (k === 'filler' || r.extra) { if (firstFiller == null || r.tin < firstFiller) firstFiller = r.tin; return; }
      if (whoosh) add(r.tin, 'whoosh', (k === 'hero' || k === 'giant') ? 1.0 : 0.8);
      if (land && (k === 'designed' || k === 'hero' || k === 'giant' || k === 'line')) add(r.tin + 0.55 * D[mode], 'land', 0.7);
      if ((mode === 'pop' || mode === 'type') && k !== 'left') {
        var ord = entranceOrder(r), dl = mode === 'pop' ? 0.03 : 0.045, nLead = Math.max(1, (r.leadTo == null ? r.words.length - 1 : r.leadTo) - (r.leadFrom || 0) + 1);
        for (var i = 0; i < Math.min(nLead, ord.length); i++) words.push(r.tin + dl * i);
      }
    });
    if (firstFiller != null) add(firstFiller, 'swarm', 0.6);
    words.sort(function (a, b) { return a - b; });
    if (mode === 'pop') words.slice(0, 12).forEach(function (t) { add(t, 'pop', 0.7); });
    if (mode === 'type') words.slice(0, 24).forEach(function (t) { add(t, 'tick', 0.5); });
    if (small) for (var j = 0; j < small.words.length; j++) add(small.tin + (small.step || T.SMALL) * j, 'tick', 0.4);
    if (T.ending === 'exit') add(T.te, 'whoosh', 0.9);
    else if (T.ending === 'dive') { add(T.te - 0.2, 'riser', 0.8); add(T.dur - 0.05, 'hit', 1.0); }
    else if (T.ending === 'sink') add(T.te, 'boom', 0.9);
    return ev.map(function (e, i) { return [e, i]; }).sort(function (a, b) { return a[0].t - b[0].t || a[1] - b[1]; }).map(function (p) { return p[0]; });
  };

  Engine.prototype.destroy = function () {
    this.el.para.textContent = '';
    while (this.el.defs.firstChild) this.el.defs.removeChild(this.el.defs.firstChild);
    this.rows = [];
  };

  function createSync(rootEl, take, settings, opts) {
    var s = normalize(settings), base = baseOf(opts);
    injectFont(s.font, base);
    return new Engine(rootEl, take, settings, opts);
  }
  function create(rootEl, take, settings, opts) {
    return loadFont(normalize(settings).font, baseOf(opts)).then(function () { return createSync(rootEl, take, settings, opts); });
  }

  root.Floored = { create: create, createSync: createSync, prepareFont: prepareFont, preloadFonts: preloadFonts, version: '1.0',
    grain: { frames: GRAIN_FRAMES, index: grainIndex, fill: grainFill } };   // pure helpers, exposed for tests/js/grain.test.js
})(typeof window !== 'undefined' ? window : this);
