import { clamp, clone, f1, noop } from './util.js';
import { takeFile } from './api.js';
import { DEBUG } from './store.js';

/* ====================================================================== sound effects (WebAudio, synthesised) */
var AC = null, noiseBuf = null;
function audioCtx() {
  if (!AC) {
    var C = window.AudioContext || window.webkitAudioContext;
    if (!C) return null;
    try { AC = new C(); } catch (e) { return null; }
  }
  if (AC.state === 'suspended') AC.resume().catch(noop);
  return AC;
}
function noiseBuffer(c) {
  if (!noiseBuf || noiseBuf.sampleRate !== c.sampleRate) {
    var n = Math.floor(c.sampleRate * 1.2), seed = 1234567, i;
    noiseBuf = c.createBuffer(1, n, c.sampleRate);
    var d = noiseBuf.getChannelData(0);
    for (i = 0; i < n; i++) { seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0; d[i] = (seed / 4294967296) * 2 - 1; }
  }
  return noiseBuf;
}
function noiseSrc(c, w, dur) { var s = c.createBufferSource(); s.buffer = noiseBuffer(c); s.loop = true; s.start(w); s.stop(w + dur + 0.03); return s; }
function oscSrc(c, type, w, dur, f0, f1) {
  var o = c.createOscillator();
  o.type = type;
  o.frequency.setValueAtTime(f0, w);
  if (f1) o.frequency.exponentialRampToValueAtTime(f1, w + dur);
  o.start(w); o.stop(w + dur + 0.03);
  return o;
}
function envGain(c, w, attack, dur, peak) {
  var g = c.createGain();
  g.gain.setValueAtTime(0.0001, w);
  g.gain.linearRampToValueAtTime(Math.max(peak, 0.0002), w + attack);
  g.gain.exponentialRampToValueAtTime(0.0001, w + dur);
  return g;
}
function filt(c, type, f0, f1, w, dur, q) {
  var f = c.createBiquadFilter();
  f.type = type; f.Q.value = q || 1;
  f.frequency.setValueAtTime(f0, w);
  if (f1) f.frequency.exponentialRampToValueAtTime(f1, w + dur);
  return f;
}
function clickAt(c, w, amp, out) { noiseSrc(c, w, 0.004).connect(envGain(c, w, 0.0006, 0.004, amp)).connect(out); }
var SYNTH = {
  whoosh: function (c, w, g, out) { noiseSrc(c, w, 0.3).connect(filt(c, 'bandpass', 400, 2400, w, 0.3, 1.1)).connect(envGain(c, w, 0.09, 0.3, 0.55 * g)).connect(out); },
  land: function (c, w, g, out) { oscSrc(c, 'sine', w, 0.18, 70, 46).connect(envGain(c, w, 0.005, 0.18, 0.9 * g)).connect(out); clickAt(c, w, 0.3 * g, out); },
  pop: function (c, w, g, out) { oscSrc(c, 'sine', w, 0.08, 600, 300).connect(envGain(c, w, 0.004, 0.08, 0.5 * g)).connect(out); },
  tick: function (c, w, g, out) { clickAt(c, w, 0.45 * g, out); },
  swarm: function (c, w, g, out) { noiseSrc(c, w, 0.7).connect(filt(c, 'bandpass', 300, 3200, w, 0.7, 0.8)).connect(envGain(c, w, 0.22, 0.7, 0.4 * g)).connect(out); },
  riser: function (c, w, g, out) {
    noiseSrc(c, w, 0.6).connect(filt(c, 'highpass', 500, 5000, w, 0.6, 0.7)).connect(envGain(c, w, 0.5, 0.62, 0.35 * g)).connect(out);
    oscSrc(c, 'sine', w, 0.6, 220, 1400).connect(envGain(c, w, 0.5, 0.62, 0.22 * g)).connect(out);
  },
  hit: function (c, w, g, out) {
    oscSrc(c, 'sine', w, 0.35, 50, 34).connect(envGain(c, w, 0.004, 0.35, 0.95 * g)).connect(out);
    noiseSrc(c, w, 0.12).connect(filt(c, 'lowpass', 900, 0, w, 0.12, 0.7)).connect(envGain(c, w, 0.002, 0.12, 0.5 * g)).connect(out);
  },
  boom: function (c, w, g, out) { oscSrc(c, 'sine', w, 0.8, 45, 32).connect(envGain(c, w, 0.01, 0.8, 0.9 * g)).connect(out); }
};
/* schedule every event at or after fromT; returns a cancel function */
function scheduleSfx(events, fromT, vol) {
  var c = audioCtx();
  if (!c) return null;
  var bus = c.createGain();
  bus.gain.value = vol;
  bus.connect(c.destination);
  var base = c.currentTime + 0.03;
  (events || []).forEach(function (e) {
    if (e.t < fromT - 0.01) return;
    var fn = SYNTH[e.kind];
    if (!fn) return;
    try { fn(c, base + Math.max(0, e.t - fromT), e.gain == null ? 1 : e.gain, bus); } catch (x) { /* one bad sound must not stop the rest */ }
  });
  return function cancel() {
    try {
      bus.gain.cancelScheduledValues(0);
      bus.gain.setValueAtTime(0, c.currentTime);
      setTimeout(function () { try { bus.disconnect(); } catch (e) { /* ignore */ } }, 120);
    } catch (e) { /* ignore */ }
  };
}

/* ====================================================================== the live preview */
var SKELETON =
  '<div class="ft-world"><div class="ft-cam"><div class="ft-floor"><div class="ft-tex"></div><div class="ft-para"></div><div class="ft-ao"></div>' +
  '<div class="ft-sw"><video class="ft-sv" muted playsinline preload="auto"></video></div></div></div>' +
  '<div class="ft-pw"><video class="ft-pv" muted playsinline preload="auto"></video></div></div>' +
  '<div class="ft-vig"></div><canvas class="ft-grain" width="540" height="960"></canvas><div class="ft-flash"></div>' +
  '<svg class="ft-defs" width="0" height="0" style="position:absolute"><defs></defs></svg>';

export function createPreview(host, take, startSettings, hooks) {
  hooks = hooks || {};
  var S = clone(startSettings);
  var useEngine = !!(window.Floored && typeof window.Floored.create === 'function');
  var root = document.createElement('div');
  root.className = useEngine ? 'ft-root' : 'fb-root';
  root.style.cssText = 'position:absolute;left:0;top:0;width:1080px;height:1920px;transform-origin:0 0;';
  if (useEngine) {
    root.innerHTML = SKELETON;
  } else {
    /* fallback while the engine is missing: floor colour + the person with the spike's pose (S 0.62, ax 545, ay 1150) */
    var k = 0.62 * (take.k0 || 0.45), fx = take.feet ? take.feet.x : take.w / 2, fy = take.feet ? take.feet.y : take.h * 0.85;
    root.style.background = S.palette.floor;
    root.innerHTML = '<div class="fb-pw" style="position:absolute;left:0;top:0;transform-origin:0 0;width:' + take.w + 'px;height:' + take.h +
      'px;transform:translate(' + (545 - fx * k).toFixed(2) + 'px,' + (1150 - fy * k).toFixed(2) + 'px) scale(' + k.toFixed(4) +
      ')"><video class="ft-pv" muted playsinline preload="auto" style="display:block;width:100%;height:100%"></video></div>';
  }
  host.appendChild(root);
  var pv = root.querySelector('.ft-pv');
  var sv = root.querySelector('.ft-sv');
  var au = null, engine = null;
  var urls = [];
  var loaded = false, disposed = false, raf = 0;
  var playing = false, holdUntil = 0, looping = true, soundOn = false, scrubbing = false, wasPlaying = false;
  var needsPaint = true, curT = 0, sfxCancel = null, lastErr = '';
  var busy = false, pending = null, wantRestart = false;
  var api_ = { kind: useEngine ? 'engine' : 'fallback' };

  function dur() { return take.dur || (engine && engine.duration) || 1; }
  function fps() { return take.fps || 24; }
  function report(e) {
    var m = (e && e.message) || String(e);
    if (m !== lastErr) {
      lastErr = m;
      DEBUG.log.push('preview: ' + m);
      if (window.console) console.warn('[preview]', e);
      if (hooks.onError) hooks.onError(e);
    }
  }
  function paintAt(t) { if (!engine) return; try { engine.paint(t); } catch (e) { report(e); } }

  function blobUrl(url, type) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error('Could not load ' + url + ' (' + r.status + ')');
      return r.arrayBuffer();
    }).then(function (ab) {
      var u = URL.createObjectURL(new Blob([ab], { type: type }));
      urls.push(u);
      return u;
    });
  }
  function whenReady(v) {
    return new Promise(function (res) {
      if (v.readyState >= 2) return res();
      var done = false;
      function fin() { if (done) return; done = true; v.removeEventListener('loadeddata', fin); v.removeEventListener('error', fin); res(); }
      v.addEventListener('loadeddata', fin);
      v.addEventListener('error', fin);
      setTimeout(fin, 12000);
    });
  }

  function applyAudio() {
    if (!au) return;
    au.muted = !(soundOn && S.sound.voice);
    if (playing && !au.muted && au.paused) au.play().catch(noop);
  }
  function cancelSfx() { if (sfxCancel) { sfxCancel(); sfxCancel = null; } }
  function rescheduleSfx(t) {
    cancelSfx();
    if (soundOn && S.sound.sfx && engine && playing) sfxCancel = scheduleSfx(engine.events(), t, 0.5);
  }
  function seekMedia(t) {
    try { pv.currentTime = t; } catch (e) { /* not ready yet */ }
    if (sv) { try { sv.currentTime = t; } catch (e) { /* ignore */ } }
    if (au) { try { au.currentTime = t; } catch (e) { /* ignore */ } }
  }
  function playMedia() {
    pv.play().catch(noop);
    if (sv) sv.play().catch(noop);
    if (au) { applyAudio(); au.play().catch(noop); }
  }
  function pauseMedia() { pv.pause(); if (sv) sv.pause(); if (au) au.pause(); }

  function startFrom(t) {
    t = clamp(t, 0, dur() - 0.002);
    curT = t;
    holdUntil = 0;
    playing = true;
    seekMedia(t);
    playMedia();
    rescheduleSfx(t);
    needsPaint = true;
    if (hooks.onPlayState) hooks.onPlayState(true);
  }
  function pause() {
    var was = playing;
    playing = false; holdUntil = 0;
    pauseMedia();
    cancelSfx();
    needsPaint = true;
    if (was && hooks.onPlayState) hooks.onPlayState(false);
  }

  function frame(now) {
    raf = requestAnimationFrame(frame);
    if (disposed || !loaded) return;
    if (holdUntil) {
      curT = dur();
      if (needsPaint) { needsPaint = false; paintAt(curT); if (hooks.onTime) hooks.onTime(curT); }
      if (now >= holdUntil) {
        holdUntil = 0;
        if (looping) startFrom(0);
        else { playing = false; pauseMedia(); if (hooks.onPlayState) hooks.onPlayState(false); }
      }
      return;
    }
    if (playing) {
      var t = pv.currentTime;
      if (pv.ended || t >= dur() - 0.045) {
        holdUntil = now + 700;
        curT = dur();
        if (sv) sv.pause();
        if (au) au.pause();
        paintAt(curT);
        if (hooks.onTime) hooks.onTime(curT);
        return;
      }
      curT = t;
      if (sv) {
        if (!sv.seeking && Math.abs(sv.currentTime - t) > 0.05) sv.currentTime = t;
        if (sv.paused && !sv.ended) sv.play().catch(noop);
      }
      if (au) {
        if (!au.seeking && Math.abs(au.currentTime - t) > 0.08) au.currentTime = t;
        if (au.paused && !au.ended && !au.muted) au.play().catch(noop);
      }
      paintAt(t);
      if (hooks.onTime) hooks.onTime(t);
    } else if (needsPaint) {
      needsPaint = false;
      paintAt(curT);
      if (hooks.onTime) hooks.onTime(curT);
    }
  }

  function runSet() {
    busy = true;
    var s = pending;
    pending = null;
    Promise.resolve().then(function () { return engine.set(s); }).catch(report).then(function () {
      if (disposed) return;
      if (pending) return runSet();
      busy = false;
      var rs = wantRestart;
      wantRestart = false;
      if (rs) startFrom(0); else needsPaint = true;
    });
  }

  /* ---- public api */
  api_.load = function () {
    // the files the take names: a 4K take previews from its smaller copy; a take saved before `files` existed uses the usual names
    var f = take.files || {};
    var audioName = f.audio !== undefined ? f.audio : (take.hasAudio ? 'audio.m4a' : null);
    var jobs = [blobUrl(takeFile(take.id, f.preview || f.person || 'person.webm'), 'video/webm')];
    jobs.push(sv ? blobUrl(takeFile(take.id, f.shadow || 'shadow.webm'), 'video/webm').catch(function () { return null; }) : Promise.resolve(null));
    jobs.push(audioName ? blobUrl(takeFile(take.id, audioName), 'audio/mp4').catch(function () { return null; }) : Promise.resolve(null));
    return Promise.all(jobs).then(function (u) {
      if (disposed) return null;
      pv.src = u[0];
      if (sv && u[1]) sv.src = u[1];
      if (u[2]) { au = new Audio(); au.preload = 'auto'; au.muted = true; au.src = u[2]; }
      return Promise.all([whenReady(pv), sv && u[1] ? whenReady(sv) : null]);
    }).then(function () {
      if (disposed || !useEngine) return null;
      return window.Floored.create(root, take, clone(S), { mode: 'live', fontsBase: '/engine/fonts/' }).then(function (e) { engine = e; });
    }).then(function () {
      if (disposed) return;
      loaded = true;
      needsPaint = true;
      paintAt(0);
      if (hooks.onTime) hooks.onTime(0);
      raf = requestAnimationFrame(frame);
      if (pending && engine && !busy) runSet();   /* settings changed while the take was loading */
    });
  };
  api_.fit = function (W, H) { root.style.transform = 'scale(' + (H / 1920) + ')'; };
  api_.apply = function (next, restart) {
    var prev = S;
    S = clone(next);
    if (!useEngine) {
      root.style.background = S.palette.floor;
      if (restart && loaded) startFrom(0);
    } else {
      pending = clone(next);
      wantRestart = wantRestart || !!restart;
      if (engine && !busy) runSet();
    }
    if (prev.sound.voice !== S.sound.voice || prev.sound.sfx !== S.sound.sfx) { applyAudio(); rescheduleSfx(curT); }
  };
  api_.play = function () { if (loaded) startFrom(curT >= dur() - 0.05 ? 0 : curT); };
  api_.pause = pause;
  api_.toggle = function () { if (!loaded) return; if (playing) pause(); else api_.play(); };
  api_.restart = function () { if (loaded) startFrom(0); };
  api_.seek = function (t) {
    if (!loaded) return;
    curT = clamp(t, 0, dur());
    seekMedia(Math.min(curT, dur() - 0.002));
    needsPaint = true;
    holdUntil = 0;
    if (playing) { rescheduleSfx(curT); } else if (hooks.onTime) hooks.onTime(curT);
  };
  api_.step = function (dir) {
    if (!loaded) return;
    if (playing) pause();
    var n = Math.round(curT * fps()) + dir;
    api_.seek(clamp(n / fps(), 0, Math.max(0, dur() - 1 / fps())));
  };
  api_.scrubStart = function () { if (!loaded) return; scrubbing = true; wasPlaying = playing; if (playing) { playing = false; holdUntil = 0; pauseMedia(); cancelSfx(); } };
  api_.scrubTo = function (t) { if (!loaded) return; curT = clamp(t, 0, dur()); seekMedia(Math.min(curT, dur() - 0.002)); needsPaint = true; if (hooks.onTime) hooks.onTime(curT); };
  api_.scrubEnd = function () { if (!scrubbing) return; scrubbing = false; if (wasPlaying) startFrom(curT >= dur() - 0.05 ? 0 : curT); wasPlaying = false; };
  api_.setLoop = function (b) { looping = !!b; };
  api_.setSound = function (on) { soundOn = !!on; if (soundOn) audioCtx(); applyAudio(); rescheduleSfx(curT); };
  api_.isPlaying = function () { return playing; };
  api_.time = function () { return curT; };
  api_.duration = dur;
  api_.events = function () { try { return engine ? engine.events() : []; } catch (e) { return []; } };
  api_.engine = function () { return engine; };
  api_.dispose = function () {
    disposed = true;
    cancelAnimationFrame(raf);
    pauseMedia(); cancelSfx();
    try { pv.removeAttribute('src'); pv.load(); } catch (e) { /* ignore */ }
    if (host.contains(root)) host.removeChild(root);
    urls.forEach(function (u) { try { URL.revokeObjectURL(u); } catch (e) { /* ignore */ } });
  };
  return api_;
}
