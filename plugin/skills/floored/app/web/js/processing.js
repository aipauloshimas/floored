import { IC, browserNotice, byId, callout, clamp, empty, fill, h, ico, setAccent, svgWrap, topbar } from './util.js';
import { api, posterFor } from './api.js';
import { LOOKS, PALETTES, cachedPrefs, putPrefs, ssGet } from './store.js';
import { lookTile } from './panel.js';
import { etaText } from './copy.js';

var STEPS = [
  { id: 'checking',  title: 'Checking your take' },
  { id: 'cutting',   title: 'Cutting you out' },
  { id: 'measuring', title: 'Measuring where you stand' },
  { id: 'shadow',    title: 'Adding your shadow' },
  { id: 'words',     title: 'Reading your words' },
  { id: 'ready',     title: 'Ready' }
];
function stepIndex(stage) { for (var i = 0; i < STEPS.length; i++) if (STEPS[i].id === stage) return i; return -1; }

export function processingScreen(id) {
  var dead = false, timer = 0, take = null, status = null, lastIdx = -1, shownWarn = -1, posterOk = true, posterTries = 0;
  // the look chosen last is where this take starts (the studio reads it from the saved prefs). Painting it here never writes:
  // only a click on a tile does, so a saved "my look" stays the last look until the creator picks another one.
  var lastLook = cachedPrefs().lastLook;
  var mine = (lastLook && lastLook.indexOf('my:') === 0) ? (cachedPrefs().looks || []).filter(function (l) { return 'my:' + l.id === lastLook; })[0] : null;

  var posterEl = h('img', { class: 'proc-poster', alt: '', src: posterFor(id) });
  posterEl.addEventListener('error', function () { posterOk = false; posterEl.style.visibility = 'hidden'; });
  posterEl.addEventListener('load', function () { posterOk = true; posterEl.style.visibility = 'visible'; });
  var frame = h('div', { class: 'proc-frame', 'aria-hidden': 'true' }, h('span', { class: 'proc-fallback' }, ico('phone', null, 28)), posterEl, h('span', { class: 'shimmer' }));

  var title = h('h1', { class: 'display md', text: 'Getting your take ready' });
  var lede = h('p', { class: 'lede', text: 'This takes a few minutes. Pick a look while you wait, it will be waiting for you.' });
  var rows = STEPS.map(function (s) {
    var mark = h('span', { class: 'step-mark' });
    var meta = h('span', { class: 'step-meta' });
    var bar = h('i');
    return {
      id: s.id, mark: mark, meta: meta, bar: bar,
      el: h('li', { class: 'step', 'data-state': 'pending' }, mark,
        h('div', { class: 'step-main' }, h('div', { class: 'step-line' }, h('span', { class: 'step-title', text: s.title }), meta),
          h('div', { class: 'bar', hidden: true }, bar)))
    };
  });
  var warnBox = h('div', { class: 'proc-notes' });
  var errBox = h('div', { class: 'proc-notes' });
  var netNote = h('p', { class: 'muted net-note', hidden: true, text: 'Lost the connection for a moment, trying again…' });

  function setState(r, state) {
    r.el.setAttribute('data-state', state);
    r.mark.innerHTML = state === 'done' ? svgWrap(IC.check, 14) : state === 'error' ? svgWrap(IC.x, 14) : state === 'active' ? '<span class="spinner"></span>' : '';
    r.el.querySelector('.bar').hidden = state !== 'active';
    if (state !== 'active') r.meta.textContent = '';
  }
  function render() {
    var stage = status ? status.stage : 'queued', idx, i;
    if (stage === 'ready') idx = STEPS.length;
    else if (stage === 'error') idx = lastIdx >= 0 ? lastIdx : 0;
    else if (stage === 'queued') idx = 0;
    else { idx = stepIndex(stage); lastIdx = idx; }
    for (i = 0; i < rows.length; i++) {
      var state = i < idx ? 'done' : i === idx ? (stage === 'error' ? 'error' : 'active') : 'pending';
      setState(rows[i], state);
    }
    if (stage === 'ready') rows[rows.length - 1].meta.textContent = '';
    if (idx < rows.length && stage !== 'error') {
      var r = rows[idx], p = clamp(status && status.progress || 0, 0, 1);
      if (stage === 'queued') {
        r.meta.textContent = (status && status.message) || 'Waiting to start';
        r.bar.style.width = '0%';
        r.el.querySelector('.bar').classList.add('indeterminate');
      } else {
        r.el.querySelector('.bar').classList.remove('indeterminate');
        r.bar.style.width = Math.round(p * 100) + '%';
        var e = stage === 'cutting' && status ? etaText(status.eta, status.etaGuess) : '';   // the server measures it: only the cutout is slow enough to wait for
        r.meta.textContent = Math.round(p * 100) + '%' + (e ? ' · ' + e : '');
      }
    }
    var looksSec = el && el.querySelector('.proc-looks');
    if (looksSec) looksSec.hidden = stage === 'error';
    if (stage === 'error') {
      title.textContent = 'That didn’t work';
      lede.textContent = 'Nothing is lost. Try another clip, or film it again.';
      fill(errBox, callout('error', 'We couldn’t finish this take', (status && (status.error || status.message)) || 'Something went wrong.',
        h('a', { class: 'btn small', href: '#/' }, 'Try another clip')));
    } else {
      empty(errBox);
      title.textContent = stage === 'ready' ? 'Your take is ready' : 'Getting your take ready';
    }
    var ws = (take && take.warnings) || [];
    if (ws.length !== shownWarn) {
      shownWarn = ws.length;
      fill(warnBox, ws.map(function (w) { return callout('warn', null, w.message); }));
    }
    if (!posterOk && posterTries < 8 && !ssGet('ft:poster:' + id)) { posterTries++; posterEl.src = posterFor(id) + '?r=' + posterTries; }
  }

  /* look picker */
  var tiles = [];
  var lookGrid = h('div', { class: 'look-grid' }, LOOKS.map(function (l) {
    var t = lookTile(l, 'TEXT', function (look) { pick(look.id); });
    tiles.push(t);
    return t;
  }));
  var mineNote = h('p', { class: 'muted', hidden: true });
  /* paint: the accent colour and which tile is marked. Never writes prefs. */
  function paint(lookId) {
    var look = byId(LOOKS, lookId), pal = null;
    if (look) pal = byId(PALETTES, look.palette);
    else if (mine && mine.settings && mine.settings.palette && mine.settings.palette.floor && mine.settings.palette.ink) pal = mine.settings.palette;
    else pal = byId(PALETTES, byId(LOOKS, 'original').palette);
    setAccent(pal);
    mineNote.hidden = !!look || !mine;
    if (!look && mine) mineNote.textContent = 'Starting from your look “' + mine.name + '”. Pick one below to start from that instead.';
    tiles.forEach(function (t) { t.setSelected(!!look && t.getAttribute('data-look') === lookId); });
  }
  /* a click: the creator chose */
  function pick(lookId) {
    mine = null;
    putPrefs({ lastLook: lookId });
    paint(lookId);
  }
  paint(byId(LOOKS, lastLook) || mine ? lastLook : 'original');   // nothing saved yet: show Original, without writing it

  function go() { if (!dead) location.replace('#/studio/' + encodeURIComponent(id)); }
  function poll() {
    if (dead) return;
    api('/api/takes/' + encodeURIComponent(id)).then(function (res) {
      if (dead) return;
      netNote.hidden = true;
      take = res.take || take; status = res.status;
      render();
      if (status.stage === 'ready') { timer = setTimeout(go, 900); return; }
      if (status.stage === 'error') return;
      timer = setTimeout(poll, 1000);
    }, function (err) {
      if (dead) return;
      if (err.status === 404) {
        status = { stage: 'error', progress: 0, message: 'We can’t find this take. It may have been removed.' };
        render();
        return;
      }
      netNote.hidden = false;
      timer = setTimeout(poll, 2000);
    });
  }

  var el = h('div', { class: 'screen processing' },
    browserNotice(),
    topbar(),
    h('main', { class: 'proc-main' },
      h('div', { class: 'proc-grid' },
        frame,
        h('section', { class: 'proc-side' }, title, lede,
          h('ol', { class: 'steps', 'aria-label': 'Progress' }, rows.map(function (r) { return r.el; })),
          netNote, errBox, warnBox)),
      h('section', { class: 'proc-looks' },
        h('h2', { class: 'section-title', text: 'Pick a look while you wait' }),
        h('p', { class: 'muted', text: 'You can change everything later. This just sets where you start.' }),
        mineNote, lookGrid)));
  render();
  var first = new Promise(function (resolve) {
    api('/api/takes/' + encodeURIComponent(id)).then(function (res) {
      if (dead) return resolve();
      take = res.take || take; status = res.status; render();
      resolve();
      if (status.stage === 'ready') { timer = setTimeout(go, 900); return; }
      if (status.stage !== 'error') timer = setTimeout(poll, 1000);
    }, function (err) {
      resolve();
      if (dead) return;
      if (err.status === 404) { status = { stage: 'error', progress: 0, message: 'We can’t find this take. It may have been removed.' }; render(); return; }
      netNote.hidden = false; timer = setTimeout(poll, 2000);
    });
  });
  return {
    el: el,
    ready: first,
    dispose: function () { dead = true; clearTimeout(timer); }
  };
}
