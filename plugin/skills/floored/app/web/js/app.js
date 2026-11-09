import { byId, clone, delay, noop, setAccent } from './util.js';
import { DEBUG, LOOKS, PALETTES, cachedPrefs, fonts, init } from './store.js';
import { homeScreen } from './home.js';
import { processingScreen } from './processing.js';
import { studioScreen } from './studio.js';

var app = document.getElementById('app');

/* ====================================================================== fonts */
/* Every look font and Inter are fetched at start-up (the engine's own preloadFonts), so switching looks never waits on one and the
   look tiles draw in the right font at once. Tiles and data-fonts wait for it, but never longer than 3 s. */
var FONT_WAIT_MS = 3000;
function loadFonts() {
  if (!document.fonts || !document.fonts.load) return Promise.resolve();
  var jobs = [document.fonts.load('400 14px "FT UI"'), document.fonts.load('600 14px "FT UI"')];
  if (window.Floored && window.Floored.preloadFonts) jobs.push(window.Floored.preloadFonts('/engine/fonts/'));
  return Promise.race([Promise.all(jobs).catch(noop), delay(FONT_WAIT_MS)]);
}

/* ====================================================================== router + boot */
var current = null;
function unmount() {
  if (!current) return;
  try { current.screen.dispose(); } catch (e) { DEBUG.log.push('dispose: ' + e.message); }
  if (current.screen.el.parentNode) current.screen.el.parentNode.removeChild(current.screen.el);
  current = null;
}
function parseHash() {
  var raw = (location.hash || '').replace(/^#/, '') || '/';
  var qi = raw.indexOf('?');
  var path = qi >= 0 ? raw.slice(0, qi) : raw;
  var query = new URLSearchParams(qi >= 0 ? raw.slice(qi + 1) : '');
  var parts = path.split('/').filter(Boolean), id = null;
  if (parts[1]) { try { id = decodeURIComponent(parts[1]); } catch (e) { id = parts[1]; } }
  return { name: parts[0] || 'home', id: id, query: query };
}
function mountScreen(kind, id, make) {
  if (current && current.kind === kind && current.id === id) return current;
  unmount();
  document.title = 'floored';
  try { delete document.documentElement.dataset.ready; } catch (e) { /* ignore */ }
  var screen = make();
  current = { kind: kind, id: id, screen: screen };
  app.appendChild(screen.el);
  try { window.scrollTo(0, 0); } catch (e2) { /* ignore */ }
  screen.ready.then(function () { if (current && current.screen === screen) document.documentElement.dataset.ready = '1'; });
  return current;
}
function route() {
  var r = parseHash();
  document.documentElement.setAttribute('data-route', r.name);
  if (r.name === 'processing' && r.id) { mountScreen('processing', r.id, function () { return processingScreen(r.id); }); return; }
  if ((r.name === 'studio' || r.name === 'export') && r.id) {
    var cur = mountScreen('studio', r.id, function () { return studioScreen(r.id, r.query); });
    cur.screen.setExport(r.name === 'export');
    return;
  }
  if (r.name !== 'home') { location.replace('#/'); return; }
  mountScreen('home', null, function () { return homeScreen(); });
}

var booted = false;
window.addEventListener('hashchange', function () { if (booted) route(); });
window.addEventListener('error', function (e) { DEBUG.log.push('error: ' + (e && e.message)); });
window.addEventListener('unhandledrejection', function (e) { DEBUG.log.push('rejection: ' + (e && e.reason && e.reason.message || e.reason)); });
DEBUG.route = route;
/* Test hook: window.__ft is what the Playwright smoke tests (tests/ui) and later tasks use to look inside the studio.
   Nothing in the app calls these.
     __ft.screen()    the current screen: 'home' | 'processing' | 'studio' | 'export'
     __ft.settings()  a deep copy of the studio's current settings (null outside the studio)
     __ft.take()      the studio's current take object (null outside the studio)
     __ft.seek(t)     pause the live preview at t seconds; resolves once it has painted
   Also on it: log (errors the app caught), route, and studio ({ S, preview, take, update }) while a take is open. */
DEBUG.screen = function () { var n = parseHash().name; return n === 'processing' || n === 'studio' || n === 'export' ? n : 'home'; };
DEBUG.settings = function () { return DEBUG.studio ? clone(DEBUG.studio.S) : null; };
DEBUG.take = function () { return DEBUG.studio ? DEBUG.studio.take : null; };
DEBUG.seek = function (t) {
  function frames(n) { return new Promise(function (res) { (function tick() { if (n-- <= 0) res(); else requestAnimationFrame(tick); })(); }); }
  function untilReady(left) {
    if (DEBUG.studio && document.documentElement.dataset.ready === '1') return Promise.resolve();
    if (left <= 0) return Promise.reject(new Error('The studio is not ready.'));
    return delay(50).then(function () { return untilReady(left - 50); });
  }
  return untilReady(20000).then(function () {
    DEBUG.studio.preview.pause();
    DEBUG.studio.preview.seek(t);
    return frames(2);
  });
};
/* the creator's saved preferences come from the server first: the accent colour and the start screens depend on them */
init().then(function () {
  var lk = byId(LOOKS, cachedPrefs().lastLook) || LOOKS[0];
  setAccent(byId(PALETTES, lk.palette) || PALETTES[0]);
  booted = true;
  route();
});
fonts.ready = loadFonts();
fonts.ready.then(function () { document.documentElement.dataset.fonts = '1'; });
