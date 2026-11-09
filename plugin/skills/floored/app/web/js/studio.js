import { browserNotice, btn, callout, clamp, f1, f2, fill, h, ico, noop, setAccent, setPressed, toast, topbar } from './util.js';
import { api, posterImg } from './api.js';
import { DEBUG, autoHero, flush, loadSettings, rememberSmall, saveSettings } from './store.js';
import { createPreview } from './preview.js';
import { SECTION_IDS, createPanel } from './panel.js';
import { createExport } from './export.js';

export function studioScreen(id, query) {
  var take = null, status = null, S = null, preview = null;
  var disposed = false, binders = [];
  var ro = null, cleanups = [];
  var el = h('div', { class: 'screen studio' });
  var notice = browserNotice();      // null in Chrome, Edge and the other Chromium browsers
  var resolveReady = noop;
  var ready = new Promise(function (r) { resolveReady = r; });
  var ui = {};   /* element handles filled in by build() */
  /* what panel.js and export.js see of this screen */
  var c = {
    id: id,
    el: el,
    ui: ui,
    get S() { return S; }, set S(v) { S = v; },
    get take() { return take; },
    get preview() { return preview; },
    get disposed() { return disposed; },
    on: on, bind: bind, unbind: unbind, syncAll: syncAll, update: update, commit: commit
  };
  var panelUI = createPanel(c);
  var exportUI = createExport(c);

  function bind(fn) { binders.push(fn); try { fn(); } catch (e) { DEBUG.log.push('bind: ' + e.message); } }
  function syncAll() { for (var i = 0; i < binders.length; i++) { try { binders[i](); } catch (e) { DEBUG.log.push('sync: ' + e.message); } } }
  function on(target, type, fn, opts) { target.addEventListener(type, fn, opts); cleanups.push(function () { target.removeEventListener(type, fn, opts); }); }

  /* a change of settings: save, repaint the panel, tell the engine ('restart' = play again from 0) */
  function commit(kind) {
    if (disposed) return;       // leftover debounces and late callbacks do nothing once the studio is left
    saveSettings(take, S);
    rememberSmall(S);
    setAccent(S.palette);
    if (ui.stage) ui.stage.style.background = S.palette.floor;
    syncAll();
    if (preview) preview.apply(S, kind === 'restart');
  }
  function update(mutator, kind) { mutator(S); commit(kind); }

  function unbind(fn) { var i = binders.indexOf(fn); if (i >= 0) binders.splice(i, 1); }


  /* ---------------------------------------------------------------- loading */
  if (notice) el.appendChild(notice);
  el.appendChild(topbar());
  var loadingBox = h('main', { class: 'studio-loading' }, h('span', { class: 'spinner' }), h('span', { text: 'Loading your take…' }));
  el.appendChild(loadingBox);

  api('/api/takes/' + encodeURIComponent(id)).then(function (res) {
    if (disposed) return;
    take = res.take; status = res.status;
    if (!status || status.stage !== 'ready') { location.replace('#/processing/' + encodeURIComponent(id)); return; }
    return loadSettings(take).then(function (s) {
      if (disposed) return;
      S = s;
      build();
    });
  }, function (err) {
    if (disposed) return;
    loadingBox.classList.add('is-error');
    fill(loadingBox, ico('alert', 'warn-ico', 24),
      h('div', { class: 'load-error' },
        h('strong', { text: err.status === 404 ? 'We can’t find this take.' : 'We couldn’t open this take.' }),
        h('p', { class: 'muted', text: err.message }),
        h('a', { class: 'btn', href: '#/' }, 'Back to start')));
    resolveReady();
  });

  /* ---------------------------------------------------------------- build */
  function build() {
    setAccent(S.palette);
    document.title = (take.name || 'Studio') + ' · floored';

    /* top bar */
    var warns = take.warnings || [];
    var chipBtn = h('button', { type: 'button', class: 'take-chip', 'aria-haspopup': 'true', 'aria-expanded': 'false', 'aria-label': 'About this take' },
      h('span', { class: 'chip-thumb' }, posterImg(take.id)),
      h('span', { class: 'chip-text' }, h('strong', { text: take.name || take.id }),
        h('span', { class: 'chip-meta num', text: f1(take.dur) + ' s · ' + (take.fps || 24) + ' fps' })),
      warns.length ? h('span', { class: 'warn-dot', title: warns.length + (warns.length === 1 ? ' note' : ' notes') }) : null);
    var pop = h('div', { class: 'popover', role: 'dialog', 'aria-label': 'Notes about this take', hidden: true },
      warns.length
        ? [h('p', { class: 'pop-title', text: warns.length === 1 ? 'One thing to know' : 'A few things to know' }),
           warns.map(function (w) { return callout('warn', null, w.message); })]
        : h('p', { class: 'pop-ok' }, ico('check', 'ok-ico'), 'No problems found. Nice take.'));
    var chipWrap = h('div', { class: 'chip-wrap' }, chipBtn, pop);
    function setPop(open) { pop.hidden = !open; chipBtn.setAttribute('aria-expanded', open ? 'true' : 'false'); }
    chipBtn.addEventListener('click', function (e) { e.stopPropagation(); setPop(pop.hidden); });
    on(document, 'pointerdown', function (e) { if (!pop.hidden && !chipWrap.contains(e.target)) setPop(false); });
    on(document, 'keydown', function (e) { if (e.key === 'Escape' && !pop.hidden) { setPop(false); chipBtn.focus(); } });

    var exportBtn = btn('Export', { kind: 'primary', onclick: function () { location.hash = '#/export/' + encodeURIComponent(id); } });
    ui.exportBtn = exportBtn;
    var bar = topbar({
      chip: chipWrap,
      actions: [btn('New take', { kind: 'ghost', icon: 'plus', aria: 'New take', onclick: function () { location.hash = '#/'; } }), exportBtn]
    });

    /* stage */
    var host = h('div', { class: 'stage-clip' });
    var overlay = h('div', { class: 'stage-status' }, h('span', { class: 'spinner' }), h('span', { class: 'stage-status-text', text: 'Loading your take…' }));
    var engineChip = h('div', { class: 'stage-chip', hidden: true, text: 'Engine loading…' });
    var stage = h('div', { class: 'stage', style: { background: S.palette.floor } }, host, overlay, engineChip);
    ui.stage = stage;

    /* transport */
    var playBtn = h('button', { type: 'button', class: 'play-btn', 'aria-label': 'Play', onclick: function () { if (preview) preview.toggle(); } }, ico('play'));
    var curEl = h('span', { class: 't-cur', text: '0.00' });
    var timeEl = h('span', { class: 'time num' }, curEl, h('span', { class: 't-sep', text: ' / ' }), h('span', { class: 't-dur', text: f2(take.dur) }));
    var fillEl = h('i', { class: 'scrub-fill' }), thumbEl = h('i', { class: 'scrub-thumb' });
    var scrub = h('div', { class: 'scrub', role: 'slider', tabindex: '0', 'aria-label': 'Position in the clip', 'aria-valuemin': '0', 'aria-valuemax': f2(take.dur), 'aria-valuenow': '0' },
      h('div', { class: 'scrub-track' }, fillEl, thumbEl));
    var dragging = false;
    function tFromEvent(e) { var r = scrub.getBoundingClientRect(); return clamp((e.clientX - r.left) / Math.max(1, r.width), 0, 1) * take.dur; }
    scrub.addEventListener('pointerdown', function (e) {
      if (!preview) return;
      dragging = true; scrub.setPointerCapture(e.pointerId); scrub.classList.add('is-drag');
      preview.scrubStart(); preview.scrubTo(tFromEvent(e));
    });
    scrub.addEventListener('pointermove', function (e) { if (dragging && preview) preview.scrubTo(tFromEvent(e)); });
    function endDrag() { if (!dragging) return; dragging = false; scrub.classList.remove('is-drag'); if (preview) preview.scrubEnd(); }
    scrub.addEventListener('pointerup', endDrag);
    scrub.addEventListener('pointercancel', endDrag);
    var loopBtn = h('button', { type: 'button', class: 'icon-btn', 'aria-pressed': 'true', 'aria-label': 'Loop', title: 'Loop', onclick: function () {
      var on_ = loopBtn.getAttribute('aria-pressed') !== 'true'; setPressed(loopBtn, on_); if (preview) preview.setLoop(on_);
    } }, ico('repeat'));
    var soundBtn = h('button', { type: 'button', class: 'icon-btn', 'aria-pressed': 'false', 'aria-label': 'Sound', title: 'Sound (off until you turn it on)', onclick: function () {
      var on_ = soundBtn.getAttribute('aria-pressed') !== 'true';
      setPressed(soundBtn, on_);
      fill(soundBtn, ico(on_ ? 'volume' : 'mute'));
      if (preview) preview.setSound(on_);
    } }, ico('mute'));
    var transport = h('div', { class: 'transport' }, playBtn, timeEl, scrub, loopBtn, soundBtn);
    var lastShown = '';
    function showTime(t) {
      var s = f2(t);
      if (s === lastShown) return;
      lastShown = s;
      curEl.textContent = s;
      var p = clamp(t / take.dur, 0, 1) * 100;
      fillEl.style.width = p + '%'; thumbEl.style.left = p + '%';
      scrub.setAttribute('aria-valuenow', s);
    }
    function showPlay(playing) {
      fill(playBtn, ico(playing ? 'pause' : 'play'));
      playBtn.setAttribute('aria-label', playing ? 'Pause' : 'Play');
    }

    var stageCol = h('div', { class: 'stage-col' }, stage, transport);
    var stageArea = h('section', { class: 'stage-area' }, stageCol);
    ui.stageCol = stageCol; ui.stageArea = stageArea;

    /* panel */
    var panel = h('aside', { class: 'panel', 'aria-label': 'Looks and settings' });
    ui.panel = panel;
    panelUI.build(panel);

    fill(el, notice, bar, h('main', { class: 'studio-body' }, stageArea, panel));
    layoutStage();
    ro = new ResizeObserver(layoutStage);
    ro.observe(stageArea);
    on(window, 'resize', layoutStage);
    on(document, 'keydown', onKey);
    syncAll();
    exportUI.openIfWanted();
    pollSoon();

    /* open the section named in the URL */
    var want = query && query.get && query.get('panel');
    if (want && SECTION_IDS.indexOf(want) >= 0) panelUI.openSection(want, true);

    /* the preview */
    preview = createPreview(host, take, S, {
      onTime: showTime,
      onPlayState: showPlay,
      onError: function (e) { toast('The preview hit a snag: ' + ((e && e.message) || e), 'error'); }
    });
    engineChip.hidden = preview.kind === 'engine';
    layoutStage();
    DEBUG.studio = { get S() { return S; }, get preview() { return preview; }, get take() { return take; }, update: update, poll: poll };
    var freeze = query && query.get && query.get('t');
    preview.load().then(function () {
      if (disposed) return;
      overlay.hidden = true;
      if (freeze != null && freeze !== '' && !isNaN(parseFloat(freeze))) { preview.seek(parseFloat(freeze)); showPlay(false); }
      else if (!exportUI.isOpen()) preview.play();
      setTimeout(resolveReady, 350);
    }, function (err) {
      if (disposed) return;
      fill(overlay, ico('alert', 'warn-ico', 24), h('span', { class: 'stage-status-text', text: 'The video did not load. ' + (err && err.message ? err.message : '') }));
      overlay.classList.add('is-error');
      resolveReady();
    });
  }

  /* ---------------------------------------------------------------- live suggestions
     Claude writes hook suggestions into the take (`ft suggest`) while the studio is open. The take is asked for again every 3 s,
     only while the page is visible and one request at a time; when suggestionsRev has grown the Suggestions tab is refreshed,
     and a take without speech whose words the creator has not touched starts from the first idea. */
  var POLL_MS = 3000, POLL_TIMEOUT_MS = 10000, pollTimer = 0, pollBusy = false, adoptPending = false;
  function pollSoon() { clearTimeout(pollTimer); pollTimer = 0; if (!disposed) pollTimer = setTimeout(poll, POLL_MS); }
  /* one request at a time; a request that hangs is given up after 10 s, and the next tick asks again. Resolves when it is over. */
  function poll() {
    pollTimer = 0;
    if (disposed) return Promise.resolve();
    if (document.hidden || pollBusy) { pollSoon(); return Promise.resolve(); }
    pollBusy = true;
    var ctl = typeof AbortController === 'function' ? new AbortController() : null;
    var guard = setTimeout(function () { if (ctl) ctl.abort(); }, POLL_TIMEOUT_MS);
    function done() { clearTimeout(guard); pollBusy = false; pollSoon(); }
    return api('/api/takes/' + encodeURIComponent(id), ctl ? { signal: ctl.signal } : undefined).then(function (res) {
      if (disposed || !res || !res.take) return;
      try { gotTake(res.take); tryAdopt(); } catch (e) { DEBUG.log.push('poll: ' + e.message); }
    }).then(done, done);
  }
  function gotTake(t) {
    var rev = t.suggestionsRev || 0;
    if (!take || rev <= (take.suggestionsRev || 0)) return;
    take.suggestionsRev = rev;
    take.suggestions = Array.isArray(t.suggestions) ? t.suggestions : [];
    take.smallSuggestions = Array.isArray(t.smallSuggestions) ? t.smallSuggestions : [];
    adoptPending = !(take.words && take.words.length) && take.suggestions.length > 0;
    syncAll();                                  // the Suggestions list and the small-line field show the new ideas at once
    toast('New ideas from Claude');
  }
  /* Claude's first idea becomes the phrase of a take with no speech whose words the creator has not touched. It waits (and is
     tried again on the next tick) while the creator is typing, and while the export dialog is open: restarting the floor under
     either would be rude. Typing or picking words cancels it. */
  function tryAdopt() {
    if (!adoptPending || disposed || !S) return;
    var first = take.suggestions && take.suggestions[0];
    if (!first || (take.words && take.words.length) || (S.text && S.text.edited)) { adoptPending = false; return; }
    if (exportUI.isOpen() || panelUI.typing()) return;
    adoptPending = false;
    if (first === S.text.phrase) return;
    update(function (s) { s.text.phrase = first; s.text.source = 'suggested'; s.text.hero = autoHero(first); }, 'restart');
  }

  /* ---------------------------------------------------------------- stage sizing */
  function layoutStage() {
    if (!ui.stageArea || disposed) return;
    var mobile = window.matchMedia('(max-width: 600px)').matches, H, W;
    if (mobile) {
      H = Math.min(window.innerHeight * 0.4, 380);
    } else {
      var r = ui.stageArea.getBoundingClientRect();
      H = Math.min(r.height - 112, (r.width - 64) * 16 / 9);
    }
    H = Math.floor(Math.max(200, H));
    W = Math.round(H * 9 / 16);
    ui.stageCol.style.setProperty('--stage-w', W + 'px');
    ui.stageCol.style.setProperty('--stage-h', H + 'px');
    el.style.setProperty('--sticky-h', (56 + H + 72) + 'px');
    if (preview) preview.fit(W, H);
  }

  /* ---------------------------------------------------------------- keyboard */
  function onKey(e) {
    if (exportUI.isOpen() || e.metaKey || e.ctrlKey || e.altKey) return;
    var t = e.target, tag = t && t.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || (t && t.isContentEditable)) return;
    var keyboardFocus = false;
    try { keyboardFocus = !!(t && t.matches && t.matches(':focus-visible') && t !== document.body); } catch (x) { keyboardFocus = false; }
    if (!preview) return;
    if (e.key === ' ' || e.code === 'Space') {
      if (keyboardFocus && t.closest && t.closest('button, [role="switch"], a, summary')) return;   /* let Space press the focused control */
      e.preventDefault(); preview.toggle();
    } else if (e.key === 'ArrowLeft') { e.preventDefault(); preview.step(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); preview.step(1); }
    else if (e.key === 'Home') { e.preventDefault(); preview.restart(); }
  }

  /* ---------------------------------------------------------------- leaving */
  on(document, 'visibilitychange', function () {
    if (document.hidden && preview && preview.isPlaying()) preview.pause();
    if (!document.hidden && S && !pollBusy) { clearTimeout(pollTimer); poll(); }      // back on the page: look for new ideas at once
  });
  function dispose() {
    panelUI.flushPending();      // typing still waiting on its 400 ms is applied and saved first, then the studio goes quiet
    disposed = true;
    clearTimeout(pollTimer); pollTimer = 0;
    flush();
    exportUI.dispose();
    for (var i = 0; i < cleanups.length; i++) { try { cleanups[i](); } catch (e) { /* ignore */ } }
    cleanups = [];
    if (ro) { try { ro.disconnect(); } catch (e) { /* ignore */ } }
    if (preview) { try { preview.dispose(); } catch (e2) { /* ignore */ } preview = null; }
    if (DEBUG.studio) delete DEBUG.studio;
  }

  function setExport(on) { exportUI.setExport(on); if (!on) tryAdopt(); }       // the dialog is closed: an idea that waited may go in now
  return { el: el, ready: ready, dispose: dispose, setExport: setExport };
}
