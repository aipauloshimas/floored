import { h, ico } from './util.js';
import { REACH } from './copy.js';

/* Can the page reach the floored server? One answer for every request: api() and the upload report here, nobody checks on their own.
   Only a request that never got an answer (a network failure) marks the server gone; any HTTP answer, even a 4xx or 5xx, means it is there.
   While it is gone a fixed banner says so (it stays until the server answers, it is not a toast) and the page asks every 3 s whether it is back
   (a light GET). When it is back the banner goes and the listeners run: the store sends the settings that were waiting, the screens read again. */
var PROBE_MS = 3000, PROBE_PATH = '/api/prefs';
var gone = false, probeTimer = 0, listeners = [], bannerEl = null;

export function isGone() { return gone; }
/* fn(true) when the server stops answering, fn(false) when it is back; returns the function that stops listening */
export function onReach(fn) {
  listeners.push(fn);
  return function () { var i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1); };
}
function say(g) { listeners.slice().forEach(function (fn) { try { fn(g); } catch (e) { /* a listener must not stop the others */ } }); }

function banner() {
  if (bannerEl) return bannerEl;
  bannerEl = h('div', { class: 'ft-banner', role: 'status', 'aria-live': 'polite' });
  document.body.insertBefore(bannerEl, document.body.firstChild);
  return bannerEl;
}
function sizeVar() { document.documentElement.style.setProperty('--banner-h', gone && bannerEl ? bannerEl.offsetHeight + 'px' : '0px'); }
window.addEventListener('resize', function () { if (gone) sizeVar(); });

function probe() {
  probeTimer = 0;
  if (!gone) return;
  fetch(PROBE_PATH, { cache: 'no-store' }).then(function () { markReached(); }, function () { probeTimer = setTimeout(probe, PROBE_MS); });
}
export function markGone() {
  if (gone) return;
  gone = true;
  var b = banner();
  b.textContent = '';
  b.appendChild(ico('alert', 'ft-banner-ico', 18));
  b.appendChild(h('span', { text: REACH.banner }));
  sizeVar();
  clearTimeout(probeTimer);
  probeTimer = setTimeout(probe, PROBE_MS);
  say(true);
}
export function markReached() {
  if (!gone) return;
  gone = false;
  clearTimeout(probeTimer); probeTimer = 0;
  if (bannerEl) bannerEl.textContent = '';
  sizeVar();
  say(false);
}
