/* Bench-only purity test, injected by make.py --purity right after the template registers its timeline.
   Claim under test: engine.paint(t) leaves the DOM in the same state whatever was painted before it.
   For 16 variants of the settings (every entrance, ending, layout, a camera, all fx on / off) and every ordered pair
   (a, b) of 7 instants: paint(a), record the whole DOM state (every style property, every attribute), paint(b),
   paint(a), compare. The verdict is drawn on the frame so a HyperFrames snapshot shows it (and kept in window.__purity). */
(function () {
  var e = window.__ft, root = document.getElementById('root');
  function norm() {
    var out = [], all = root.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
      var n = all[i], st = n.style, o = {}, j, k;
      for (j = 0; j < st.length; j++) o['s.' + st[j]] = st.getPropertyValue(st[j]);
      for (k = 0; k < n.attributes.length; k++) if (n.attributes[k].name !== 'style') o['a.' + n.attributes[k].name] = n.attributes[k].value;
      out.push({ k: n.tagName + '#' + (n.getAttribute('data-ft-id') || String(n.getAttribute('class') || '') || i), o: o });
    }
    return out;
  }
  function diff(A, B, cnt, ex, tag) {
    var any = false;
    if (A.length !== B.length) { cnt.LEN = (cnt.LEN || 0) + 1; if (!ex.LEN) ex.LEN = tag + ' element count ' + A.length + ' != ' + B.length; return true; }
    for (var i = 0; i < A.length; i++) {
      var a = A[i].o, b = B[i].o, names = {}, p, nm;
      for (p in a) if (a[p] !== b[p]) names[p] = 1;
      for (p in b) if (a[p] !== b[p]) names[p] = 1;
      for (nm in names) {
        any = true;
        cnt[nm] = (cnt[nm] || 0) + 1;
        if (!ex[nm]) ex[nm] = tag + ' ' + A[i].k + ' ' + nm + ': ' + String(a[nm]).slice(0, 40) + ' != ' + String(b[nm]).slice(0, 40);
      }
    }
    return any;
  }
  var base = JSON.parse(JSON.stringify(e.settings));
  function variant(v) {
    var s = JSON.parse(JSON.stringify(base)), k, f;
    for (k in v) { if (k === 'fx') { for (f in v.fx) s.fx[f] = v.fx[f]; } else s[k] = v[k]; }
    return s;
  }
  var allOn = { shadow: true, blur: true, focus: true, vignette: true, grain: true, texture: true };
  var allOff = { shadow: false, blur: false, focus: false, vignette: false, grain: false, texture: false };
  var V = [
    ['base', {}], ['drop', { entrance: 'drop' }], ['rise', { entrance: 'rise' }], ['type', { entrance: 'type' }],
    ['pop', { entrance: 'pop' }], ['wipe', { entrance: 'wipe' }], ['exit', { ending: 'exit' }], ['dive', { ending: 'dive' }],
    ['sink', { ending: 'sink' }], ['cut', { ending: 'cut' }], ['stripes', { layout: 'stripes' }], ['giant', { layout: 'giant' }],
    ['poster', { layout: 'poster' }], ['orbit', { camera: 'orbit' }], ['allfx', { fx: allOn }], ['nofx', { fx: allOff }]
  ];
  var S = window.__PURITY_TIMES || [3.0, 0.2, 0.55, 1.0, 1.6, 4.5, 4.9];
  var failed = [], pairs = 0, errors = [];
  V.forEach(function (vv) {
    var cnt = {}, ex = {}, bad = 0;
    try {
      e.set(variant(vv[1]));
      S.forEach(function (a) {
        e.paint(a); var sa = norm();
        S.forEach(function (b) {
          if (a === b) return;
          e.paint(b); e.paint(a); pairs++;
          if (diff(sa, norm(), cnt, ex, a + '>' + b + '>' + a)) bad++;
        });
      });
    } catch (err) { errors.push(vv[0] + ': ' + (err && err.message)); }
    if (bad) {
      var names = Object.keys(cnt);
      failed.push(vv[0] + ' ' + bad + ' bad [' + names.slice(0, 4).map(function (n) { return n + 'x' + cnt[n]; }).join(', ') + '] e.g. ' + ex[names[0]]);
    }
  });
  var msg;
  if (failed.length || errors.length) msg = 'PURITY FAIL: ' + failed.slice(0, 3).join('  ||  ') + (errors.length ? '  ERRORS ' + errors.join('; ') : '') + '  (' + failed.length + ' of ' + V.length + ' variants failing)';
  else msg = 'PURITY OK: ' + V.length + ' variants x ' + S.length * (S.length - 1) + ' ordered pairs = ' + pairs + ' paint(a),paint(b),paint(a) round trips, every style and attribute identical';
  e.set(base); e.paint(0);
  window.__purity = msg;
  var d = document.createElement('div');
  d.textContent = msg;
  d.style.cssText = 'position:fixed;left:20px;top:20px;z-index:99999;font:700 22px monospace;color:#0f0;background:#000;padding:8px;width:1000px;white-space:normal;word-break:break-all';
  document.body.appendChild(d);
})();
