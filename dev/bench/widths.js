/* Bench-only width test, injected by make.py --widths in place of the template's timeline registration.
   Claim under test: the DOM width of every row equals the width layout.js computed from FT_METRICS (so the lead chunk
   really sits where the layout put it) in every font. For each of the 6 fonts: engine.set({font}), wait for the font,
   then compare row.offsetWidth with row.r.width for all rows. The verdict is drawn on the frame; the timeline is
   registered only afterwards (HyperFrames waits for it). */
(async function () {
  var e = window.__ft, base = JSON.parse(JSON.stringify(e.settings));
  var fonts = ['condensed', 'serif', 'geo', 'mono', 'stencil', 'hand'], lines = [];
  var FD = window.FT_DATA.FONTS;
  for (var fi = 0; fi < fonts.length; fi++) {
    var f = fonts[fi], s = JSON.parse(JSON.stringify(base));
    s.font = f;
    try {
      await e.set(s);
      await document.fonts.ready;
      e.paint(3.0);
      var fam = FD[f].family, loaded = document.fonts.check(FD[f].weight + ' 100px "' + fam + '"');
      var worst = 0, worstId = '', sum = 0, n = 0, relWorst = 0;
      e.rows.forEach(function (R) {
        var w = R.el.offsetWidth, L = R.r.width, err = w - L;
        sum += Math.abs(err); n++;
        if (Math.abs(err) > Math.abs(worst)) { worst = err; worstId = R.r.id + ' (' + w + ' vs ' + Math.round(L) + ')'; }
        if (Math.abs(err) / L > relWorst) relWorst = Math.abs(err) / L;
      });
      lines.push(f + ': ' + n + ' rows, font ' + (loaded ? 'loaded' : 'NOT LOADED') + ', worst dw ' + worst.toFixed(1) + ' px at ' + worstId + ', mean |dw| ' + (sum / n).toFixed(2) + ' px, worst rel ' + (relWorst * 100).toFixed(3) + '%');
    } catch (err) { lines.push(f + ': ERROR ' + (err && err.message)); }
  }
  await e.set(base); e.paint(0);
  var msg = 'WIDTHS (DOM offsetWidth vs layout width)\n' + lines.join('\n');
  window.__widths = msg;
  var d = document.createElement('div');
  d.textContent = msg;
  d.style.cssText = 'position:fixed;left:20px;top:20px;z-index:99999;font:700 21px monospace;color:#0f0;background:#000;padding:8px;width:1010px;white-space:pre-wrap;word-break:break-all';
  document.body.appendChild(d);
  window.__timelines = window.__timelines || {};
  window.__timelines['main'] = window.__bench_tl;
})();
