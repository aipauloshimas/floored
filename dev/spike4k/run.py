#!/usr/bin/env python3
"""Task 2 spike: does HyperFrames 0.9.22 render locally with no account, and which 4K method keeps text crisp?

  run.py WORK install       clean-profile `npm install --prefix WORK/renderer hyperframes@0.9.22` + first render (stdin closed)
  run.py WORK help          save `--help` texts and grep the installed package for telemetry/login words
  run.py WORK offline [V=x] re-render with the opt-out set behind a dead proxy, then with every non-loopback connection of the
                            node processes refused (and logged); a third run with telemetry on shows what it would contact
  run.py WORK prep4k        upscale assets/person.webm to 2160x3840 (lanczos, VP9 alpha, CRF 18); write comp_flag/zoom/scale
  run.py WORK cands [NAME]  render base1080, flag, zoom, scale (10M at 1080, 40M at 4K), wall times to renders/times.json
  run.py WORK measure       frames 24, 60, 110 (t = 1.0, 2.5, 4.6): geom (SSIM), crisp (Laplacian-variance ratio), sobel -> measure.json
  run.py WORK telemetry     `telemetry status` as is and with each opt-out set -> logs/telemetry-status.txt
  run.py WORK rr NAME [..]  one render of WORK/NAME with the clean profile (extra args pass through)
WORK is a folder OUTSIDE the repo holding the clean profile, the renderer, the copied composition and every render. Keep its
path SHORT (for example C:/Users/you/AppData/Local/Temp/fts4k): the Chrome the renderer downloads sits under
WORK/profile/home/.cache/..., and from a deep folder the render dies silently (exit 1, no message) on Windows' 260-character limit.
"""
import argparse, json, os, shutil, subprocess, sys, time
from pathlib import Path

HF = '0.9.22'
ATS = [1.0, 2.5, 4.6]
FPS = 24
SRC_COMP = Path(os.environ['FT_SPIKE_COMP']) if os.environ.get('FT_SPIKE_COMP') else None   # a finished export folder (index.html + assets/)
GEOM_MIN, CRISP_MIN = 0.97, 1.6
NPM = shutil.which('npm') or 'npm'


def clean_env(work, extra=None):
    """Env that points every user-profile location into WORK/profile, so nothing of your account state is seen."""
    p = work / 'profile'
    for d in ('home', 'appdata', 'localappdata', 'npmcache'):
        (p / d).mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(HOME=str(p / 'home'), USERPROFILE=str(p / 'home'), APPDATA=str(p / 'appdata'),
               LOCALAPPDATA=str(p / 'localappdata'), npm_config_cache=str(p / 'npmcache'),
               HOMEDRIVE=p.drive, HOMEPATH=str(p / 'home')[len(p.drive):], PYTHONUTF8='1')
    for k in ('XDG_CACHE_HOME', 'XDG_CONFIG_HOME', 'PUPPETEER_CACHE_DIR', 'PUPPETEER_EXECUTABLE_PATH',
              'DO_NOT_TRACK', 'HYPERFRAMES_NO_TELEMETRY', 'HYPERFRAMES_NO_UPDATE_CHECK', 'CI'):
        env.pop(k, None)
    env.update(extra or {})
    return env


def bin_path(work):
    return work / 'renderer' / 'node_modules' / '.bin' / ('hyperframes.cmd' if os.name == 'nt' else 'hyperframes')


def run(cmd, env, log, cwd=None, timeout=900):
    """Run with stdin closed and a timeout; the full output goes to `log`. Returns (exit code or None on timeout, seconds)."""
    t0 = time.time()
    try:
        r = subprocess.run([str(c) for c in cmd], env=env, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, encoding='utf-8', errors='replace', timeout=timeout)
        code, out, err = r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired as e:
        code, out, err = None, (e.stdout or b'').decode('utf-8', 'replace') if isinstance(e.stdout, bytes) else (e.stdout or ''), \
            (e.stderr or b'').decode('utf-8', 'replace') if isinstance(e.stderr, bytes) else (e.stderr or '')
    dt = time.time() - t0
    Path(log).write_text('$ %s\nexit=%s  wall=%.1fs\n--- stdout ---\n%s\n--- stderr ---\n%s\n' %
                         (' '.join(str(c) for c in cmd), code, dt, out, err), encoding='utf-8')
    return code, dt


def dir_size(p):
    n = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                n += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n


def mb(n):
    return '%.1f MB' % (n / 1e6)


def ensure_comp(work, name='comp'):
    d = work / name
    if not d.exists():
        if SRC_COMP is None or not (SRC_COMP / 'index.html').is_file():
            sys.exit('set FT_SPIKE_COMP to a finished export folder (index.html and assets/)')
        d.mkdir(parents=True)
        shutil.copy2(SRC_COMP / 'index.html', d / 'index.html')
        shutil.copytree(SRC_COMP / 'assets', d / 'assets')
    return d


def probe(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                        'stream=width,height,r_frame_rate,nb_read_frames,codec_name,bit_rate', '-of', 'json', str(path)],
                       capture_output=True, text=True)
    s = json.loads(r.stdout)['streams'][0]
    return s


def cmd_install(work, a):
    env = clean_env(work)
    (work / 'logs').mkdir(exist_ok=True)
    (work / 'renderer').mkdir(exist_ok=True)
    code, dt = run([NPM, 'install', '--prefix', work / 'renderer', 'hyperframes@' + HF], env, work / 'logs' / 'install.log')
    print('npm install exit', code, '%.0fs' % dt, 'renderer', mb(dir_size(work / 'renderer')),
          'npm cache', mb(dir_size(work / 'profile' / 'npmcache')))
    comp = ensure_comp(work)
    out = work / 'renders' / 'first.mp4'
    out.parent.mkdir(exist_ok=True)
    code, dt = run([bin_path(work), 'render', comp, '-o', out, '--fps', FPS, '--video-bitrate', '10M'], env,
                   work / 'logs' / 'first-render.log')
    print('first render exit', code, '%.0fs' % dt)
    if out.exists():
        print(probe(out))
    prof = work / 'profile'
    print('profile after: %s total; localappdata %s; home %s; appdata %s' % (
        mb(dir_size(prof)), mb(dir_size(prof / 'localappdata')), mb(dir_size(prof / 'home')), mb(dir_size(prof / 'appdata'))))


# ---------------------------------------------------------------------------------------------------- measurement
def luma(img):
    import numpy as np
    a = np.asarray(img.convert('RGB'), dtype=np.float64)
    return 0.299 * a[..., 0] + 0.587 * a[..., 1] + 0.114 * a[..., 2]


def _gauss(size=11, sigma=1.5):
    import numpy as np
    x = np.arange(size) - (size - 1) / 2
    g = np.exp(-x * x / (2 * sigma * sigma))
    return g / g.sum()


def _filt(a, k):
    """Separable 'valid' filter, numpy only."""
    import numpy as np
    n = len(k)
    h = sum(k[i] * a[:, i:a.shape[1] - n + 1 + i] for i in range(n))
    return sum(k[i] * h[i:h.shape[0] - n + 1 + i, :] for i in range(n))


def ssim(a, b):
    """Mean SSIM of two luma arrays (0..255), gaussian 11x11 sigma 1.5, K1 .01 K2 .03: the standard Wang et al. form."""
    k = _gauss()
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    ma, mb_ = _filt(a, k), _filt(b, k)
    saa = _filt(a * a, k) - ma * ma
    sbb = _filt(b * b, k) - mb_ * mb_
    sab = _filt(a * b, k) - ma * mb_
    m = ((2 * ma * mb_ + c1) * (2 * sab + c2)) / ((ma * ma + mb_ * mb_ + c1) * (saa + sbb + c2))
    return float(m.mean())


def gradmag(a):
    """Sobel gradient magnitude of a luma array (interior pixels)."""
    import numpy as np
    gx = (a[:-2, 2:] + 2 * a[1:-1, 2:] + a[2:, 2:]) - (a[:-2, :-2] + 2 * a[1:-1, :-2] + a[2:, :-2])
    gy = (a[2:, :-2] + 2 * a[2:, 1:-1] + a[2:, 2:]) - (a[:-2, :-2] + 2 * a[:-2, 1:-1] + a[:-2, 2:])
    return np.sqrt(gx * gx + gy * gy)


def grad(a):
    """Mean Sobel magnitude of luma (information only: the `sobel` column)."""
    return float(gradmag(a).mean())


def lapvar(a):
    """Variance of the 4-neighbour Laplacian: the gate measure (ruling of 2026-11-08)."""
    lap = 4 * a[1:-1, 1:-1] - a[:-2, 1:-1] - a[2:, 1:-1] - a[1:-1, :-2] - a[1:-1, 2:]
    return float(lap.var())


def frame_index(t):
    return int(round(t * FPS))


def extract(video, idxs, outdir, tag):
    """Pull frames by index with ffmpeg (select=eq(n,i)) as PNG."""
    outdir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for i in idxs:
        p = outdir / ('%s_f%03d.png' % (tag, i))
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-vf', r'select=eq(n\,%d)' % i, '-frames:v', '1',
                        str(p)], check=True, stdin=subprocess.DEVNULL)
        paths[i] = p
    return paths


def measure_pair(f4k, f1080, crops, tag):
    """geom and crisp as ruled on 2026-11-08: crisp = var(Laplacian(luma crop4k)) / var(Laplacian(luma lanczos2x(crop1080))).
    Everything else returned is information: the mean-Sobel ratio the plan first asked for (`sobel`), p99 of the Sobel
    magnitude, each statistic's ideal ceiling, and a blur / unsharp control on the 4K crop."""
    import numpy as np
    from PIL import Image, ImageFilter
    a4, a1 = Image.open(f4k).convert('RGB'), Image.open(f1080).convert('RGB')
    assert a4.size == (2160, 3840) and a1.size == (1080, 1920), (a4.size, a1.size)
    down = a4.resize((1080, 1920), Image.LANCZOS)
    down_box = a4.resize((1080, 1920), Image.BOX)
    geom = ssim(luma(down), luma(a1))
    geom_box = ssim(luma(down_box), luma(a1))
    x0, y0, x1, y1 = 100, 200, 980, 900
    c1 = a1.crop((x0, y0, x1, y1))
    c4 = a4.crop((2 * x0, 2 * y0, 2 * x1, 2 * y1))
    up = c1.resize(c4.size, Image.LANCZOS)
    stat = lambda im: dict(lap=lapvar(luma(im)), sobel=grad(luma(im)))
    s4, su = stat(c4), stat(up)
    crops.mkdir(parents=True, exist_ok=True)
    c4.save(crops / (tag + '_4k.png'))
    up.save(crops / (tag + '_1080up2x.png'))
    # ceiling (information only): the same 4K frame, box-downscaled to 1080 and lanczos-upscaled back. A renderer whose 4K
    # output is the ideal one for its own 1080 version cannot score higher than this on that statistic.
    si = stat(down_box.crop((x0, y0, x1, y1)).resize(c4.size, Image.LANCZOS))
    ctl = {}   # control: the 4K crop made softer (Gaussian) or harder (unsharp mask), scored against the same 1080 upscale
    for name, im in (('blur0.7', c4.filter(ImageFilter.GaussianBlur(0.7))), ('blur1.5', c4.filter(ImageFilter.GaussianBlur(1.5))),
                     ('blur2.0', c4.filter(ImageFilter.GaussianBlur(2.0))),
                     ('unsharp', c4.filter(ImageFilter.UnsharpMask(radius=1.5, percent=200, threshold=0)))):
        sv = stat(im)
        ctl[name] = dict(crisp=sv['lap'] / su['lap'], sobel=sv['sobel'] / su['sobel'])
    p4 = float(np.percentile(gradmag(luma(c4)), 99))
    pu = float(np.percentile(gradmag(luma(up)), 99))
    return dict(geom=geom, geom_box=geom_box, crisp=s4['lap'] / su['lap'], sobel=s4['sobel'] / su['sobel'],
                lap4k=s4['lap'], lap1080up=su['lap'], sobel4k=s4['sobel'], sobel1080up=su['sobel'], p99=p4 / pu,
                ceiling_crisp=s4['lap'] / si['lap'], ceiling_sobel=s4['sobel'] / si['sobel'], control=ctl)


def render(work, comp, out, extra=None, env_extra=None, log=None, timeout=1500):
    """One `hyperframes render` with the clean profile, stdin closed. Returns (exit code, seconds)."""
    env = clean_env(work, env_extra)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [bin_path(work), 'render', comp, '-o', out, '--fps', FPS, '--video-bitrate', '10M'] + list(extra or [])
    return run(cmd, env, log or work / 'logs' / (out.stem + '.log'), timeout=timeout)


def cmd_rr(work, a):
    """rr NAME [render args...]: render work/NAME to work/renders/NAME.mp4 (extra args pass through after --)."""
    name = a.rest[0]
    code, dt = render(work, work / name, work / 'renders' / (name + '.mp4'), a.rest[1:])
    out = work / 'renders' / (name + '.mp4')
    print(name, 'exit', code, '%.0fs' % dt, probe(out) if out.exists() else 'no output')


# ---------------------------------------------------------------------------------------------- help / telemetry grep
NET_PRELOAD = r"""
// logs (and with FT_NETBLOCK=1 refuses) every non-loopback connection a node process of the render makes
const net = require('net'), dns = require('dns'), fs = require('fs');
const logf = process.env.FT_NETLOG;
const isLocal = h => !h || /^(localhost|127\.|::1$|\[::1\]|0\.0\.0\.0|::ffff:127\.)/i.test(String(h));
function note(kind, h) { try { fs.appendFileSync(logf, kind + ' ' + h + ' pid=' + process.pid + '\n'); } catch (e) {} }
const origLookup = dns.lookup;
dns.lookup = function (host, opts, cb) {
  if (typeof opts === 'function') { cb = opts; opts = {}; }
  if (!isLocal(host)) { note('lookup', host); if (process.env.FT_NETBLOCK === '1') { const e = new Error('blocked ' + host); e.code = 'ENOTFOUND'; return process.nextTick(cb, e); } }
  return origLookup.call(dns, host, opts, cb);
};
const origConnect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...a) {
  const o = a[0];
  const host = o && typeof o === 'object' ? o.host : (typeof a[1] === 'string' ? a[1] : undefined);
  if (o && typeof o === 'object' && o.path) return origConnect.apply(this, a);
  if (host && !isLocal(host)) { note('connect', host); if (process.env.FT_NETBLOCK === '1') { process.nextTick(() => this.destroy(Object.assign(new Error('blocked ' + host), { code: 'ECONNREFUSED' }))); return this; } }
  return origConnect.apply(this, a);
};
"""


def cmd_help(work, a):
    env = clean_env(work)
    for name, args in (('render-help', ['render', '--help']), ('telemetry-help', ['telemetry', '--help']),
                       ('help', ['--help'])):
        code, _ = run([bin_path(work)] + args, env, work / 'logs' / (name + '.txt'))
        print(name, 'exit', code)
    print(subprocess.run([str(bin_path(work)), 'telemetry', 'status'], env=env, stdin=subprocess.DEVNULL,
                         capture_output=True, text=True).stdout)
    import re
    pat = re.compile(r'DO_NOT_TRACK|TELEMETRY|telemetry|login|usage', re.I)
    pkg = work / 'renderer' / 'node_modules' / 'hyperframes'
    hits, files = {}, 0
    for f in pkg.rglob('*'):
        if f.is_file() and f.suffix in ('.js', '.mjs', '.cjs', '.json', '.md', '.ts'):
            files += 1
            for i, line in enumerate(f.read_text(encoding='utf-8', errors='replace').splitlines()):
                if pat.search(line):
                    hits.setdefault(str(f.relative_to(pkg)), []).append((i + 1, line.strip()[:240]))
    out = work / 'logs' / 'grep-telemetry.txt'
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write('searched %d files under %s\n' % (files, pkg))
        for f, ls in sorted(hits.items()):
            fh.write('\n== %s (%d lines)\n' % (f, len(ls)))
            for n, l in ls[:60]:
                fh.write('%d: %s\n' % (n, l))
    print('grep: %d files with hits, written to %s' % (len(hits), out))


def cmd_offline(work, a):
    """Re-render the 1080 composition with the opt-out set (a) behind a dead proxy, (b) with every non-loopback connection of
    the node processes refused by a preload (and logged); (c) for contrast, telemetry on, connections only logged.
    Usage: offline [VAR=value ...]  (default: HYPERFRAMES_NO_TELEMETRY=1 DO_NOT_TRACK=1 HYPERFRAMES_NO_UPDATE_CHECK=1)."""
    optouts = dict(x.split('=', 1) for x in a.rest) or {'HYPERFRAMES_NO_TELEMETRY': '1', 'DO_NOT_TRACK': '1',
                                                        'HYPERFRAMES_NO_UPDATE_CHECK': '1'}
    comp = ensure_comp(work)
    pre = work / 'netguard.js'
    pre.write_text(NET_PRELOAD, encoding='utf-8')
    proxy = {'HTTP_PROXY': 'http://127.0.0.1:9', 'HTTPS_PROXY': 'http://127.0.0.1:9',
             'http_proxy': 'http://127.0.0.1:9', 'https_proxy': 'http://127.0.0.1:9'}

    def guard(tag, block):
        return {'NODE_OPTIONS': '--require=' + str(pre).replace('\\', '/'), 'FT_NETLOG': str(work / 'logs' / ('net-%s.txt' % tag)),
                'FT_NETBLOCK': '1' if block else '0'}
    runs = [('offline-proxy', dict(proxy, **optouts)),
            ('offline-blocked', dict(proxy, **optouts, **guard('offline-blocked', True))),
            ('telemetry-on-logged', guard('telemetry-on-logged', False))]
    for tag, extra in runs:
        (work / 'logs' / ('net-%s.txt' % tag)).unlink(missing_ok=True)
        out = work / 'renders' / (tag + '.mp4')
        code, dt = render(work, comp, out, env_extra=extra, log=work / 'logs' / (tag + '.log'))
        net = work / 'logs' / ('net-%s.txt' % tag)
        seen = sorted(set(net.read_text().split('\n'))) if net.exists() else []
        print(tag, 'exit', code, '%.0fs' % dt, probe(out) if out.exists() else 'no output', '\n  outbound attempts:',
              [x for x in seen if x] or 'none logged')


# ------------------------------------------------------------------------------------------------- 4K candidates
def cmd_prep4k(work, a):
    comp = ensure_comp(work)
    src = comp / 'assets' / 'person.webm'
    dst = work / 'person4k.webm'
    if not dst.exists():
        t0 = time.time()
        subprocess.run(['ffmpeg', '-v', 'error', '-y', '-c:v', 'libvpx-vp9', '-i', str(src), '-vf', 'scale=2160:3840:flags=lanczos,format=yuva420p',
                        '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-crf', '18', '-b:v', '0', '-row-mt', '1', '-cpu-used', '2',
                        '-auto-alt-ref', '0', str(dst)], check=True, stdin=subprocess.DEVNULL)
        print('person4k.webm', mb(dst.stat().st_size), '%.0fs' % (time.time() - t0))
    html = (comp / 'index.html').read_text(encoding='utf-8')
    root_open = ('<div id="root" class="ft-root" data-composition-id="main" data-start="0" data-width="1080" '
                 'data-height="1920" data-duration="5.031" data-fps="24">')
    assert root_open in html and '</svg>\n</div>\n<script>' in html and "document.getElementById('root')" in html
    big = html.replace('width=1080, height=1920', 'width=2160, height=3840')
    variants = {}
    variants['flag'] = html                     # composition unchanged: Chrome renders at DPR 2 (--resolution portrait-4k)
    z = big.replace('data-width="1080" data-height="1920"', 'data-width="2160" data-height="3840"')
    variants['zoom'] = z.replace('</style>', '  .ft-root { zoom: 2; }\n</style>', 1)
    s = big.replace(root_open, '<div id="root" data-composition-id="main" data-start="0" data-width="2160" data-height="3840" '
                    'data-duration="5.031" data-fps="24" '
                    'style="position:relative;width:2160px;height:3840px;overflow:hidden;background:#000">\n'
                    '<div id="ftroot" class="ft-root" style="transform:scale(2);transform-origin:0 0">')
    s = s.replace('</svg>\n</div>\n<script>', '</svg>\n</div></div>\n<script>').replace("document.getElementById('root')", "document.getElementById('ftroot')")
    variants['scale'] = s
    for name, h in variants.items():
        d = work / ('comp_' + name)
        if d.exists():
            shutil.rmtree(d)
        d.mkdir()
        shutil.copytree(comp / 'assets', d / 'assets')
        shutil.copy2(dst, d / 'assets' / 'person.webm')
        (d / 'index.html').write_text(h, encoding='utf-8')
    print('variants written:', ', '.join('comp_' + n for n in variants))


CANDS = {   # name -> (composition folder, extra render args, video bitrate: 10M at 1080, 40M at 4K = same bits per pixel)
    'base1080': ('comp', [], '10M'),
    'flag': ('comp_flag', ['--resolution', 'portrait-4k'], '40M'),
    'zoom': ('comp_zoom', [], '40M'),
    'scale': ('comp_scale', [], '40M'),
}


def cmd_cands(work, a):
    tj = work / 'renders' / 'times.json'
    times = json.loads(tj.read_text()) if tj.exists() else {}
    for name in (a.rest or list(CANDS)):
        d, extra, br = CANDS[name]
        out = work / 'renders' / (name + '.mp4')
        out.parent.mkdir(exist_ok=True)
        cmd = [bin_path(work), 'render', work / d, '-o', out, '--fps', FPS, '--video-bitrate', br] + extra
        code, dt = run(cmd, clean_env(work), work / 'logs' / ('cand-%s.log' % name), timeout=2400)
        info = probe(out) if out.exists() else None
        times[name] = dict(exit=code, wall_s=round(dt, 1), probe=info, size=out.stat().st_size if out.exists() else None)
        print(name, 'exit', code, '%.0fs' % dt, info, flush=True)
        tj.write_text(json.dumps(times, indent=1))


def cmd_measure(work, a):
    """Frames 24, 60, 110 are re-extracted from the existing renders (no re-render) and everything is recomputed."""
    from PIL import Image
    idxs = [frame_index(t) for t in ATS]
    fr = work / 'frames'
    ref = extract(work / 'renders' / 'base1080.mp4', idxs, fr, 'base1080')
    res = {}
    for name in CANDS:
        if name == 'base1080' or not (work / 'renders' / (name + '.mp4')).exists():
            continue
        fx = extract(work / 'renders' / (name + '.mp4'), idxs, fr, name)
        for t, i in zip(ATS, idxs):
            tag = '%s_t%.1f' % (name, t)
            res[tag] = measure_pair(fx[i], ref[i], work / 'crops', tag)
            res[tag]['frame'] = i
    for t, i in zip(ATS, idxs):
        Image.open(ref[i]).convert('RGB').crop((100, 200, 980, 900)).save(work / 'crops' / ('base1080_t%.1f_1080.png' % t))
    (work / 'measure.json').write_text(json.dumps(res, indent=1))
    print('gate: geom >= %.2f and crisp (Laplacian-variance ratio) >= %.1f at all three instants.' % (GEOM_MIN, CRISP_MIN))
    print('info: sobel = mean-Sobel ratio, p99 = p99 Sobel ratio, ceil_c / ceil_s = ideal ceiling of crisp / sobel')
    print('%-12s %-5s %8s %8s %8s %8s %6s %7s %7s  pass' % ('candidate', 'frame', 'geom', 'geom_box', 'crisp', 'sobel', 'p99',
                                                          'ceil_c', 'ceil_s'))
    verdict = {}
    for tag, r in res.items():
        ok = r['geom'] >= GEOM_MIN and r['crisp'] >= CRISP_MIN
        verdict.setdefault(tag.split('_t')[0], []).append(ok)
        print('%-12s %-5d %8.4f %8.4f %8.3f %8.3f %6.2f %7.3f %7.3f  %s' % (
            tag, r['frame'], r['geom'], r['geom_box'], r['crisp'], r['sobel'], r['p99'], r['ceiling_crisp'], r['ceiling_sobel'],
            'PASS' if ok else 'fail'))
    print('control on the 4K crop, crisp/sobel against the 1080 upscale (blur = Gaussian sigma in px, unsharp = radius 1.5, 200%):')
    for tag, r in res.items():
        print('  %-12s ' % tag + '  '.join('%s %.2f/%.2f' % (k, v['crisp'], v['sobel']) for k, v in r['control'].items()))
    for n, v in verdict.items():
        print(n, 'PASSES all three instants' if all(v) and len(v) == len(ATS) else 'fails')


def cmd_telemetry(work, a):
    """`telemetry status` in the clean profile: as is, then with each opt-out set. Saved to logs/telemetry-status.txt."""
    out = []
    for label, extra in (('default', {}), ('HYPERFRAMES_NO_TELEMETRY=1', {'HYPERFRAMES_NO_TELEMETRY': '1'}),
                         ('DO_NOT_TRACK=1', {'DO_NOT_TRACK': '1'})):
        r = subprocess.run([str(bin_path(work)), 'telemetry', 'status'], env=clean_env(work, extra), stdin=subprocess.DEVNULL,
                           capture_output=True, text=True)
        body = chr(10).join(l.rstrip() for l in r.stdout.splitlines() if l.strip())
        out.append('## %s (exit %s)' % (label, r.returncode) + chr(10) + body)
    text = (chr(10) * 2).join(out)
    (work / 'logs').mkdir(parents=True, exist_ok=True)
    (work / 'logs' / 'telemetry-status.txt').write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('work')
    ap.add_argument('cmd')
    ap.add_argument('rest', nargs='*')
    a, unknown = ap.parse_known_args()
    a.rest += unknown
    work = Path(a.work).resolve()
    work.mkdir(parents=True, exist_ok=True)
    globals()['cmd_' + a.cmd](work, a)
