import { CAM_ART, END_ART, LAYOUT_ART, btn, byId, contrast, fill, h, ico, mixHex, segmented, setPressed, svg40, switchEl, toast } from './util.js';
import { FONTS, LOOKS, METRICS, OPT, PALETTES, applyLook, applyMyLook, autoHero, cachedPrefs, deleteLook, fonts, isEdited, lookKey, myLookId, normWord, optLabel, palLabel, putPrefs, saveLook, smallFieldText, suggestionsFor, tokens, voicePhrase } from './store.js';

export var SECTION_IDS = ['text', 'colors', 'font', 'layout', 'entrance', 'camera', 'pace', 'ending', 'effects', 'sound'];

/* ====================================================================== look tiles (Studio + Processing) */
var LAYOUT_THETA = { wall: 29, stripes: 29, giant: 16, poster: 6 };
/* the stack the engine draws every row with: a character the look font lacks (an accent in Gochi Hand) falls to Inter, never to a
   system font */
function fontStack(f) { return '"' + f.family + '", "FT Inter"'; }
function lookWordStyle(look, word) {
  var f = FONTS[look.font], m = METRICS[look.font], w = String(word || 'TEXT'), k = 0.3, kh = 0.6;
  if (m) {
    var sum = 0, i;
    for (i = 0; i < w.length; i++) { var a = m.w && m.w[w.charAt(i)]; sum += (a == null ? m.fallback : a); }
    sum += (f.ls || 0) * w.length;
    sum = Math.max(0.3, sum);
    /* size the word so its tilted box fits the tile: width and height both counted */
    var th = (LAYOUT_THETA[look.layout] || 29) * Math.PI / 180, cs = Math.cos(th), sn = Math.sin(th);
    k = 0.9 / (sum * cs + m.capH * sn);
    kh = 0.84 / (sum * sn + m.capH * cs);
  }
  var pal = look.pal || byId(PALETTES, look.palette);
  return {
    '--k': k.toFixed(4), '--kh': kh.toFixed(4), '--rot': '-' + (LAYOUT_THETA[look.layout] || 29) + 'deg',
    fontFamily: fontStack(f), fontWeight: String(f.weight), letterSpacing: (f.ls || 0) + 'em', color: pal.ink
  };
}
export function lookTile(look, word, onPick) {
  var pal = look.pal || byId(PALETTES, look.palette);   // a saved look has its own colours (look.pal)
  var wordEl = h('span', { class: 'look-word', style: lookWordStyle(look, word), text: word || 'TEXT' });
  var check = h('span', { class: 'look-check' }, ico('check', null, 14));
  /* a small spinner until the look fonts are in (they are preloaded at start-up; app.js gives up waiting after 3 s) */
  var art = h('span', { class: 'look-art is-loading', style: { background: pal.floor } }, wordEl, check, h('span', { class: 'spinner look-spin', 'aria-hidden': 'true' }));
  fonts.ready.then(function () { art.classList.remove('is-loading'); });
  var b = h('button', { type: 'button', class: 'look-card', 'aria-pressed': 'false', 'data-look': look.id, onclick: function () { onPick(look); } },
    art,
    h('span', { class: 'look-name', text: look.label }),
    h('span', { class: 'look-vibe', text: look.vibe }));
  b.setWord = function (w) {
    wordEl.textContent = w || 'TEXT';
    var st = lookWordStyle(look, w);
    wordEl.style.setProperty('--k', st['--k']);
    wordEl.style.setProperty('--kh', st['--kh']);
  };
  b.setSelected = function (on) { setPressed(b, on); };
  return b;
}

/* A small modal in the studio screen's own layer (same look as the Export dialog). Focus stays inside it, Escape and a click
   on the backdrop close it, and focus goes back to where it was. opts: { id, title, role, body, foot (buttons), focus (element) } */
function openDialog(host, opts) {
  var prev = document.activeElement;
  function close() {
    if (backdrop.parentNode) backdrop.parentNode.removeChild(backdrop);
    if (prev && document.contains(prev) && prev.focus) { try { prev.focus({ preventScroll: true }); } catch (e) { /* ignore */ } }
  }
  var dialog = h('div', { class: 'modal modal-sm', role: opts.role || 'dialog', 'aria-modal': 'true', 'aria-labelledby': opts.id + '-h', tabindex: '-1' },
    h('div', { class: 'modal-head' }, h('h2', { id: opts.id + '-h', text: opts.title })),
    h('div', { class: 'modal-body' }, opts.body),
    h('div', { class: 'modal-foot' }, opts.foot));
  var backdrop = h('div', { class: 'modal-backdrop' }, dialog);
  backdrop.addEventListener('pointerdown', function (e) { if (e.target === backdrop) close(); });
  backdrop.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(); return; }
    if (e.key !== 'Tab') return;
    var f = dialog.querySelectorAll('button:not([disabled]), input:not([disabled])');
    if (!f.length) return;
    var first = f[0], last = f[f.length - 1], act = document.activeElement;
    if (e.shiftKey && (act === first || act === dialog)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && act === last) { e.preventDefault(); first.focus(); }
  });
  host.appendChild(backdrop);
  try { (opts.focus || dialog).focus({ preventScroll: true }); } catch (e2) { /* ignore */ }
  return { close: close, el: dialog };
}

/* The side panel: looks, then the ten "Make it yours" sections. `c` is the studio controller (studio.js): c.S settings,
   c.take, c.ui, c.id, c.bind (register a repaint), c.update (change settings), c.commit. */
export function createPanel(c) {
  var openId = null, accItems = {}, brand = null, brandTouched = false;
  var mineTiles = [], openMenu = null, textArea = null;

  function heroWord() { return c.S && c.S.text && c.S.text.hero ? c.S.text.hero : 'TEXT'; }

  function setPhrase(phrase, source) {
    c.update(function (s) {
      s.text.phrase = phrase; s.text.source = source;
      s.text.edited = true;                         // the creator picked or typed words: Claude's later ideas are offered, never swapped in
      if (s.text.hero) {
        var found = tokens(phrase).some(function (t) { return normWord(t) === normWord(s.text.hero); });
        if (!found) s.text.hero = autoHero(phrase);
      }
    }, 'restart');
  }
  function pickLook(lookId) {
    c.S = applyLook(c.S, lookId);
    if (!c.take.hasAudio) c.S.sound.voice = false;
    putPrefs({ lastLook: lookId });
    c.commit('restart');
  }
  function pickMine(look) {
    c.S = applyMyLook(c.S, look.settings, c.take);
    putPrefs({ lastLook: myLookId(look.id) });
    c.commit('restart');
    toast('Applied “' + look.name + '”. Your words stayed.');
  }

  function buildPanel(panel) {
    /* --- Looks */
    var editedBadge = h('span', { class: 'badge', hidden: true, text: 'Edited' });
    var resetBtn = h('button', { type: 'button', class: 'link-btn', hidden: true, onclick: function () { pickLook(c.S.look); } }, ico('reset', null, 14), 'Reset');
    var lookTiles = LOOKS.map(function (l) { return lookTile(l, heroWord(), function (look) { pickLook(look.id); }); });
    function mineMatch() { var k = lookKey(c.S); return cachedPrefs().looks.some(function (l) { return lookKey(l.settings) === k; }); }
    c.bind(function () {
      var mine = mineMatch(), edited = isEdited(c.S) && !mine;
      editedBadge.hidden = !edited; resetBtn.hidden = !edited;
      lookTiles.forEach(function (t) { t.setSelected(!mine && t.getAttribute('data-look') === c.S.look); t.setWord(heroWord()); });
      mineTiles.forEach(function (t) { t.tile.setSelected(lookKey(t.look.settings) === lookKey(c.S)); t.tile.setWord(heroWord()); });
    });

    /* --- My looks: saved setups, applied to any take (everything but the words) */
    var myGrid = h('div', { class: 'look-grid two' });
    var myEmpty = h('p', { class: 'hint faint', text: 'Save a setup you like and use it on your next take.' });
    var myBlock = h('div', { class: 'my-looks' },
      h('div', { class: 'panel-head' }, h('h3', { id: 'mylooks-h', class: 'panel-title sm', text: 'My looks' }),
        btn('Save as my look', { small: true, icon: 'plus', onclick: openNameDialog })),
      myEmpty, myGrid);
    function closeMenu() { if (openMenu) { openMenu.menu.remove(); openMenu.btn.setAttribute('aria-expanded', 'false'); openMenu = null; } }
    function renderMine() {
      closeMenu();
      var list = cachedPrefs().looks;
      myEmpty.hidden = list.length > 0;
      mineTiles = list.map(function (look) {
        var s = look.settings || {}, pal = s.palette || {}, base = byId(LOOKS, s.look);
        var tile = lookTile({ id: myLookId(look.id), label: look.name, vibe: base ? 'Based on ' + base.label : '', font: FONTS[s.font] ? s.font : LOOKS[0].font,
          layout: s.layout || 'wall', pal: { floor: pal.floor || '#000000', ink: pal.ink || '#ffffff' } }, heroWord(), function () { pickMine(look); });
        var menuBtn = h('button', { type: 'button', class: 'tile-menu-btn', 'aria-label': 'More for ' + look.name, 'aria-haspopup': 'menu', 'aria-expanded': 'false' }, ico('more', null, 16));
        menuBtn.addEventListener('click', function (e) {
          e.stopPropagation();
          if (openMenu && openMenu.btn === menuBtn) { closeMenu(); return; }
          closeMenu();
          var del = h('button', { type: 'button', class: 'menu-item', role: 'menuitem', onclick: function () { closeMenu(); confirmDelete(look); } }, ico('x', null, 14), 'Delete');
          var menu = h('div', { class: 'tile-menu', role: 'menu', 'aria-label': 'Options for ' + look.name }, del);
          menuBtn.parentNode.appendChild(menu);
          menuBtn.setAttribute('aria-expanded', 'true');
          openMenu = { menu: menu, btn: menuBtn };
          del.focus();
        });
        var wrap = h('div', { class: 'my-look' }, tile, menuBtn);
        return { look: look, tile: tile, wrap: wrap };
      });
      fill(myGrid, mineTiles.map(function (t) { return t.wrap; }));
      c.syncAll();
    }
    c.on(document, 'pointerdown', function (e) { if (openMenu && !openMenu.menu.contains(e.target) && e.target !== openMenu.btn && !openMenu.btn.contains(e.target)) closeMenu(); });
    c.on(document, 'keydown', function (e) { if (e.key === 'Escape' && openMenu) { var b = openMenu.btn; closeMenu(); b.focus(); } });

    function openNameDialog() {
      var input = h('input', { type: 'text', class: 'input', maxlength: '30', autocomplete: 'off', 'aria-label': 'Look name', placeholder: 'For example: My series' });
      var counter = h('span', { class: 'counter num', text: '0/30' });
      var err = h('p', { class: 'inline-warn', hidden: true });
      var saveBtn = btn('Save', { kind: 'primary', disabled: true });
      var dlg = null, busy = false;
      function name() { return input.value.replace(/\s+/g, ' ').trim(); }
      function sync() { counter.textContent = input.value.length + '/30'; saveBtn.disabled = busy || !name(); }
      function submit() {
        if (busy || !name()) return;
        busy = true; sync(); err.hidden = true;
        saveLook(name(), c.S).then(function () {
          var saved = name();
          dlg.close();
          renderMine();
          toast('Saved “' + saved + '” to My looks.');
        }, function (e) { busy = false; sync(); err.hidden = false; err.textContent = e && e.message ? e.message : 'We couldn’t save this look.'; });
      }
      saveBtn.addEventListener('click', submit);
      input.addEventListener('input', sync);
      input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); submit(); } });
      dlg = openDialog(c.el, {
        id: 'name-look', title: 'Name your look',
        body: h('div', { class: 'field' },
          h('p', { class: 'muted note', text: 'Saves the colors, font, layout, camera, pace, ending, effects and sound. Your words stay with each take.' }),
          input, h('div', { class: 'field-foot' }, h('span', { class: 'muted', text: 'Use a name you already have to replace that look.' }), counter), err),
        foot: [btn('Cancel', { kind: 'ghost', onclick: function () { dlg.close(); } }), saveBtn],
        focus: input
      });
    }
    function confirmDelete(look) {
      var dlg = null, delBtn = btn('Delete', { kind: 'primary' }), cancelBtn = btn('Cancel', { kind: 'ghost', onclick: function () { dlg.close(); } });
      delBtn.addEventListener('click', function () {
        delBtn.disabled = true;
        deleteLook(look.id).then(function () { dlg.close(); renderMine(); toast('Deleted “' + look.name + '”.'); },
          function (e) { delBtn.disabled = false; toast((e && e.message) || 'We couldn’t delete this look.', 'error'); });
      });
      dlg = openDialog(c.el, {
        id: 'delete-look', title: 'Delete this look?', role: 'alertdialog',
        body: h('p', { class: 'muted note', text: '“' + look.name + '” will be removed from My looks. Takes that already use it keep their settings.' }),
        foot: [cancelBtn, delBtn], focus: cancelBtn
      });
    }

    var looks = h('section', { class: 'panel-section', 'aria-labelledby': 'looks-h' },
      h('div', { class: 'panel-head' }, h('h2', { id: 'looks-h', class: 'panel-title', text: 'Looks' }), h('div', { class: 'edit-tools' }, editedBadge, resetBtn)),
      h('p', { class: 'panel-sub', text: 'Start from a look, then make it yours.' }),
      h('div', { class: 'look-grid two' }, lookTiles), myBlock);
    renderMine();

    /* --- Make it yours */
    var defs = {
      text:     { title: 'Text',     icon: 'type',    value: function () { return c.S.text.phrase; },                        build: buildText },
      colors:   { title: 'Colors',   icon: 'palette', value: function () { return [h('i', { class: 'mini-swatch', style: { background: 'linear-gradient(90deg,' + c.S.palette.floor + ' 50%,' + c.S.palette.ink + ' 50%)' } }), palLabel(c.S.palette)]; }, build: buildColors },
      font:     { title: 'Font',     icon: 'font',    value: function () { return FONTS[c.S.font].label; },                  build: buildFont },
      layout:   { title: 'Layout',   icon: 'grid',    value: function () { return optLabel('layout', c.S.layout); },         build: buildLayout },
      entrance: { title: 'Entrance', icon: 'enter',   value: function () { return optLabel('entrance', c.S.entrance); },     build: buildEntrance },
      camera:   { title: 'Camera',   icon: 'video',   value: function () { return optLabel('camera', c.S.camera); },         build: buildCamera },
      pace:     { title: 'Pace',     icon: 'gauge',   value: function () { return optLabel('pace', c.S.pace); },             build: buildPace },
      ending:   { title: 'Ending',   icon: 'flag',    value: function () { return optLabel('ending', c.S.ending); },         build: buildEnding },
      effects:  { title: 'Effects',  icon: 'sparkles', value: function () { var n = Object.keys(c.S.fx).filter(function (k) { return c.S.fx[k]; }).length; return n + ' on'; }, build: buildEffects },
      sound:    { title: 'Sound',    icon: 'volume',  value: function () {
        var v = c.S.sound.voice && c.take.hasAudio, f = c.S.sound.sfx;
        return v && f ? 'Voice and effects' : v ? 'Voice only' : f ? 'Effects only' : 'Off';
      }, build: buildSound }
    };
    var acc = h('div', { class: 'acc' });
    SECTION_IDS.forEach(function (sid) {
      var def = defs[sid];
      var valueEl = h('span', { class: 'acc-value' });
      var head = h('button', { type: 'button', class: 'acc-head', id: 'acc-' + sid, 'aria-expanded': 'false', 'aria-controls': 'sec-' + sid, onclick: function () { openSection(sid); } },
        h('span', { class: 'acc-ico' }, ico(def.icon)), h('span', { class: 'acc-title', text: def.title }), valueEl, ico('chevron', 'chev'));
      var body = h('div', { class: 'acc-body', id: 'sec-' + sid, role: 'region', 'aria-labelledby': 'acc-' + sid, hidden: true });
      var item = h('div', { class: 'acc-item', 'data-section': sid }, head, body);
      accItems[sid] = { def: def, item: item, head: head, body: body, built: false };
      c.bind(function () { fill(valueEl, def.value()); });
      acc.appendChild(item);
    });
    var make = h('section', { class: 'panel-section', 'aria-labelledby': 'make-h' },
      h('div', { class: 'panel-head' }, h('h2', { id: 'make-h', class: 'panel-title', text: 'Make it yours' })),
      h('p', { class: 'panel-sub', text: 'Everything here is optional. Change what you like.' }), acc);
    fill(panel, looks, make);
  }

  function openSection(sid, instant) {
    openId = openId === sid ? null : sid;
    SECTION_IDS.forEach(function (k) {
      var a = accItems[k], open = k === openId;
      a.item.classList.toggle('is-open', open);
      a.head.setAttribute('aria-expanded', open ? 'true' : 'false');
      a.body.hidden = !open;
      if (open && !a.built) { a.built = true; a.body.appendChild(a.def.build()); c.syncAll(); }
    });
    try {
      var q = new URLSearchParams(location.hash.indexOf('?') >= 0 ? location.hash.slice(location.hash.indexOf('?') + 1) : '');
      if (openId) q.set('panel', openId); else q.delete('panel');
      var qs = q.toString();
      history.replaceState(null, '', '#/studio/' + encodeURIComponent(c.id) + (qs ? '?' + qs : ''));
    } catch (e) { /* the URL is a convenience */ }
    if (openId) requestAnimationFrame(function () {
      var item = accItems[openId] && accItems[openId].item;
      if (!item) return;
      var smooth = !instant && !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (window.matchMedia('(max-width: 600px)').matches) item.scrollIntoView({ block: 'start', behavior: smooth ? 'smooth' : 'auto' });
      else c.ui.panel.scrollTo({ top: Math.max(0, item.offsetTop - 12), behavior: smooth ? 'smooth' : 'auto' });
    });
  }

  /* small builders shared by the sections */
  function tiles(cls, items, getSel, onPick, render) {
    var wrap = h('div', { class: 'tiles ' + cls });
    var list = items.map(function (it) {
      var b = h('button', { type: 'button', class: 'tile', 'aria-pressed': 'false', 'data-id': it.id, onclick: function () { onPick(it.id); } }, render(it));
      wrap.appendChild(b);
      return { b: b, it: it };
    });
    c.bind(function () { var sel = getSel(); list.forEach(function (x) { setPressed(x.b, x.it.id === sel); }); });
    return wrap;
  }
  function hintFor(group, get) {
    var p = h('p', { class: 'hint' });
    c.bind(function () { p.textContent = (byId(OPT[group], get()) || {}).hint || ''; });
    return p;
  }
  function artTile(art) { return function (it) { return [h('span', { class: 'tile-art', html: art[it.id] ? svg40(art[it.id]) : '' }), h('span', { class: 'tile-label', text: it.label })]; }; }
  function switchRow(label, desc, getOn, onToggle, disabledReason) {
    var sw = switchEl(label, { disabled: !!disabledReason, onToggle: onToggle });
    c.bind(function () { sw.setOn(getOn()); });
    return h('div', { class: 'switch-row' + (disabledReason ? ' is-disabled' : '') },
      h('div', { class: 'switch-text' }, h('span', { class: 'switch-label', text: label }), desc || disabledReason ? h('span', { class: 'switch-desc', text: disabledReason || desc }) : null), sw);
  }
  /* .waiting() is true while a call is queued: a typed field must not be repainted from the settings in that time (another
     section opening repaints the panel, and would put the old words back before the debounce had read them) */
  /* a delayed call. waiting(): one is queued. now(): run the queued call at once (leaving the screen). cancel(): drop it. */
  var debounced = [];
  function debounce(fn, ms) {
    var t = 0, args = null;
    var d = function () { args = arguments; clearTimeout(t); t = setTimeout(function () { t = 0; fn.apply(null, args); }, ms); };
    d.waiting = function () { return t !== 0; };
    d.cancel = function () { clearTimeout(t); t = 0; };
    d.now = function () { if (!t) return; clearTimeout(t); t = 0; fn.apply(null, args); };
    debounced.push(d);
    return d;
  }
  /* the studio is being left: whatever the creator typed in the last 400 ms is applied now, so it is saved, then nothing stays queued */
  function flushPending() { debounced.forEach(function (d) { d.now(); d.cancel(); }); }

  /* 1 Text */
  function buildText() {
    var view = c.S.text.source || 'suggested';
    var vp = voicePhrase(c.take);
    var seg = segmented([{ id: 'speech', label: 'From your voice' }, { id: 'typed', label: 'Type it' }, { id: 'suggested', label: 'Suggestions' }],
      function (v) { view = v; seg.setValue(v); renderView(); }, 'Where the words come from');
    seg.setValue(view);
    var viewBox = h('div', { class: 'text-view' });

    var area = h('textarea', { class: 'input area', rows: '3', maxlength: '60', placeholder: 'Type the words for the floor', 'aria-label': 'Your words' });
    var counter = h('span', { class: 'counter num' });
    area.value = c.S.text.phrase;
    textArea = area;
    function count() { counter.textContent = area.value.length + '/60'; }
    var pushTyped = debounce(function () {
      if (c.disposed) return;      // a queued keystroke must not touch a studio that has been left
      var v = area.value.replace(/\s+/g, ' ').trim();
      if (v && v !== c.S.text.phrase) setPhrase(v, 'typed');
    }, 400);
    area.addEventListener('input', function () {
      // the creator is writing their own words: from the first key, Claude's ideas no longer replace the text (the phrase itself
      // reaches the settings 400 ms later)
      if (!c.S.text.edited) c.update(function (s) { s.text.edited = true; });
      count(); pushTyped(); showDropped(area.value + ' ' + (c.S.text.small || ''));
    });
    count();
    var typedView = h('div', null, area, h('div', { class: 'field-foot' }, h('span', { class: 'muted', text: 'Short is best. Two to eight words.' }), counter));

    /* characters the floor fonts cannot draw: named, so a missing emoji is no surprise */
    var droppedText = h('span');
    var droppedNote = h('div', { class: 'inline-warn', 'data-dropped': '', role: 'status', hidden: true }, ico('alert', 'callout-ico', 16), droppedText);
    function showDropped(text) {
      var list = window.FTLayout && window.FTLayout.dropped ? window.FTLayout.dropped(text) : [];
      droppedNote.hidden = !list.length;
      if (!list.length) return;
      // a lone combining mark is drawn on a dotted circle, so it can be seen
      droppedText.textContent = 'Left out: ' + list.map(function (ch) { return /\p{M}/u.test(ch) ? '◌' + ch : ch; }).join(' ') +
        " (emoji and symbols don't fit the floor fonts).";
    }

    function renderView() {
      if (view === 'speech') {
        if (!vp) {
          fill(viewBox, h('div', { class: 'soft-box' }, h('p', { class: 'muted', text: 'We couldn’t hear any words in this take. Type your own, or pick a suggestion.' })));
          return;
        }
        var used = c.S.text.source === 'speech' && c.S.text.phrase === vp;
        fill(viewBox, h('div', { class: 'soft-box' },
          h('p', { class: 'quote', text: '“' + vp + '”' }),
          h('div', { class: 'soft-foot' }, btn(used ? 'In use' : 'Use this', { kind: used ? '' : 'primary', small: true, disabled: used, icon: used ? 'check' : null, onclick: function () { setPhrase(vp, 'speech'); } }))));
      } else if (view === 'typed') {
        fill(viewBox, typedView);
      } else {
        fill(viewBox, h('div', { class: 'chips col' }, suggestionsFor(c.take).map(function (s) {
          return h('button', { type: 'button', class: 'chip wide', 'aria-pressed': (c.S.text.source === 'suggested' && c.S.text.phrase === s) ? 'true' : 'false', onclick: function () { setPhrase(s, 'suggested'); } }, s);
        })));
      }
    }
    renderView();
    var lastView = '';
    c.bind(function () {
      var key = view + '|' + c.S.text.source + '|' + c.S.text.phrase + '|' + (c.take.suggestionsRev || 0);
      if (key !== lastView && view !== 'typed') { lastView = key; renderView(); }
      if (document.activeElement !== area && !pushTyped.waiting() && area.value !== c.S.text.phrase) { area.value = c.S.text.phrase; count(); }
      showDropped((pushTyped.waiting() ? area.value : c.S.text.phrase) + ' ' + (c.S.text.small || ''));
    });

    /* hero word */
    var heroBox = h('div', { class: 'chips' }), heroKey = '';
    function setHero(t) { c.update(function (s) { s.text.hero = t; s.text.edited = true; }, 'restart'); }
    c.bind(function () {
      var seen = {}, toks = tokens(c.S.text.phrase).map(normWord).filter(function (t) { if (!t || seen[t]) return false; seen[t] = 1; return true; });     // a token the floor leaves out (an emoji) is no hero
      var key = toks.join('|');
      if (key !== heroKey) {
        heroKey = key;
        fill(heroBox, h('button', { type: 'button', class: 'chip', 'data-hero': '', onclick: function () { setHero(''); } }, 'None'),
          toks.map(function (t) { return h('button', { type: 'button', class: 'chip', 'data-hero': t, onclick: function () { setHero(t); } }, t); }));
      }
      var cur = c.S.text.hero ? normWord(c.S.text.hero) : '';
      Array.prototype.forEach.call(heroBox.children, function (c) { setPressed(c, c.getAttribute('data-hero') === cur); });
    });

    /* small line: off unless the creator turned it on; the field starts from their last words, else Claude's first suggestion */
    var armed = false;      // switched on while the field is still empty: the switch stays on until words arrive
    var smallInput = h('input', { type: 'text', class: 'input', maxlength: '40', placeholder: 'A short line for the floor', 'aria-label': 'Small line' });
    smallInput.value = c.S.text.small || smallFieldText(c.take);
    var smallSwitch = switchEl('Small line', { onToggle: function (on_) {
      if (on_) {
        var v = smallInput.value.trim();
        if (!v) { armed = true; c.syncAll(); smallInput.focus(); return; }
        c.update(function (s) { s.text.small = v; }, 'restart');
      } else { armed = false; c.update(function (s) { s.text.small = ''; }, 'restart'); }
    } });
    var pushSmall = debounce(function () {
      if (c.disposed) return;
      var v = smallInput.value.trim();
      if (!v) return;
      armed = false;
      if (c.S.text.small !== v) c.update(function (s) { s.text.small = v; }, 'restart');
    }, 400);
    smallInput.addEventListener('input', pushSmall);
    c.bind(function () {
      var on_ = !!c.S.text.small || armed;
      smallSwitch.setOn(on_); smallInput.disabled = !on_;
      if (document.activeElement === smallInput || pushSmall.waiting()) return;
      if (c.S.text.small) smallInput.value = c.S.text.small;
      else if (!armed) smallInput.value = smallFieldText(c.take);     // follows the last words and Claude's new ideas until the line is on
    });

    return h('div', { class: 'sec-body' },
      seg, viewBox, droppedNote,
      h('div', { class: 'field' }, h('div', { class: 'field-head' }, h('span', { class: 'field-label', text: 'Hero word' }), h('span', { class: 'muted', text: 'One big word, standing tall' })), heroBox),
      h('div', { class: 'field' }, h('div', { class: 'field-head' }, h('span', { class: 'field-label', text: 'Small line' }), smallSwitch), smallInput));
  }

  /* 2 Colors */
  function buildColors() {
    var grid = h('div', { class: 'swatch-grid' });
    function swatch(label, getColors, onPick) {
      var dot = h('i', { class: 'swatch-dot' });
      var b = h('button', { type: 'button', class: 'swatch', 'aria-pressed': 'false', onclick: onPick }, dot, h('span', { class: 'swatch-label', text: label }));
      b.paint = function () { var c = getColors(); dot.style.background = 'linear-gradient(90deg,' + c.floor + ' 50%,' + c.ink + ' 50%)'; };
      b.paint();
      return b;
    }
    var pals = PALETTES.map(function (p) {
      var b = swatch(p.label, function () { return p; }, function () { c.update(function (s) { s.palette = { id: p.id, floor: p.floor, ink: p.ink, small: p.small }; }, 'live'); });
      b.setAttribute('data-id', p.id);
      grid.appendChild(b);
      return b;
    });
    function brandNow() { return brand || { floor: c.S.palette.floor, ink: c.S.palette.ink }; }
    function brandPalette() { var b = brandNow(); return { id: 'brand', floor: b.floor, ink: b.ink, small: mixHex(b.floor, b.ink, 0.55) }; }
    brand = cachedPrefs().brand ? { floor: cachedPrefs().brand.floor, ink: cachedPrefs().brand.ink } : null;
    if (brand) brandTouched = true;
    var brandTile = swatch('Your brand', function () { return c.S.palette.id === 'brand' ? c.S.palette : brandNow(); }, function () {
      if (!brand) brand = { floor: c.S.palette.floor, ink: c.S.palette.ink };
      c.update(function (s) { s.palette = brandPalette(); }, 'live');
    });
    brandTile.setAttribute('data-id', 'brand');
    grid.appendChild(brandTile);

    var raf = 0;
    function colorField(label, key) {
      var input = h('input', { type: 'color', class: 'color-input', 'aria-label': label + ' color' });
      var code = h('code', { class: 'hex' });
      input.addEventListener('input', function () {
        if (!brand) brand = { floor: c.S.palette.floor, ink: c.S.palette.ink };
        brand[key] = input.value; brandTouched = true; putPrefs({ brand: { floor: brand.floor, ink: brand.ink } });
        if (raf) return;
        raf = requestAnimationFrame(function () { raf = 0; c.update(function (s) { s.palette = brandPalette(); }, 'live'); });
      });
      c.bind(function () { var v = (c.S.palette.id === 'brand' ? c.S.palette : brandNow())[key]; if (input.value !== v.toLowerCase()) input.value = v.toLowerCase(); code.textContent = v.toUpperCase(); });
      return h('label', { class: 'color-field' }, h('span', { class: 'field-label', text: label }), input, code);
    }
    var brandBox = h('div', { class: 'brand-box', hidden: true }, colorField('Floor', 'floor'), colorField('Words', 'ink'));
    var warn = h('div', { class: 'inline-warn', hidden: true }, ico('alert', 'callout-ico', 16), h('span', { text: 'Words may be hard to read on this floor.' }));
    c.bind(function () {
      pals.forEach(function (b) { setPressed(b, b.getAttribute('data-id') === c.S.palette.id); });
      setPressed(brandTile, c.S.palette.id === 'brand');
      brandTile.paint();
      brandBox.hidden = c.S.palette.id !== 'brand';
      warn.hidden = contrast(c.S.palette.floor, c.S.palette.ink) >= 2.5;
    });
    return h('div', { class: 'sec-body' }, grid, brandBox, warn);
  }

  /* 3 Font */
  function buildFont() {
    var items = Object.keys(FONTS).map(function (k) { return { id: k, label: FONTS[k].label }; });
    return h('div', { class: 'sec-body' }, tiles('cols-3 font-tiles', items, function () { return c.S.font; },
      function (k) { c.update(function (s) { s.font = k; }, 'restart'); },
      function (it) {
        var f = FONTS[it.id];
        return [h('span', { class: 'font-sample', style: { fontFamily: fontStack(f), fontWeight: String(f.weight), letterSpacing: (f.ls || 0) + 'em' }, text: 'Aa HOW' }),
                h('span', { class: 'tile-label', text: it.label })];
      }));
  }
  /* 4 Layout */
  function buildLayout() {
    return h('div', { class: 'sec-body' },
      tiles('cols-2', OPT.layout, function () { return c.S.layout; }, function (k) { c.update(function (s) { s.layout = k; }, 'restart'); }, artTile(LAYOUT_ART)),
      hintFor('layout', function () { return c.S.layout; }));
  }
  /* 5 Entrance */
  function buildEntrance() {
    return h('div', { class: 'sec-body' },
      tiles('cols-3', OPT.entrance, function () { return c.S.entrance; }, function (k) { c.update(function (s) { s.entrance = k; }, 'restart'); },
        function (it) { return [h('span', { class: 'ent-demo ent-' + it.id, 'aria-hidden': 'true' }, h('i'), h('i'), h('i')), h('span', { class: 'tile-label', text: it.label })]; }),
      hintFor('entrance', function () { return c.S.entrance; }));
  }
  /* 6 Camera */
  function buildCamera() {
    return h('div', { class: 'sec-body' },
      tiles('cols-3', OPT.camera, function () { return c.S.camera; }, function (k) { c.update(function (s) { s.camera = k; }, 'restart'); }, artTile(CAM_ART)),
      hintFor('camera', function () { return c.S.camera; }));
  }
  /* 7 Pace */
  function buildPace() {
    var noWords = !(c.take.words && c.take.words.length);
    var seg = segmented(OPT.pace.map(function (p) {
      return { id: p.id, label: p.label, disabled: p.id === 'speech' && noWords, title: p.id === 'speech' && noWords ? 'We didn’t hear any words in this take' : null };
    }), function (k) { c.update(function (s) { s.pace = k; }, 'restart'); }, 'Pace');
    var hint = h('p', { class: 'hint' });
    c.bind(function () {
      seg.setValue(c.S.pace);
      hint.textContent = (byId(OPT.pace, c.S.pace) || {}).hint || '';
    });
    return h('div', { class: 'sec-body' }, seg, hint,
      noWords ? h('p', { class: 'hint faint', text: '“On your voice” needs spoken words, and we didn’t hear any in this take.' }) : null);
  }
  /* 8 Ending */
  function buildEnding() {
    return h('div', { class: 'sec-body' },
      tiles('cols-2', OPT.ending, function () { return c.S.ending; }, function (k) { c.update(function (s) { s.ending = k; }, 'restart'); }, artTile(END_ART)),
      hintFor('ending', function () { return c.S.ending; }));
  }
  /* 9 Effects */
  function buildEffects() {
    return h('div', { class: 'sec-body switch-list' }, OPT.fx.map(function (f) {
      return switchRow(f.label, null, function () { return !!c.S.fx[f.id]; }, function (on_) { c.update(function (s) { s.fx[f.id] = on_; }, 'live'); });
    }));
  }
  /* 10 Sound */
  function buildSound() {
    return h('div', { class: 'sec-body switch-list' },
      switchRow('Your voice', 'The sound from your take.', function () { return !!c.S.sound.voice && !!c.take.hasAudio; },
        function (on_) { c.update(function (s) { s.sound.voice = on_; }, 'live'); }, c.take.hasAudio ? '' : 'This take has no sound.'),
      switchRow('Sound effects', 'Whooshes and landings for the words.', function () { return !!c.S.sound.sfx; },
        function (on_) { c.update(function (s) { s.sound.sfx = on_; }, 'live'); }),
      h('p', { class: 'hint faint', text: 'To hear them in the preview, turn on the speaker under the video.' }));
  }

  /* the creator has the words field in hand (a suggestion from Claude must not replace the text now) */
  function typing() { return !!textArea && document.activeElement === textArea; }
  return { build: buildPanel, openSection: openSection, flushPending: flushPending, typing: typing };
}
