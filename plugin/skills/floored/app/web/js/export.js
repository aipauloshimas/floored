import { IC, btn, byId, callout, clamp, clone, fill, h, ico, svgWrap, switchEl, toast } from './util.js';
import { api, postJSON } from './api.js';
import { DEBUG, FONTS, LOOKS, isEdited, optLabel, palLabel } from './store.js';
import { RENDER_SEC_PER_FRAME, exportEstimateText, exportRunningText, outputLine, resultLine } from './copy.js';

var EXPORT_STEPS = [
  { id: 'writing', title: 'Preparing' },
  { id: 'rendering', title: 'Rendering frames' },
  { id: 'sound', title: 'Mixing sound' }
];

/* The Export dialog and the render it starts. `c` is the studio controller (studio.js). */
export function createExport(c) {
  var exportEl = null, ex = { phase: 'idle' }, exTimer = 0, lastFocus = null;
  var wantExport = false, exView = '', exBind = [], exRefs = null, exPrevPlaying = false, exSamples = [], exSampleStage = '';
  var EX_STEP_IDX = { starting: 0, writing: 0, rendering: 1, sound: 2 };
  var EX_STEP_NOTE = { writing: 'Setting things up', sound: 'Adding your voice and effects' };

  function exSyncAll() { for (var i = 0; i < exBind.length; i++) { try { exBind[i](); } catch (e) { DEBUG.log.push('exsync: ' + e.message); } } }
  /* seconds per frame for this machine (from /api/info); the server's own defaults until it answers */
  var secPerFrame = { '1': RENDER_SEC_PER_FRAME['1'], '2': RENDER_SEC_PER_FRAME['2'] }, infoAsked = false;
  function askInfo() {
    if (infoAsked) return;
    infoAsked = true;
    api('/api/info').then(function (info) {
      var e = info && info.estimates && info.estimates.renderSecPerFrame;
      if (e) ['1', '2'].forEach(function (k) { if (typeof e[k] === 'number' && e[k] > 0) secPerFrame[k] = e[k]; });
      exSyncAll();
    }).catch(function () { infoAsked = false; });
  }
  function is4K() { return c.take && c.take.tier === 2; }
  function baseName(p) { var s = String(p || '').split(/[\\/]/).pop(); try { return decodeURIComponent(s); } catch (e) { return s; } }

  function setExportBusy(on) {
    if (!c.ui.exportBtn) return;
    c.ui.exportBtn.classList.toggle('is-busy', !!on);
    var lab = c.ui.exportBtn.querySelector('.btn-label');
    if (lab) lab.textContent = on ? 'Rendering…' : 'Export';
  }

  function exSwitchRow(label, desc, getOn, onToggle, disabledReason) {
    var sw = switchEl(label, { disabled: !!disabledReason, onToggle: onToggle });
    exBind.push(function () { sw.setOn(getOn()); });
    return h('div', { class: 'switch-row' + (disabledReason ? ' is-disabled' : '') },
      h('div', { class: 'switch-text' }, h('span', { class: 'switch-label', text: label }), h('span', { class: 'switch-desc', text: disabledReason || desc })), sw);
  }

  function summaryCells() {
    var look = byId(LOOKS, c.S.look), nfx = Object.keys(c.S.fx).filter(function (k) { return c.S.fx[k]; }).length;
    return [
      ['Look', (look ? look.label : c.S.look) + (isEdited(c.S) ? ' (edited)' : '')],
      ['Colors', palLabel(c.S.palette)],
      ['Font', FONTS[c.S.font].label],
      ['Layout', optLabel('layout', c.S.layout)],
      ['Entrance', optLabel('entrance', c.S.entrance)],
      ['Camera', optLabel('camera', c.S.camera)],
      ['Pace', optLabel('pace', c.S.pace)],
      ['Ending', optLabel('ending', c.S.ending)],
      ['Effects', nfx ? nfx + ' on' : 'None']
    ];
  }

  function setStepState(r, state) {
    if (r.state === state) return;
    r.state = state;
    r.el.setAttribute('data-state', state);
    r.mark.innerHTML = state === 'done' ? svgWrap(IC.check, 14) : state === 'active' ? '<span class="spinner"></span>' : '';
    r.barBox.hidden = state !== 'active';
    if (state !== 'active') r.meta.textContent = '';
  }
  function exEta(stage, p) {
    var now = performance.now();
    if (exSampleStage !== stage) { exSamples = []; exSampleStage = stage; }
    exSamples.push([now, p]);
    if (exSamples.length > 40) exSamples.shift();
    var a = exSamples[0], b = exSamples[exSamples.length - 1], dt = (b[0] - a[0]) / 1000, dp = b[1] - a[1];
    if (dt < 4 || dp <= 0.004) return '';
    var left = (1 - p) * dt / dp;
    return left < 50 ? 'less than a minute left' : 'about ' + Math.ceil(left / 60) + ' min left';
  }

  /* the four faces of the modal: idle, running, done, error */
  function viewIdle() {
    var grid = h('dl', { class: 'sum-grid' }, summaryCells().map(function (c) {
      return h('div', { class: 'sum-cell' }, h('dt', { text: c[0] }), h('dd', { text: c[1] }));
    }));
    var extra = [c.S.text.hero ? 'Big word: ' + c.S.text.hero : '', c.S.text.small ? 'Small line: ' + c.S.text.small : ''].filter(Boolean).join(' · ');
    var words = h('div', { class: 'sum-words' },
      h('span', { class: 'sum-label', text: 'Words' }),
      h('p', { class: 'sum-quote', text: '“' + c.S.text.phrase + '”' }),
      extra ? h('p', { class: 'sum-small', text: extra }) : null);
    var fmt = h('div', { class: 'format-line' }, ico('video', null, 16), h('span', { text: outputLine(c.take) }));
    var est = h('p', { class: 'format-estimate' });
    exBind.push(function () { est.textContent = exportEstimateText(c.take.frames, secPerFrame[is4K() ? '2' : '1'], is4K()); });
    askInfo();
    var sound = h('div', { class: 'switch-list' },
      exSwitchRow('Your voice', 'The sound from your take.', function () { return !!c.S.sound.voice && !!c.take.hasAudio; },
        function (v) { c.update(function (s) { s.sound.voice = v; }, 'live'); }, c.take.hasAudio ? '' : 'This take has no sound.'),
      exSwitchRow('Sound effects', 'Whooshes and landings for the words.', function () { return !!c.S.sound.sfx; },
        function (v) { c.update(function (s) { s.sound.sfx = v; }, 'live'); }));
    fill(exRefs.body, words, grid, fmt, est, sound);
    fill(exRefs.foot, btn('Not now', { kind: 'ghost', onclick: requestClose }), btn('Render', { kind: 'primary', onclick: startExport }));
  }
  function viewRunning() {
    var rows = EXPORT_STEPS.map(function (s) {
      var r = { id: s.id, title: s.title, mark: h('span', { class: 'step-mark' }), meta: h('span', { class: 'step-meta' }), bar: h('i'), state: '' };
      r.barBox = h('div', { class: 'bar', hidden: true }, r.bar);
      r.el = h('li', { class: 'step', 'data-state': 'pending' }, r.mark,
        h('div', { class: 'step-main' }, h('div', { class: 'step-line' }, h('span', { class: 'step-title', text: s.title }), r.meta), r.barBox));
      return r;
    });
    exRefs.rows = rows;
    var runLede = h('p', { class: 'lede small' });
    exBind.push(function () { runLede.textContent = exportRunningText(c.take.frames, secPerFrame[is4K() ? '2' : '1'], is4K()); });
    fill(exRefs.body,
      runLede,
      h('ol', { class: 'steps compact' }, rows.map(function (r) { return r.el; })),
      h('p', { class: 'muted note', text: 'You can close this window. We will tell you when it is done.' }));
    fill(exRefs.foot, btn('Keep editing', { kind: 'ghost', onclick: requestClose }));
    updateRunning();
  }
  function updateRunning() {
    var rows = exRefs && exRefs.rows;
    if (!rows) return;
    var stage = ex.phase === 'starting' ? 'writing' : ex.stage, idx = EX_STEP_IDX[stage], i, p = clamp(ex.progress || 0, 0, 1);
    if (idx == null) idx = 0;
    for (i = 0; i < rows.length; i++) setStepState(rows[i], i < idx ? 'done' : i === idx ? 'active' : 'pending');
    var r = rows[idx];
    if (stage === 'rendering' && p > 0) {
      r.barBox.classList.remove('indeterminate');
      r.bar.style.width = Math.round(p * 100) + '%';
      var e = exEta(stage, p);
      r.meta.textContent = Math.round(p * 100) + '%' + (e ? ' · ' + e : '');
    } else {
      r.barBox.classList.add('indeterminate');
      r.bar.style.width = '0%';
      r.meta.textContent = EX_STEP_NOTE[stage] || '';
    }
  }
  /* a file path that wraps at its folder separators, and still copies as one clean string */
  function pathEl(p) {
    var code = h('code', { class: 'path', title: p });
    (String(p).match(/[^\\/]+[\\/]?|[\\/]/g) || [String(p)]).forEach(function (seg) {
      code.appendChild(document.createTextNode(seg));
      code.appendChild(document.createElement('wbr'));
    });
    return code;
  }
  /* what the app wants the creator to know about the finished file: details.notes, plain sentences (often none) */
  function exportNotes(r) {
    var notes = r && r.details && r.details.notes;
    return Array.isArray(notes) ? notes.filter(function (n) { return typeof n === 'string' && n; }) : [];
  }
  function viewDone() {
    var name = baseName(ex.path || ex.file);
    var video = h('video', { class: 'result-video', controls: true, playsinline: true, preload: 'metadata', src: ex.file ? ex.file + '#t=0.05' : null });
    var dl = h('a', { class: 'btn primary', href: ex.file || '#', download: name }, ico('download'), h('span', { class: 'btn-label', text: 'Download' }));
    var show = btn('Show in folder', { icon: 'folder', onclick: function () {
      if (!ex.path) return;
      postJSON('/api/reveal', { path: ex.path }).then(function () { toast('Opened the folder.'); }, function (err) { toast(err.message, 'error'); });
    } });
    var again = h('button', { type: 'button', class: 'link-btn', onclick: function () { ex = { phase: 'idle' }; renderExport(); } }, ico('reset', null, 14), 'Render again');
    fill(exRefs.body, h('div', { class: 'result' },
      h('div', { class: 'result-media' }, video),
      h('div', { class: 'result-info' },
        h('h3', { class: 'result-title', text: 'Your intro is ready' }),
        h('p', { class: 'muted', text: resultLine(c.take) }),
        (ex.notes || []).map(function (note) { return h('p', { class: 'muted note result-note', text: note }); }),
        ex.path ? pathEl(ex.path) : null,
        h('div', { class: 'result-actions' }, dl, show),
        again)));
    fill(exRefs.foot, btn('Back to editing', { kind: 'ghost', onclick: requestClose }));
  }
  function viewError() {
    fill(exRefs.body, callout('error', 'The render did not finish', ex.error || 'Something went wrong.'),
      h('p', { class: 'muted note', text: 'Your settings are safe. You can try again.' }));
    fill(exRefs.foot, btn('Close', { kind: 'ghost', onclick: requestClose }), btn('Try again', { kind: 'primary', onclick: startExport }));
  }
  function renderExport() {
    if (!exportEl || !exRefs) return;
    var view = ex.phase === 'starting' ? 'running' : ex.phase;
    if (view !== exView) {
      exView = view; exBind = [];
      exRefs.dialog.setAttribute('data-view', view);
      if (view === 'idle') viewIdle(); else if (view === 'running') viewRunning(); else if (view === 'done') viewDone(); else viewError();
      exSyncAll();
      if (!exportEl.contains(document.activeElement)) {
        var first = exRefs.foot.querySelector('.btn.primary') || exRefs.dialog;
        try { first.focus({ preventScroll: true }); } catch (e) { /* ignore */ }
      }
    } else if (view === 'running') updateRunning();
  }

  function requestClose() {
    if (/^#\/export\//.test(location.hash)) location.hash = '#/studio/' + encodeURIComponent(c.id);
    else closeExport();
  }
  function exKey(e) {
    if (!exportEl) return;
    if (e.key === 'Escape') { e.preventDefault(); requestClose(); return; }
    if (e.key !== 'Tab') return;
    var f = exportEl.querySelectorAll('button:not([disabled]), a[href], video[controls], input:not([disabled]), [tabindex]:not([tabindex="-1"])');
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1], act = document.activeElement;
    if (e.shiftKey && (act === first || act === exRefs.dialog)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && act === last) { e.preventDefault(); first.focus(); }
  }
  function openExport() {
    if (!c.take || exportEl || c.disposed) return;
    lastFocus = document.activeElement;
    exPrevPlaying = !!(c.preview && c.preview.isPlaying());
    if (c.preview && exPrevPlaying) c.preview.pause();
    exView = ''; exBind = []; exRefs = {};
    var body = h('div', { class: 'modal-body' }), foot = h('div', { class: 'modal-foot' });
    var closeBtn = h('button', { type: 'button', class: 'icon-btn', 'aria-label': 'Close', onclick: requestClose }, ico('x'));
    var dialog = h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'export-h', tabindex: '-1' },
      h('div', { class: 'modal-head' }, h('h2', { id: 'export-h', text: 'Export your intro' }), closeBtn), body, foot);
    var backdrop = h('div', { class: 'modal-backdrop' }, dialog);
    backdrop.addEventListener('pointerdown', function (e) { if (e.target === backdrop) requestClose(); });
    exRefs.body = body; exRefs.foot = foot; exRefs.dialog = dialog;
    exportEl = backdrop;
    c.el.appendChild(backdrop);
    document.addEventListener('keydown', exKey);
    c.bind(exSyncAll);
    renderExport();
  }
  function closeExport() {
    if (!exportEl) return;
    c.unbind(exSyncAll);
    document.removeEventListener('keydown', exKey);
    var v = exportEl.querySelector('video');
    if (v) { try { v.pause(); } catch (e) { /* ignore */ } }
    if (exportEl.parentNode) exportEl.parentNode.removeChild(exportEl);
    exportEl = null; exRefs = null; exView = '';
    var back = lastFocus && document.contains(lastFocus) ? lastFocus : c.ui.exportBtn;
    if (back && back.focus) { try { back.focus({ preventScroll: true }); } catch (e) { /* ignore */ } }
    lastFocus = null;
    if (c.preview && exPrevPlaying) c.preview.play();
    exPrevPlaying = false;
  }
  function setExport(on) {
    wantExport = !!on;
    if (!c.take) return;
    if (on) openExport(); else closeExport();
  }

  /* render: start, then poll the server once a second */
  function startExport() {
    if (!c.take || ex.phase === 'starting' || ex.phase === 'running') return;
    clearTimeout(exTimer);
    ex = { phase: 'starting', stage: 'writing', progress: 0, fail: 0 };
    exSamples = []; exSampleStage = '';
    if (c.ui.exportBtn) c.ui.exportBtn.classList.remove('has-result');
    setExportBusy(true);
    renderExport();
    var events = c.preview ? c.preview.events() : [];
    postJSON('/api/export', { takeId: c.take.id, settings: clone(c.S), events: events }).then(function (res) {
      if (c.disposed) return;
      if (!res || !res.id) throw new Error('The server did not start the render.');
      ex.id = res.id; ex.phase = 'running';
      exTimer = setTimeout(pollExport, 400);
      renderExport();
    }).catch(function (err) { if (!c.disposed) failExport(err && err.message); });
  }
  function pollExport() {
    clearTimeout(exTimer);
    if (c.disposed || ex.phase !== 'running') return;
    api('/api/exports/' + encodeURIComponent(ex.id)).then(function (r) {
      if (c.disposed || ex.phase !== 'running') return;
      ex.fail = 0;
      ex.stage = r.stage; ex.progress = +r.progress || 0; ex.message = r.message || '';
      if (r.stage === 'done') {
        ex.phase = 'done'; ex.file = r.file || ''; ex.path = r.path || ''; ex.notes = exportNotes(r);
        setExportBusy(false);
        if (c.ui.exportBtn) c.ui.exportBtn.classList.add('has-result');
        if (!exportEl) toast('Your intro is ready. Open Export to see it.');
      } else if (r.stage === 'error') {
        failExport(r.message || 'The render did not finish.');
        return;
      } else {
        exTimer = setTimeout(pollExport, 1000);
      }
      renderExport();
    }, function (err) {
      if (c.disposed || ex.phase !== 'running') return;
      ex.fail = (ex.fail || 0) + 1;
      if (err.status === 404 || ex.fail >= 6) failExport(err.message);
      else exTimer = setTimeout(pollExport, 1000);
    });
  }
  function failExport(msg) {
    clearTimeout(exTimer);
    ex.phase = 'error'; ex.error = msg || 'Something went wrong.';
    setExportBusy(false);
    if (!exportEl) toast('The render did not finish.', 'error');
    renderExport();
  }

  return {
    setExport: setExport,
    isOpen: function () { return !!exportEl; },
    openIfWanted: function () { if (wantExport) openExport(); },
    dispose: function () { clearTimeout(exTimer); document.removeEventListener('keydown', exKey); }
  };
}
