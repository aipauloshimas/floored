var PANEL_BG = '#141417';

/* ====================================================================== helpers */
export function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
export function clone(o) { return JSON.parse(JSON.stringify(o)); }
export function delay(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
export function noop() {}
export function byId(list, id) { for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i]; return null; }
export function f2(x) { return (Math.round(x * 100) / 100).toFixed(2); }
export function f1(x) { return (Math.round(x * 10) / 10).toFixed(1); }



export function h(tag, props) {
  var el = document.createElement(tag);
  if (props) {
    for (var k in props) {
      var v = props[k];
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k === 'style') {
        if (typeof v === 'string') el.style.cssText = v;
        else for (var s in v) { if (s.indexOf('--') === 0) el.style.setProperty(s, v[s]); else el.style[s] = v[s]; }
      } else if (k.indexOf('on') === 0 && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else el.setAttribute(k, v === true ? '' : v);
    }
  }
  for (var i = 2; i < arguments.length; i++) append(el, arguments[i]);
  return el;
}
function append(el, c) {
  if (c == null || c === false) return;
  if (Array.isArray(c)) { for (var i = 0; i < c.length; i++) append(el, c[i]); return; }
  el.appendChild(c.nodeType ? c : document.createTextNode(String(c)));
}
export function empty(el) { while (el.firstChild) el.removeChild(el.firstChild); return el; }
export function fill(el) { empty(el); for (var i = 1; i < arguments.length; i++) append(el, arguments[i]); return el; }
export function setPressed(el, on) { el.setAttribute('aria-pressed', on ? 'true' : 'false'); }

/* sessionStorage for throw-away page state (a poster taken at upload); it may be blocked, so every call is guarded */
export function ssGet(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } }
export function ssSet(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { /* ignore */ } }

/* ====================================================================== icons (inline SVG, 1.5 px stroke at 18 px) */
export var IC = {
  upload: '<path d="M12 15.5V4.5m0 0L8 8.5m4-4l4 4"/><path d="M4.5 14.5v3a2 2 0 002 2h11a2 2 0 002-2v-3"/>',
  play: '<path d="M8 5.8v12.4a.8.8 0 001.2.7l10-6.2a.8.8 0 000-1.4L9.2 5.1A.8.8 0 008 5.8z" fill="currentColor"/>',
  pause: '<rect x="6.5" y="5" width="4" height="14" rx="1.2" fill="currentColor"/><rect x="13.5" y="5" width="4" height="14" rx="1.2" fill="currentColor"/>',
  repeat: '<path d="M17 3l3 3-3 3"/><path d="M4 11V9.5A3.5 3.5 0 017.5 6H20"/><path d="M7 21l-3-3 3-3"/><path d="M20 13v1.5a3.5 3.5 0 01-3.5 3.5H4"/>',
  volume: '<path d="M4 9.5v5h3.5l5 4v-13l-5 4z"/><path d="M16 9.2a4 4 0 010 5.6"/><path d="M18.6 6.6a8 8 0 010 10.8"/>',
  mute: '<path d="M4 9.5v5h3.5l5 4v-13l-5 4z"/><path d="M16.5 9.5l5 5m0-5l-5 5"/>',
  chevron: '<path d="M9 6l6 6-6 6"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4.5"/><path d="M12 17.4v.1"/>',
  info: '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5"/><path d="M12 8v.1"/>',
  folder: '<path d="M3.5 7.5a2 2 0 012-2H9l2 2.5h7.5a2 2 0 012 2v7.5a2 2 0 01-2 2h-13a2 2 0 01-2-2z"/>',
  download: '<path d="M12 4.5v11m0 0l-4-4m4 4l4-4"/><path d="M4.5 18v.5a1.5 1.5 0 001.5 1.5h12a1.5 1.5 0 001.5-1.5V18"/>',
  arrow: '<path d="M5 12h14m0 0l-5-5m5 5l-5 5"/>',
  reset: '<path d="M4.5 12a7.5 7.5 0 107.5-7.5 7.5 7.5 0 00-5.6 2.5"/><path d="M4.5 4v4h4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  more: '<circle cx="6.5" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none"/><circle cx="17.5" cy="12" r="1.4" fill="currentColor" stroke="none"/>',
  phone: '<rect x="7" y="2.5" width="10" height="19" rx="2.5"/><path d="M10.5 18.5h3"/>',
  frame: '<path d="M4 8.5V5.5A1.5 1.5 0 015.5 4h3M15.5 4h3A1.5 1.5 0 0120 5.5v3M20 15.5v3a1.5 1.5 0 01-1.5 1.5h-3M8.5 20h-3A1.5 1.5 0 014 18.5v-3"/><circle cx="12" cy="9.2" r="1.7"/><path d="M12 11.2v4.3M9.3 13h5.4M10.4 18l1.6-2.5 1.6 2.5"/>',
  pin: '<path d="M12 21s6.5-5.4 6.5-10.5a6.5 6.5 0 10-13 0C5.5 15.6 12 21 12 21z"/><circle cx="12" cy="10.5" r="2.2"/>',
  sun: '<circle cx="12" cy="12" r="3.6"/><path d="M12 3.5v2M12 18.500v2M3.500 12h2M18.500 12h2M6 6l1.400 1.400M16.600 16.600L18 18M6 18l1.400-1.400M16.600 7.400L18 6"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
  type: '<path d="M5 7V5.5h14V7M12 5.5v13M9.5 18.5h5"/>',
  palette: '<path d="M12 3.5a8.5 8.5 0 100 17c1.2 0 1.9-.8 1.9-1.8 0-1.5-1.3-1.6-1.3-2.9 0-1 .8-1.6 2-1.6h2.4a3.5 3.5 0 003.5-3.5c0-3.9-3.8-7.2-8.5-7.2z"/><circle cx="7.8" cy="11.2" r=".6" fill="currentColor"/><circle cx="10.4" cy="7.6" r=".6" fill="currentColor"/><circle cx="14.8" cy="7.9" r=".6" fill="currentColor"/>',
  font: '<path d="M3.5 19L9 5l5.5 14M5.7 14.5h6.6"/><path d="M15.5 19c0-2.2.9-3.4 2.4-3.4s2.3 1 2.3 2.6V19"/>',
  grid: '<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>',
  enter: '<path d="M3.5 12H15"/><path d="M11.5 7.5L16 12l-4.5 4.5"/><path d="M20 5.5v13"/>',
  video: '<rect x="3" y="6.5" width="12.5" height="11" rx="2.5"/><path d="M15.5 10.5l5-2.5v8l-5-2.5"/>',
  gauge: '<path d="M4.5 17a8.5 8.5 0 1115 0"/><path d="M12 14l3.5-4.5"/><circle cx="12" cy="14.2" r="1.1"/>',
  flag: '<path d="M6 21V4"/><path d="M6 5h11.5l-2.5 3.5 2.5 3.5H6"/>',
  sparkles: '<path d="M11 4l1.7 4.6 4.6 1.7-4.6 1.7L11 16.6l-1.7-4.6L4.700 10.300l4.600-1.700z"/><path d="M18.200 15.200l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z"/>',
  speaker: '<path d="M4 9.5v5h3.5l5 4v-13l-5 4z"/><path d="M16 9.2a4 4 0 010 5.6"/>'
};
export function svgWrap(inner, size) {
  size = size || 18;
  var sw = (1.5 * 24 / size).toFixed(2);
  return '<svg viewBox="0 0 24 24" width="' + size + '" height="' + size + '" fill="none" stroke="currentColor" stroke-width="' + sw +
    '" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + inner + '</svg>';
}
export function ico(name, cls, size) { return h('span', { class: 'ico' + (cls ? ' ' + cls : ''), html: svgWrap(IC[name] || '', size) }); }
export function svg40(inner) {
  return '<svg viewBox="0 0 40 40" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">' + inner + '</svg>';
}
/* camera diagrams */
export var CAM_ART = {
  pull:  '<rect x="5" y="5" width="30" height="30" rx="4" opacity=".4"/><rect x="14.500" y="14.500" width="11" height="11" rx="2.500"/><g><path d="M6.500 6.500L12 12m-4.600 0H12V7.400"/><path d="M6.500 6.500L12 12m-4.600 0H12V7.400" transform="rotate(180 20 20)"/></g>',
  crane: '<path d="M20 31V9m0 0l-5.500 5.500M20 9l5.500 5.500"/><path d="M8 33.500h24" opacity=".5"/>',
  orbit: '<path d="M6.500 23c0-4.500 6-8 13.500-8s13.500 3.500 13.500 8-6 8-13.500 8"/><path d="M30.500 11.500l3.400 3.600-4.800 1"/><circle cx="20" cy="23" r="2.200" fill="currentColor" stroke="none"/>',
  push:  '<rect x="5" y="5" width="30" height="30" rx="4" opacity=".4"/><rect x="13" y="13" width="14" height="14" rx="2.500"/><g><path d="M12 12L6.500 6.500m0 4.600V6.500h4.600"/><path d="M12 12L6.500 6.500m0 4.600V6.500h4.600" transform="rotate(180 20 20)"/></g>',
  still: '<rect x="11" y="18" width="18" height="14" rx="3.500"/><path d="M15 18v-4.500a5 5 0 0110 0V18"/>'
};
/* layout schematics */
export var LAYOUT_ART = {
  wall: '<g transform="rotate(-29 20 20)" stroke-width="4.200"><path d="M-8 4h14M10 4h20M34 4h12M-8 12h24M20 12h10M34 12h12M-8 20h10M6 20h22M32 20h14M-8 28h20M16 28h12M32 28h14M-8 36h12M8 36h22M34 36h12"/></g>',
  giant: '<g transform="rotate(-16 20 20)"><rect x="3" y="13" width="34" height="14" rx="2.500" fill="currentColor" stroke="none"/></g>',
  stripes: '<g transform="rotate(-29 20 20)" stroke-width="5"><path d="M-6 8h50M-6 20h50M-6 32h50"/></g>',
  poster: '<g transform="rotate(-6 20 20)" fill="currentColor" stroke="none"><rect x="6" y="7" width="28" height="7" rx="1.500"/><rect x="6" y="16.500" width="20" height="7" rx="1.500"/><rect x="6" y="26" width="25" height="7" rx="1.500"/></g>'
};
/* ending icons */
export var END_ART = {
  cut:  '<rect x="6" y="10" width="28" height="20" rx="3.500"/><path d="M20 6v28" stroke-dasharray="2.500 3.500"/>',
  exit: '<path d="M6 13h13M6 20h19M6 27h11"/><path d="M23 13h5M29 20h5M21 27h7" opacity=".4"/>',
  dive: '<circle cx="20" cy="20" r="14" opacity=".35"/><circle cx="20" cy="20" r="8.500" opacity=".65"/><circle cx="20" cy="20" r="2.600" fill="currentColor" stroke="none"/>',
  sink: '<path d="M7 17l13-6.500L33 17l-13 6.500z"/><path d="M20 27.500V34m0 0l-3-3m3 3l3-3"/>'
};

/* ====================================================================== colour */
function hex2rgb(hx) {
  hx = String(hx).replace('#', '');
  if (hx.length === 3) hx = hx.split('').map(function (c) { return c + c; }).join('');
  var n = parseInt(hx, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}
function rgb2hex(r, g, b) {
  function p(v) { var s = Math.round(clamp(v, 0, 255)).toString(16); return s.length < 2 ? '0' + s : s; }
  return '#' + p(r) + p(g) + p(b);
}
function lum(hx) {
  var c = hex2rgb(hx).map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
export function contrast(a, b) { var la = lum(a), lb = lum(b); return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05); }
export function mixHex(a, b, t) {
  var x = hex2rgb(a), y = hex2rgb(b);
  return rgb2hex(x[0] + (y[0] - x[0]) * t, x[1] + (y[1] - x[1]) * t, x[2] + (y[2] - x[2]) * t);
}
/* UI accent follows the picked look: the ink, or the floor when the ink is too dark to read on the panel */
function accentFor(pal) {
  if (contrast(pal.ink, PANEL_BG) >= 3) return pal.ink;
  if (contrast(pal.floor, PANEL_BG) >= 3) return pal.floor;
  return '#EDEDF0';
}
function onAccent(acc) { return contrast(acc, '#0B0B0D') >= contrast(acc, '#FFFFFF') ? '#0B0B0D' : '#FFFFFF'; }
export function setAccent(pal) {
  var a = accentFor(pal), st = document.documentElement.style;
  st.setProperty('--accent', a);
  st.setProperty('--on-accent', onAccent(a));
}

/* ====================================================================== toast */
var toastEl = null, toastTimer = 0;
export function toast(msg, kind) {
  if (!toastEl) { toastEl = h('div', { class: 'toast', role: 'status', 'aria-live': 'polite' }); document.body.appendChild(toastEl); }
  toastEl.className = 'toast show' + (kind ? ' ' + kind : '');
  toastEl.textContent = msg;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function () { toastEl.className = 'toast' + (kind ? ' ' + kind : ''); }, 3600);
}

/* ====================================================================== shared widgets */
var MARK = '<svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path d="M3.500 17.500L8.500 6.500h12l-5 11z" fill="var(--accent)"/><path d="M3.500 17.500L8.500 6.500h12l-5 11z" fill="none" stroke="var(--bg)" stroke-width="1.500" stroke-linejoin="round" opacity=".28" transform="translate(-1.200 1.800)"/></svg>';
export function topbar(opts) {
  opts = opts || {};
  var el = h('header', { class: 'topbar' },
    h('a', { class: 'brand', href: '#/', 'aria-label': 'floored, home' },
      h('span', { class: 'brand-mark', html: MARK }),
      h('span', { class: 'brand-name', text: 'floored.' })),
    opts.chip || null,
    h('div', { class: 'spacer' }),
    opts.actions || null);
  return el;
}
export function btn(label, o) {
  o = o || {};
  var b = h('button', { type: 'button', class: 'btn' + (o.kind ? ' ' + o.kind : '') + (o.small ? ' small' : ''), 'aria-label': o.aria, title: o.title, disabled: o.disabled, onclick: o.onclick },
    o.icon ? ico(o.icon) : null, label != null && label !== '' ? h('span', { class: 'btn-label', text: label }) : null);
  return b;
}
/* The cut-out video is a VP9 webm with transparency: Chrome, Edge, Brave, Arc and the Claude app's pane play it, Safari and Firefox
   do not (yet). Chromium browsers say so in navigator.userAgentData. */
export function isChromium() {
  var d = navigator.userAgentData;
  return !!(d && d.brands && d.brands.some(function (b) { return /Chromium/.test(b.brand); }));
}
/* a bar to put above the studio when the browser is not Chromium (null when it is), with the page address to copy */
export function browserNotice() {
  if (isChromium()) return null;
  var url = h('span', { class: 'notice-url num', title: location.href, text: location.href });
  var copy = h('button', { type: 'button', class: 'btn small' }, h('span', { class: 'btn-label', text: 'Copy' }));
  var timer = 0;
  function done(ok) {
    copy.firstChild.textContent = ok ? 'Copied' : 'Select and copy';
    clearTimeout(timer);
    timer = setTimeout(function () { copy.firstChild.textContent = 'Copy'; }, 2400);
  }
  copy.addEventListener('click', function () {
    var href = location.href;
    function fallback() {
      // no clipboard API (or it was refused): select the address so Ctrl+C / Cmd+C finishes the job
      var ok = false;
      try {
        var ta = h('textarea', { 'aria-hidden': 'true', style: 'position:fixed;left:-9999px;top:0', text: href });
        document.body.appendChild(ta); ta.select(); ok = document.execCommand('copy'); document.body.removeChild(ta);
      } catch (e) { ok = false; }
      done(ok);
    }
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(href).then(function () { done(true); }, fallback);
    else fallback();
  });
  return h('div', { class: 'browser-notice', role: 'status' },
    h('span', { class: 'notice-msg' }, ico('alert', 'callout-ico', 18),
      h('span', { text: "Open this page in Chrome or Edge. This browser can't play the cut-out video yet." })),
    url, copy,
    h('a', { class: 'btn small', href: 'https://www.google.com/chrome/', target: '_blank', rel: 'noopener' }, h('span', { class: 'btn-label', text: 'Get Chrome' })));
}
export function callout(kind, title, msg, extra) {
  return h('div', { class: 'callout ' + kind, role: kind === 'error' ? 'alert' : 'note' },
    ico(kind === 'error' ? 'alert' : kind === 'info' ? 'info' : 'alert', 'callout-ico'),
    h('div', { class: 'callout-body' }, title ? h('strong', { text: title }) : null, msg ? h('p', { text: msg }) : null, extra || null));
}
export function switchEl(label, opts) {
  opts = opts || {};
  var b = h('button', { type: 'button', class: 'switch', role: 'switch', 'aria-checked': 'false', 'aria-label': label, disabled: opts.disabled, onclick: function () { if (!b.disabled && opts.onToggle) opts.onToggle(b.getAttribute('aria-checked') !== 'true'); } },
    h('span', { class: 'switch-knob' }));
  b.setOn = function (v) { b.setAttribute('aria-checked', v ? 'true' : 'false'); };
  return b;
}
export function segmented(options, onPick, label) {
  var wrap = h('div', { class: 'seg', role: 'group', 'aria-label': label || null });
  var btns = {};
  options.forEach(function (o) {
    var b = h('button', { type: 'button', class: 'seg-btn', 'aria-pressed': 'false', disabled: o.disabled, title: o.title || null, onclick: function () { if (!b.disabled) onPick(o.id); } }, o.label);
    btns[o.id] = b;
    wrap.appendChild(b);
  });
  wrap.setValue = function (v) { Object.keys(btns).forEach(function (k) { setPressed(btns[k], k === v); }); };
  return wrap;
}
