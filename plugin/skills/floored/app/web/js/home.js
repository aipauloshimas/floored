import { browserNotice, byId, f1, fill, h, ico, noop, setAccent, topbar } from './util.js';
import { api, capturePoster, posterImg, uploadFile } from './api.js';
import { LOOKS, PALETTES, cachedPrefs, ssSet } from './store.js';
import { FILMING } from './copy.js';

export function homeScreen() {
  var disposed = false, busy = false;
  var input = h('input', { type: 'file', accept: 'video/mp4,video/quicktime,.mp4,.mov,.m4v', class: 'sr-only', tabindex: '-1', 'aria-hidden': 'true' });
  var zone = h('div', { class: 'dropzone' });
  var zoneNote = h('div', { class: 'dz-note', 'aria-live': 'polite' });

  function chooseBtn(label) {
    return h('button', { type: 'button', class: 'btn', onclick: function (e) { e.stopPropagation(); input.click(); } }, label);
  }
  function idleView() {
    zone.classList.remove('is-busy');
    fill(zone,
      h('div', { class: 'dz-icon' }, ico('upload', null, 24)),
      h('h2', { class: 'dz-title', text: 'Drop your take here' }),
      h('p', { class: 'dz-sub', text: 'MP4 or MOV · 3–8 seconds · filmed from above' }),
      chooseBtn('Choose a file'));
  }
  function busyView(name, p) {
    zone.classList.add('is-busy');
    var bar = h('i', { style: { width: Math.round(p * 100) + '%' } });
    fill(zone,
      h('div', { class: 'dz-icon' }, h('span', { class: 'spinner' })),
      h('h2', { class: 'dz-title', text: 'Uploading…' }),
      h('p', { class: 'dz-sub', text: name }),
      h('div', { class: 'bar wide', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(Math.round(p * 100)) }, bar));
    return bar;
  }
  function errorView(msg) {
    zone.classList.remove('is-busy');
    fill(zone,
      h('div', { class: 'dz-icon warn' }, ico('alert', null, 24)),
      h('h2', { class: 'dz-title', text: 'That didn’t work' }),
      h('p', { class: 'dz-sub error-text', text: msg }),
      chooseBtn('Try another file'));
  }

  function handleFile(file) {
    if (!file || busy) return;
    if (!(/\.(mp4|mov|m4v)$/i.test(file.name) || /^video\//.test(file.type))) {
      errorView('That doesn’t look like a video. Use an MP4 or MOV file.');
      return;
    }
    busy = true;
    var bar = busyView(file.name, 0);
    var posterJob = capturePoster(file);
    uploadFile(file, function (p) { if (!disposed) { bar.style.width = Math.round(p * 100) + '%'; } }).then(function (res) {
      return posterJob.then(function (data) {
        if (data) ssSet('ft:poster:' + res.id, data);
        if (!disposed) location.hash = '#/processing/' + encodeURIComponent(res.id);
      });
    }).catch(function (err) {
      busy = false;
      if (!disposed) errorView(err.message);
    });
  }

  input.addEventListener('change', function () { var f = input.files && input.files[0]; input.value = ''; handleFile(f); });
  var depth = 0;
  zone.addEventListener('dragenter', function (e) { e.preventDefault(); depth++; zone.classList.add('is-over'); });
  zone.addEventListener('dragover', function (e) { e.preventDefault(); if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'; zone.classList.add('is-over'); });
  zone.addEventListener('dragleave', function () { depth = Math.max(0, depth - 1); if (!depth) zone.classList.remove('is-over'); });
  zone.addEventListener('drop', function (e) {
    e.preventDefault(); depth = 0; zone.classList.remove('is-over');
    var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    handleFile(f);
  });
  zone.addEventListener('click', function (e) { if (!busy && e.target === zone) input.click(); });
  function stopStray(e) { e.preventDefault(); }   /* a file dropped beside the zone must not open in the tab */
  window.addEventListener('dragover', stopStray);
  window.addEventListener('drop', stopStray);
  idleView();

  var takesBox = h('section', { class: 'home-takes', hidden: true });
  var el = h('div', { class: 'screen home' },
    browserNotice(),
    topbar(),
    h('main', { class: 'home-main' },
      h('div', { class: 'home-grid' },
        h('section', { class: 'home-left' },
          h('h1', { class: 'display', text: 'Stand on your own words.' }),
          h('p', { class: 'lede', text: 'Drop a clip filmed from above. Pick a look. Export a 3D text intro in minutes.' }),
          zone, zoneNote, input,
          h('p', { class: 'sample-line muted', text: 'No clip yet?' }),
          h('a', { class: 'sample-tile', href: '#/studio/sample' },
            h('span', { class: 'take-thumb' }, posterImg('sample')),
            h('span', { class: 'take-info' }, h('strong', { text: 'AI-generated sample' }),
              h('span', { class: 'link-text' }, 'Try the sample take', ico('arrow', 'inline', 16))))),
        h('aside', { class: 'how-card', 'aria-labelledby': 'how-title' },
          h('h2', { id: 'how-title', class: 'card-title', text: FILMING.heading }),
          h('ul', { class: 'how-list' }, FILMING.rules.map(function (r) {
            return h('li', null, h('span', { class: 'how-ico' }, ico(r.icon)), h('div', null, h('strong', { text: r.title }), h('p', { text: r.text })));
          })))),
      takesBox));

  api('/api/takes').then(function (list) {
    if (disposed || !Array.isArray(list)) return;
    var mine = list.filter(function (it) { return it && it.take && it.take.id !== 'sample'; });
    if (!mine.length) return;
    takesBox.hidden = false;
    fill(takesBox, h('h2', { class: 'section-title', text: 'Your takes' }),
      h('div', { class: 'take-grid' }, mine.map(function (it) {
        var t = it.take, s = it.status || {}, ready = s.stage === 'ready', failed = s.stage === 'error';
        var meta = ready ? (f1(t.dur || 0) + ' s · ' + (t.fps || 24) + ' fps') : failed ? 'Needs attention' : (s.message || 'Working on it');
        return h('a', { class: 'take-card', href: ready ? '#/studio/' + encodeURIComponent(t.id) : '#/processing/' + encodeURIComponent(t.id) },
          h('span', { class: 'take-thumb' }, posterImg(t.id)),
          h('span', { class: 'take-info' }, h('strong', { text: t.name || t.id }), h('span', { class: 'muted', text: meta })),
          h('span', { class: 'status-dot ' + (ready ? 'ok' : failed ? 'bad' : 'busy'), title: ready ? 'Ready' : failed ? 'Needs attention' : 'Working on it' }));
      })));
  }).catch(noop);

  var lastLook = byId(LOOKS, cachedPrefs().lastLook);
  setAccent(byId(PALETTES, lastLook ? lastLook.palette : 'sage-red'));
  return {
    el: el,
    ready: Promise.resolve(),
    dispose: function () { disposed = true; window.removeEventListener('dragover', stopStray); window.removeEventListener('drop', stopStray); }
  };
}
