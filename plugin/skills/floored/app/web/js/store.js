import { byId, clone, toast } from './util.js';
import { api } from './api.js';

export { ssGet, ssSet } from './util.js';

/* the data, settings and server-side storage every screen shares. window.__ft is the debug and test hook (see app.js).
   Where things live (Task 15): the take's settings, the last look, the brand colours, the small line and "My looks" are
   kept by the server (settings/<take>.json in the workspace, prefs.json in the user folder), so they survive a restart on
   another port. The browser keeps nothing but throw-away page state (sessionStorage: the upload poster). Settings an older
   build left in localStorage are ignored on purpose: nothing to migrate. */
var D = window.FT_DATA;
export var METRICS = window.FT_METRICS || {};
export var OPT = D.OPTIONS;
export var FONTS = D.FONTS;
export var PALETTES = D.PALETTES;
export var LOOKS = D.LOOKS;
export var DEBUG = (window.__ft = { log: [] });
/* the look fonts: app.js starts the preload and sets .ready; look tiles wait on it (with a 3 s limit set where it is started) */
export var fonts = { ready: Promise.resolve() };

/* ====================================================================== words and settings */
// a word as the layout draws it (NFC, locale-free upper-case, only the characters the fonts have), so a hero picked here is
// found by FTLayout's own matching: toLocaleUpperCase() turned "istanbul" into "İSTANBUL" under a Turkish locale
export function normWord(w) { return window.FTLayout.words(w).join(' '); }
export function tokens(phrase) { return String(phrase || '').trim().split(/\s+/).filter(Boolean); }
function letters(w) { return w.replace(/[^A-Za-z0-9À-ɏ]/g, ''); }
export function autoHero(phrase) {
  var t = tokens(phrase), best = '', i;
  for (i = 0; i < t.length; i++) if (letters(t[i]).toUpperCase() === 'TEXT') return normWord(t[i]);
  // the payoff word: usually the last one with some weight ("... for FREE")
  for (i = t.length - 1; i >= 0; i--) if (letters(t[i]).length >= 4) return normWord(t[i]);
  for (i = 0; i < t.length; i++) if (letters(t[i]).length > letters(best).length) best = t[i];
  return letters(best).length >= 3 ? normWord(best) : '';
}
export function suggestionsFor(take) { return (take && take.suggestions && take.suggestions.length) ? take.suggestions : D.SUGGESTIONS; }
export function voicePhrase(take) {
  var ws = (take && take.words) || [];
  var p = ws.map(function (w) { return String(w.word).trim(); }).filter(Boolean).join(' ');
  return p || String((take && take.transcript) || '').trim();
}
var SMALL_MAX = 40;
/* Claude's suggestions for the small line (written into the take with `ft suggest`) */
export function smallSuggestionsFor(take) { return (take && take.smallSuggestions && take.smallSuggestions.length) ? take.smallSuggestions : []; }
/* the small line a new take starts with: off, unless the creator left it on last time; then their words (or Claude's first
   suggestion, if they left it on with no words). */
function smallDefault(take) {
  var sm = prefsCache.small;
  if (!sm || !sm.on) return '';
  return String(sm.text || smallSuggestionsFor(take)[0] || '').slice(0, SMALL_MAX);
}
/* what the small-line field shows while the line is off: the creator's last words, else Claude's first suggestion */
export function smallFieldText(take) {
  return String(prefsCache.small.text || smallSuggestionsFor(take)[0] || '').slice(0, SMALL_MAX);
}
function defaultText(take) {
  // the take's own words come first when it has speech; suggestions only when it has none
  var voice = voicePhrase(take);
  if (voice) return { source: 'speech', phrase: voice, hero: autoHero(voice), small: smallDefault(take) };
  var phrase = suggestionsFor(take)[0];
  return { source: 'suggested', phrase: phrase, hero: autoHero(phrase), small: smallDefault(take) };
}
function lookBase(lookId, text) { return D.lookSettings(lookId, text); }
/* apply a look's recipe on top of the current settings, keeping the creator's words and sound choices */
export function applyLook(S, lookId) {
  var b = lookBase(lookId, clone(S.text));
  var keep = { text: S.text, sound: S.sound };
  var n = clone(b);
  n.text = keep.text; n.sound = keep.sound;
  return n;
}
function sanitize(s, take) {
  var base = lookBase(byId(LOOKS, s && s.look) ? s.look : 'original', defaultText(take));
  var o = Object.assign({}, base, s || {});
  o.text = Object.assign({}, base.text, (s && s.text) || {});
  o.palette = Object.assign({}, base.palette, (s && s.palette) || {});
  o.fx = Object.assign({}, base.fx, (s && s.fx) || {});
  o.sound = Object.assign({}, base.sound, (s && s.sound) || {});
  ['layout', 'entrance', 'camera', 'pace', 'ending'].forEach(function (k) { if (!byId(OPT[k], o[k])) o[k] = base[k]; });
  if (!FONTS[o.font]) o.font = base.font;
  if (o.pace === 'speech' && !(take.words && take.words.length)) o.pace = 'smooth';
  if (!take.hasAudio) o.sound.voice = false;
  if (!o.text.phrase || !String(o.text.phrase).trim()) o.text = clone(base.text);
  return o;
}
/* ====================================================================== my looks
   A saved look is a settings object without the words: everything a creator would want the next take to share (colours,
   font, layout, entrance, camera, pace, ending, effects, sound). TEXT_KEYS names the settings keys that count as "the
   words" and stay each take's own: the phrase, the hero word, the small line (and where the phrase came from). */
export var TEXT_KEYS = ['text'];
export function lookToSave(S) {
  var n = clone(S);
  TEXT_KEYS.forEach(function (k) { delete n[k]; });
  return n;
}
/* the take's settings with a saved look laid over them: all of the look, none of its words */
export function applyMyLook(S, saved, take) {
  var n = clone(saved);
  TEXT_KEYS.forEach(function (k) { n[k] = clone(S[k]); });
  return sanitize(n, take);
}
/* two setups that look the same (the words and the voice switch, which depends on the take, do not count) */
export function lookKey(S) {
  var p = S.palette || {}, sound = S.sound || {}, fx = S.fx || {};
  return JSON.stringify([S.look, p.id, p.floor, p.ink, S.font, S.layout, S.entrance, S.camera, S.pace, S.ending,
    OPT.fx.map(function (f) { return !!fx[f.id]; }), !!sound.sfx]);
}
export function myLookId(id) { return 'my:' + id; }

/* ====================================================================== server storage */
var prefsCache = { lastLook: null, brand: null, small: { on: false, text: '' }, looks: [] };
/* what the server last told us, without asking again (for screens that must paint at once: the accent colour, the picker) */
export function cachedPrefs() { return prefsCache; }
export function prefs() {
  return api('/api/prefs').then(function (p) { prefsCache = p; return p; });
}
export function looks() {
  return api('/api/looks').then(function (list) { prefsCache.looks = list; return list; });
}
/* called once at start-up; the studio still opens (on defaults) if the server does not answer */
export function init() { return prefs().catch(function () { return prefsCache; }); }

var pendingSettings = {}, pendingPrefs = null, timer = 0, lastSaveToast = 0, inflight = Promise.resolve();
var SAVE_DELAY = 400;
function schedule() { clearTimeout(timer); timer = setTimeout(flush, SAVE_DELAY); }
function send(method, path, body) {
  // keepalive lets the request finish while the page is going away (sendBeacon cannot do PUT)
  return api(path, { method: method, headers: { 'Content-Type': 'application/json' }, body: body, keepalive: true }).then(function () { return true; }, function (err) {
    var now = Date.now();
    if (now - lastSaveToast > 10000) { lastSaveToast = now; toast('Your last change was not saved. ' + (err && err.message ? err.message : ''), 'error'); }
    return false;
  });
}
/* write what is waiting right now; resolves when the server has it (or did not answer) */
export function flush() {
  clearTimeout(timer); timer = 0;
  var jobs = [];
  Object.keys(pendingSettings).forEach(function (id) {
    var body = pendingSettings[id];
    delete pendingSettings[id];
    jobs.push(send('PUT', '/api/takes/' + encodeURIComponent(id) + '/settings', body).then(function (ok) {
      if (!ok && pendingSettings[id] == null) pendingSettings[id] = body;       // try again with the next change
    }));
  });
  if (pendingPrefs) {
    var p = pendingPrefs;
    pendingPrefs = null;
    jobs.push(send('PUT', '/api/prefs', JSON.stringify(p)).then(function (ok) {
      if (!ok) pendingPrefs = mergePatch(p, pendingPrefs);
    }));
  }
  inflight = Promise.all([inflight].concat(jobs)).then(function () {});
  return inflight;
}
window.addEventListener('pagehide', flush);
document.addEventListener('visibilitychange', function () { if (document.hidden) flush(); });

function mergePatch(base, patch) {
  var out = Object.assign({}, base || {}, patch || {});
  if (base && base.small && patch && patch.small) out.small = Object.assign({}, base.small, patch.small);
  return out;
}
/* lastLook, brand, small: the cache changes at once, the server hears about it 400 ms after the last change */
export function putPrefs(patch) {
  Object.keys(patch).forEach(function (k) {
    prefsCache[k] = k === 'small' ? Object.assign({}, prefsCache.small, patch.small) : patch[k];
  });
  pendingPrefs = mergePatch(pendingPrefs, patch);
  schedule();
}
/* keep the small line for the next take: on or off, and its words */
export function rememberSmall(S) {
  var on = !!S.text.small, text = String(S.text.small || prefsCache.small.text || '').slice(0, SMALL_MAX);
  if (on !== prefsCache.small.on || text !== prefsCache.small.text) putPrefs({ small: { on: on, text: text } });
}
export function saveLook(name, S) {
  return api('/api/looks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name, settings: lookToSave(S) }) })
    .then(function (r) { return looks().then(function () { return r.id; }); });
}
export function deleteLook(id) {
  return api('/api/looks/' + encodeURIComponent(id), { method: 'DELETE' }).then(function () {
    prefsCache.looks = prefsCache.looks.filter(function (l) { return l.id !== id; });
    if (prefsCache.lastLook === myLookId(id)) putPrefs({ lastLook: 'original' });
  });
}

/* the take's saved settings; a take that has none starts from the last look (a built-in one, or one of "my looks") */
/* takes whose saved settings could not be read: we never write over a file we did not manage to read */
var unreadable = {};
export function loadSettings(take) {
  delete unreadable[take.id];
  return flush().then(function () {
    var got = api('/api/takes/' + encodeURIComponent(take.id) + '/settings').catch(function (err) {
      // a 404 means there is nothing saved (and nothing to lose); any other failure may hide a real file
      if (err && err.status === 404) return null;
      unreadable[take.id] = true;
      delete pendingSettings[take.id];
      toast('Couldn’t load your settings for this take. Your changes won’t be saved until you reload.', 'error');
      return null;
    });
    return Promise.all([got, prefs().catch(function () { return prefsCache; })]);
  }).then(function (r) {
    var stored = r[0];
    if (stored && typeof stored === 'object' && Object.keys(stored).length) return sanitize(stored, take);
    var last = prefsCache.lastLook, mine = null;
    if (last && last.indexOf('my:') === 0) mine = prefsCache.looks.filter(function (l) { return myLookId(l.id) === last; })[0] || null;
    var start = lookBase(byId(LOOKS, last) ? last : 'original', defaultText(take));
    return mine ? applyMyLook(start, mine.settings, take) : sanitize(start, take);
  });
}
export function saveSettings(take, S) {
  if (unreadable[take.id]) return;
  pendingSettings[take.id] = JSON.stringify(S);
  schedule();
}
/* is the current setup different from the look it started from (words and sound do not count) */
export function isEdited(S) {
  var b = lookBase(S.look, S.text);
  if (S.palette.id !== b.palette.id) return true;
  var keys = ['font', 'layout', 'entrance', 'camera', 'pace', 'ending'], i;
  for (i = 0; i < keys.length; i++) if (S[keys[i]] !== b[keys[i]]) return true;
  for (var k in b.fx) if (!!S.fx[k] !== !!b.fx[k]) return true;
  return false;
}
export function palLabel(pal) { return pal.id === 'brand' ? 'Your brand' : ((byId(PALETTES, pal.id) || {}).label || pal.id); }
export function optLabel(group, id) { return (byId(OPT[group], id) || {}).label || id; }
