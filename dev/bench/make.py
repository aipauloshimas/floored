#!/usr/bin/env python3
"""floored bench: fill engine/composition.html into bench/<name>/, check it, snapshot it with HyperFrames and tile
the frames into a labelled contact sheet.

  python make.py <lookId> [--name N] [--phrase P] [--hero H] [--small S] [--source speech|typed|suggested]
                 [--set key=value ...] [--at 0.5,1.6,3.0,4.9] [--guide] [--zoom] [--check] [--no-snap] [--sheet PATH]
  python make.py --sheets looks|fonts|entrances|endings|all
  python make.py --golden DIR                      write the visual-regression goldens (6 looks x 3 instants, 360x640 PNG)
  python make.py --compare DIR [--min-ssim 0.985]  render them again, exit 1 listing every image under the SSIM bar

--set takes top-level settings (font=geo, entrance=wipe, camera=still, ending=cut, layout=giant, pace=speech,
palette=<palette id>) and fx flags (fx.blur=false). The default text is the sample take's phrase:
"Here's how you create this awesome effect for free", hero FREE, small IN CLAUDE CODE, source speech.
--guide draws two 3 px lines on the floor plane through the cap top and the baseline of the wall row c1 (para y -150,
cap size 360), so cap tops can be judged against them for every font. --zoom crops the snapshot around that row.
"""
import argparse, json, math, os, shutil, subprocess, sys, tempfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1] / 'plugin' / 'skills' / 'floored' / 'app'
ENGINE = APP / 'web' / 'engine'
TAKE_DIR = APP / 'sample'
PHRASE = "Here's how you create this awesome effect for free"
LOOKS = ['original', 'noir', 'editorial', 'terminal', 'loud', 'sketch']
FONTS = ['condensed', 'serif', 'geo', 'mono', 'stencil', 'hand']
ENTRANCES = ['slide', 'drop', 'rise', 'type', 'pop', 'wipe']
ENDINGS = ['cut', 'exit', 'dive', 'sink']
ENGINE_FILES = ['data.js', 'metrics.js', 'layout.js', 'engine.js', 'engine.css', 'gsap.min.js']
NPX = shutil.which('npx') or 'npx'
HYPERFRAMES = 'hyperframes@0.9.22'      # pinned, same as ft.export
ROOT = HERE                              # where build() puts the folders it fills (a temp folder for goldens)
GOLDEN_TIMES = [0.6, 2.0, 4.6]
GOLDEN_SIZE = (360, 640)
MIN_SSIM = 0.985
sys.path.insert(0, str(HERE.parents[1] / 'tests' / 'py'))
sys.path.insert(0, str(APP))
from ft import export  # noqa: E402


def hf(*args):
    """The one place the renderer is named: the same locally installed, pinned HyperFrames the export uses
    (ft.export.renderer_bin, <user dir>/renderer). Only when that install is missing does this dev tool fall back to the
    pinned `npx --yes hyperframes@0.9.22`: a convenience for a fresh checkout, never what the studio does."""
    try:
        base = export.renderer_bin()
    except export.ExportError:
        base = [NPX, '--yes', HYPERFRAMES]
    return base + [str(a) for a in args]


def hf_env():
    """No telemetry, no update check (dev/notes/renderer.md): the export's own environment."""
    return export.renderer_env()

CAMS = {
    'pull':  dict(S=(1, 0.48), A=(20, 45), ax=(545, 545), ay=(1240, 1120), spin=(0, 0)),
    'crane': dict(S=(1.8, 0.5), A=(12, 42), ax=(545, 545), ay=(1300, 1130), spin=(0, 0)),
    'orbit': dict(S=(0.66, 0.58), A=(36, 36), ax=(545, 545), ay=(1150, 1150), spin=(0, 80)),
    'push':  dict(S=(0.55, 1.1), A=(42, 30), ax=(545, 545), ay=(1120, 1260), spin=(0, 0)),
    'still': dict(S=(0.62, 0.62), A=(38, 38), ax=(545, 545), ay=(1150, 1150), spin=(0, 0)),
}
THETA = {'wall': 29, 'stripes': 29, 'giant': 16, 'poster': 6}


def node_json(js):
    pre = 'global.window={};require(%s);require(%s);' % (json.dumps(str(ENGINE / 'data.js')), json.dumps(str(ENGINE / 'metrics.js')))
    r = subprocess.run(['node', '-e', pre + js], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit('node failed: ' + r.stderr)
    return json.loads(r.stdout)


def make_settings(look, phrase, hero, small, source, sets):
    text = {'source': source, 'phrase': phrase, 'hero': hero, 'small': small}
    s = node_json('console.log(JSON.stringify(window.FT_DATA.lookSettings(%s,%s)))' % (json.dumps(look), json.dumps(text)))
    for kv in sets:
        k, v = kv.split('=', 1)
        if v.lower() in ('true', 'false'):
            v = v.lower() == 'true'
        if k.startswith('fx.'):
            s['fx'][k[3:]] = v
        elif k == 'palette':
            s['palette'] = node_json('console.log(JSON.stringify(window.FT_DATA.PALETTES.filter(function(p){return p.id===%s})[0]))' % json.dumps(v))
        else:
            s[k] = v
    return s


def cam_at(cam, t, Tc):
    u = min(1, max(0, t / Tc))
    u = 2 * u * u if u < 0.5 else 1 - (-2 * u + 2) ** 2 / 2
    c = CAMS[cam]
    return {k: c[k][0] + (c[k][1] - c[k][0]) * u for k in c}


def project(x, y, c, theta):
    phi = math.radians(-theta + c['spin'])
    fx = x * math.cos(phi) - y * math.sin(phi)
    fy = x * math.sin(phi) + y * math.cos(phi)
    a = math.radians(c['A'])
    sx, sy = fx * c['S'], fy * c['S']
    yy, zz = sy * math.cos(a), sy * math.sin(a)
    k = 2000 / (2000 - zz)
    return 540 + (sx + c['ax'] - 540) * k, 150 + (yy + c['ay'] - 150) * k


def fmt_t(t):
    return '%g' % t


PURITY_JS = (HERE / 'purity.js').read_text(encoding='utf-8')
WIDTHS_JS = (HERE / 'widths.js').read_text(encoding='utf-8')


def build(name, settings, take, guide=False, purity=False, widths=False):
    out = ROOT / name
    if out.exists():
        shutil.rmtree(out)
    (out / 'assets' / 'engine' / 'fonts').mkdir(parents=True)
    for f in ENGINE_FILES:
        shutil.copy2(ENGINE / f, out / 'assets' / 'engine' / f)
    fonts = node_json('console.log(JSON.stringify(window.FT_DATA.FONTS))')
    font_file = fonts[settings['font']]['file']
    for ff in (font_file, 'inter.woff2'):           # Inter draws the characters the font lacks
        shutil.copy2(ENGINE / 'fonts' / ff, out / 'assets' / 'engine' / 'fonts' / ff)
    if widths:
        for ff in fonts.values():
            shutil.copy2(ENGINE / 'fonts' / ff['file'], out / 'assets' / 'engine' / 'fonts' / ff['file'])
    shutil.copy2(TAKE_DIR / 'person.webm', out / 'assets' / 'person.webm')
    shutil.copy2(TAKE_DIR / 'shadow.webm', out / 'assets' / 'shadow.webm')
    html = (ENGINE / 'composition.html').read_text(encoding='utf-8')
    esc = lambda o: json.dumps(o, ensure_ascii=False).replace('</', '<\\/')
    html = (html.replace('__TAKE_JSON__', esc(take)).replace('__SETTINGS_JSON__', esc(settings))
            .replace('__FONT_FILE__', font_file).replace('__DUR__', repr(take['dur'])).replace('__FPS__', repr(take['fps'])))
    if guide:
        y1, s = -150, 360
        y2 = y1 + 0.86 * s
        js = ("(function(){var p=document.querySelector('.ft-para');[[%s,'#00d0ff'],[%s,'#ff2bd6']].forEach(function(a){"
              "var g=document.createElement('div');g.style.cssText='position:absolute;left:-12000px;top:'+(a[0]-1.5)+'px;"
              "width:24000px;height:3px;background:'+a[1]+';pointer-events:none';p.appendChild(g);});})();" % (y1, y2))
        html = html.replace('window.__ft = engine;', 'window.__ft = engine; ' + js)
    if purity:
        html = html.replace("window.__timelines['main'] = tl;", "window.__timelines['main'] = tl; " + PURITY_JS)
    if widths:
        html = html.replace("window.__timelines['main'] = tl;", "window.__bench_tl = tl; " + WIDTHS_JS)
    (out / 'index.html').write_text(html, encoding='utf-8')
    return out


def run(cmd, cwd, log):
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, encoding='utf-8', errors='replace', env=hf_env(),
                       stdin=subprocess.DEVNULL)
    Path(log).write_text('$ ' + ' '.join(cmd) + '\n' + r.stdout + '\n--- stderr ---\n' + r.stderr, encoding='utf-8')
    return r


def snapshot(out, ats, zoom=None):
    snaps = out / 'snaps'
    if snaps.exists():
        shutil.rmtree(snaps)
    cmd = hf('snapshot', out, '--at', ','.join(fmt_t(t) for t in ats), '--no-end', '--keep', '--output', snaps, '--timeout', '170000')
    if zoom:
        cmd += ['--zoom', zoom]
    r = run(cmd, HERE, out / 'snapshot.log')
    files = [snaps / ('at-%ss.png' % fmt_t(t)) for t in ats]
    missing = [f for f in files if not f.exists()]
    if r.returncode or missing:
        print('snapshot problem (exit %s), missing %s; see %s' % (r.returncode, [m.name for m in missing], out / 'snapshot.log'))
    return [f for f in files if f.exists()]


def compose(items, cols, thumb_w, out_path, title=None):
    """items: [(png path, label)] -> labelled grid sheet."""
    from PIL import Image, ImageDraw
    thumbs = []
    for p, label in items:
        im = Image.open(p).convert('RGB')
        h = round(im.height * thumb_w / im.width)
        thumbs.append((im.resize((thumb_w, h), Image.LANCZOS), label))
    th = max(t.height for t, _ in thumbs)
    rows = (len(thumbs) + cols - 1) // cols
    head = 26 if title else 0
    lab = 18
    sheet = Image.new('RGB', (cols * thumb_w + (cols + 1) * 6, head + rows * (th + lab) + (rows + 1) * 6), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    if title:
        d.text((8, 6), title, fill=(235, 235, 235))
    for i, (t, label) in enumerate(thumbs):
        x = 6 + (i % cols) * (thumb_w + 6)
        y = head + 6 + (i // cols) * (th + lab + 6)
        sheet.paste(t, (x, y + lab))
        d.text((x + 2, y + 3), label, fill=(255, 220, 120))
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)
    return out_path


def one(look, name, at, phrase=PHRASE, hero='FREE', small='IN CLAUDE CODE', source='speech', sets=(), guide=False, zoom=False,
        check=False, snap=True, purity=False, widths=False):
    take = json.loads((TAKE_DIR / 'take.json').read_text(encoding='utf-8'))
    settings = make_settings(look, phrase, hero, small, source, sets)
    out = build(name, settings, take, guide, purity, widths)
    res = {'dir': out, 'settings': settings, 'frames': [], 'check': None}
    if check:
        r = run(hf('check', out, '--timeout', '120000', '--no-contrast'), HERE, out / 'check.txt')
        res['check'] = r.returncode
        print('check %s: exit %s (see %s)' % (name, r.returncode, out / 'check.txt'))
    if snap:
        z = None
        if zoom:
            Tc = 4.0 if settings['pace'] == 'smooth' else 3.2
            c = cam_at(settings['camera'], at[0], Tc)
            th = THETA[settings['layout']]
            pts = [project(-600, -150, c, th), project(-600 + 1100, -150, c, th), project(-600, 159.6, c, th), project(-600 + 1100, 159.6, c, th)]
            x0 = min(p[0] for p in pts) - 40; x1 = max(p[0] for p in pts) + 40
            y0 = min(p[1] for p in pts) - 60; y1 = max(p[1] for p in pts) + 60
            x0 = max(0, x0); y0 = max(0, y0)
            z = '%d,%d,%d,%d' % (x0, y0, min(1080 - x0, x1 - x0), min(1920 - y0, y1 - y0))
        res['frames'] = snapshot(out, at, z)
    return res


def crop_row(png, settings, t, out_png, x_range=(300, 1400)):
    """1:1 crop of the guided row (wall row c1: para y -150, cap size 360) out of a full snapshot."""
    from PIL import Image
    c = cam_at(settings['camera'], t, 4.0)
    th = THETA[settings['layout']]
    pts = [project(x, y, c, th) for x in x_range for y in (-150, 159.6)]
    x0 = max(0, min(p[0] for p in pts) - 30); x1 = min(1080, max(p[0] for p in pts) + 30)
    y0 = max(0, min(p[1] for p in pts) - 50); y1 = min(1920, max(p[1] for p in pts) + 50)
    Image.open(png).convert('RGB').crop((int(x0), int(y0), int(x1), int(y1))).save(out_png)
    return out_png


def sheets(which):
    at4 = [0.5, 1.6, 3.0, 4.9]
    if which in ('looks', 'all'):
        for grp, names in (('a', LOOKS[:3]), ('b', LOOKS[3:])):
            items = []
            for look in names:
                r = one(look, 'look-' + look, at4, check=True)
                items += [(f, '%s  %ss' % (look, f.stem.split('-', 1)[1][:-1])) for f in r['frames']]
            compose(items, 4, 300, HERE / 'sheets' / ('looks-%s.png' % grp), 'looks: ' + ', '.join(names) + '  at 0.5 / 1.6 / 3.0 / 4.9 s')
    if which in ('fonts', 'all'):
        items, crops = [], []
        for font in FONTS:
            r = one('original', 'font-' + font, [3.0], sets=['font=' + font, 'camera=still', 'ending=cut'], guide=True)
            items += [(f, font) for f in r['frames']]
            if r['frames']:
                cp = r['dir'] / 'crop-row.png'
                crop_row(r['frames'][0], r['settings'], 3.0, cp)
                crops.append((cp, font))
        compose(items, 3, 360, HERE / 'sheets' / 'fonts.png', 'fonts: wall at 3.0 s, camera still; cyan = cap top of row c1, magenta = its baseline')
        compose(crops, 2, 640, HERE / 'sheets' / 'fonts-zoom.png', 'fonts: 1:1 crop of row c1 (cyan = cap top, magenta = baseline)')
    if which in ('entrances', 'all'):
        times = {'slide': [0.45, 0.60], 'drop': [0.45, 0.57], 'rise': [0.42, 0.60], 'type': [0.40, 0.55], 'pop': [0.40, 0.55], 'wipe': [0.45, 0.63]}
        items = []
        for e in ENTRANCES:
            r = one('original', 'ent-' + e, times[e], sets=['entrance=' + e, 'ending=cut'])
            items += [(f, '%s  %ss' % (e, f.stem.split('-', 1)[1][:-1])) for f in r['frames']]
        compose(items, 4, 270, HERE / 'sheets' / 'entrances.png', 'entrances: two instants inside the first rows entry (first row enters at 0.30 s)')
    if which in ('endings', 'all'):
        items = []
        for e in ENDINGS:
            r = one('original', 'end-' + e, [4.5, 4.75, 5.0], sets=['ending=' + e])
            items += [(f, '%s  %ss' % (e, f.stem.split('-', 1)[1][:-1])) for f in r['frames']]
        compose(items, 3, 300, HERE / 'sheets' / 'endings.png', 'endings: cut / exit / dive / sink at 4.5 / 4.75 / 5.0 s (dur 5.042)')


def golden_name(look, t):
    return '%s-%.1f.png' % (look, t)


def render_goldens(work, looks=LOOKS, times=GOLDEN_TIMES):
    """Each look at its default settings on the sample take (the phrase, hero and small text above), ONE HyperFrames
    snapshot run per look for all instants, scaled to 360x640. Returns {golden file name: png path}."""
    global ROOT
    import imgcmp
    ROOT = Path(work)
    ROOT.mkdir(parents=True, exist_ok=True)
    out = {}
    for look in looks:
        r = one(look, 'g-' + look, list(times))
        if len(r['frames']) != len(times):
            raise SystemExit('golden render failed for %s, see %s' % (look, r['dir'] / 'snapshot.log'))
        for t, f in zip(times, r['frames']):
            small = ROOT / golden_name(look, t)
            imgcmp.downscale(f, small, *GOLDEN_SIZE)
            out[golden_name(look, t)] = small
    return out


def golden_cmd(dest, compare, min_ssim, work=None):
    import imgcmp
    dest = Path(dest)
    work = Path(work) if work else Path(tempfile.mkdtemp(prefix='ftg-'))
    t0 = time.time()
    made = render_goldens(work)
    print('rendered %d images in %.0f s (scratch %s)' % (len(made), time.time() - t0, work))
    if not compare:
        dest.mkdir(parents=True, exist_ok=True)
        for name, p in made.items():
            shutil.copy2(p, dest / name)
        print('wrote %d goldens to %s' % (len(made), dest))
        return 0
    bad, lowest = [], 1.0
    for name, p in sorted(made.items()):
        g = dest / name
        if not g.exists():
            bad.append((name, 'no golden'))
            continue
        v = imgcmp.ssim(p, g)
        lowest = min(lowest, v)
        print('%-20s ssim %.4f%s' % (name, v, '' if v >= min_ssim else '   <-- below %.3f' % min_ssim))
        if v < min_ssim:
            bad.append((name, '%.4f' % v))
    print('lowest ssim %.4f (bar %.3f)' % (lowest, min_ssim))
    if bad:
        print('FAILED: ' + ', '.join('%s (%s)' % b for b in bad))
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('look', nargs='?', default='original')
    ap.add_argument('--name')
    ap.add_argument('--phrase', default=PHRASE)
    ap.add_argument('--hero', default='FREE')
    ap.add_argument('--small', default='IN CLAUDE CODE')
    ap.add_argument('--source', default='speech')
    ap.add_argument('--set', action='append', default=[])
    ap.add_argument('--at', default='0.5,1.6,3.0,4.9')
    ap.add_argument('--guide', action='store_true')
    ap.add_argument('--zoom', action='store_true')
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--purity', action='store_true')
    ap.add_argument('--widths', action='store_true')
    ap.add_argument('--no-snap', action='store_true')
    ap.add_argument('--sheet')
    ap.add_argument('--sheets')
    ap.add_argument('--golden', metavar='DIR')
    ap.add_argument('--compare', metavar='DIR')
    ap.add_argument('--min-ssim', type=float, default=MIN_SSIM)
    ap.add_argument('--work', help='scratch folder for --golden / --compare (default: a new temp folder)')
    a = ap.parse_args()
    if a.golden or a.compare:
        sys.exit(golden_cmd(a.golden or a.compare, bool(a.compare), a.min_ssim, a.work))
    if a.sheets:
        sheets(a.sheets)
        return
    at = [float(x) for x in a.at.split(',') if x.strip()]
    name = a.name or a.look
    r = one(a.look, name, at, a.phrase, a.hero, a.small, a.source, a.set, a.guide, a.zoom, a.check, not a.no_snap, a.purity, a.widths)
    print('folder:', r['dir'])
    for f in r['frames']:
        print('frame:', f)
    if a.sheet and r['frames']:
        compose([(f, '%s %ss' % (name, f.stem.split('-', 1)[1][:-1])) for f in r['frames']], min(4, len(r['frames'])), 300, a.sheet, name)
        print('sheet:', a.sheet)


if __name__ == '__main__':
    main()
