import { h, ssGet } from './util.js';

/* ====================================================================== api */
export function api(path, opts) {
  return fetch(path, opts).then(function (r) {
    return r.text().then(function (txt) {
      var body = null;
      try { body = txt ? JSON.parse(txt) : null; } catch (e) { body = null; }
      if (!r.ok) {
        var err = new Error((body && body.error) || ('The server answered ' + r.status + '.'));
        err.status = r.status;
        throw err;
      }
      return body;
    });
  }, function () {
    var e = new Error('Can’t reach the floored server. Is it still running?');
    e.network = true;
    throw e;
  });
}
export function postJSON(path, data) {
  return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
}
export function takeFile(id, name) { return '/takes/' + encodeURIComponent(id) + '/' + name; }

export function uploadFile(file, onProgress) {
  return new Promise(function (resolve, reject) {
    var x = new XMLHttpRequest();
    x.open('POST', '/api/takes');
    x.setRequestHeader('X-Filename', encodeURIComponent(file.name));
    x.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
    x.upload.onprogress = function (e) { if (e.lengthComputable) onProgress(e.loaded / e.total); };
    x.onload = function () {
      var body = null;
      try { body = JSON.parse(x.responseText); } catch (e) { body = null; }
      if (x.status >= 200 && x.status < 300 && body && body.id) resolve(body);
      else reject(new Error((body && body.error) || ('The upload did not work (' + x.status + ').')));
    };
    x.onerror = function () { reject(new Error('Can’t reach the floored server. Is it still running?')); };
    x.send(file);
  });
}

/* ====================================================================== poster / thumbnails */
export function capturePoster(file) {
  return new Promise(function (resolve) {
    var url, v, done = false;
    function fin(data) {
      if (done) return;
      done = true;
      try { URL.revokeObjectURL(url); } catch (e) { /* ignore */ }
      resolve(data || null);
    }
    try {
      url = URL.createObjectURL(file);
      v = document.createElement('video');
      v.muted = true; v.playsInline = true; v.preload = 'auto'; v.src = url;
      v.addEventListener('loadeddata', function () { try { v.currentTime = Math.min(0.25, (v.duration || 1) / 4); } catch (e) { fin(null); } });
      v.addEventListener('seeked', function () {
        try {
          var c = document.createElement('canvas'), w = 180, hgt = 320;
          c.width = w; c.height = hgt;
          var vw = v.videoWidth || w, vh = v.videoHeight || hgt, s = Math.max(w / vw, hgt / vh);
          var cx = c.getContext('2d');
          cx.drawImage(v, (w - vw * s) / 2, (hgt - vh * s) / 2, vw * s, vh * s);
          fin(c.toDataURL('image/jpeg', 0.8));
        } catch (e) { fin(null); }
      });
      v.addEventListener('error', function () { fin(null); });
      setTimeout(function () { fin(null); }, 4500);
    } catch (e) { fin(null); }
  });
}
export function posterFor(id) { return ssGet('ft:poster:' + id) || takeFile(id, 'poster.jpg'); }

/* helper: poster image that quietly hides when the file is not there yet */
export function posterImg(id, cls) {
  var img = h('img', { class: cls || '', alt: '', loading: 'lazy', src: posterFor(id) });
  img.addEventListener('error', function () { img.style.visibility = 'hidden'; });
  return img;
}
