#!/usr/bin/env python3
"""Rebuild the floored fonts and the font tables the layout reads.

  python dev/gen_metrics.py            download missing sources, rebuild every woff2 + metrics.js
  python dev/gen_metrics.py --metrics  only rewrite metrics.js from the woff2 files already in engine/fonts

What it writes (all under plugin/skills/floored/app/web/engine/):
  fonts/<file>.woff2  each family's OFL font subset to CHARSET (variable fonts instanced first, see FONTS); inter.woff2
                      is Inter (UI and the fallback face) with its wght axis kept and opsz pinned to 14
  metrics.js          window.FT_METRICS[fontId] = {capH, asc, desc, fallback, fbAdj, w: {char: advance}, t: {char: rise}, b: {char: depth}}, in em
                      t[ch] = how far the accented letter `ch` reaches above the cap height (its yMax minus capH), so the layout
                      can leave room for the marks; only letters that carry a combining mark and rise over MARK_MIN (0.04 em, above any overshoot) are listed

A character a font lacks (Gochi Hand has no latin-ext) is drawn by Inter, scaled with CSS `size-adjust` so the two cap
heights match; its table width is Inter's advance (at the font's weight) times fbAdj = font capH / Inter capH, so the
layout measures what the browser draws. FALLBACK_OK lists, per font, the characters allowed to be missing.

Sources (SIL OFL 1.1), github.com/google/fonts at commit 5bb28733cec313b63fbd415b574b5ae35c8aa8b8 (fetched 2026-11-08),
URL = https://raw.githubusercontent.com/google/fonts/<commit>/ofl/<path>. The TTFs are downloaded to dev/fonts-src/
(git-ignored); only the subset woff2 files are committed. The paths are in FONTS below; see dev/notes/fonts.md.
"""
import argparse
import io
import json
import unicodedata
import urllib.parse
import urllib.request
from pathlib import Path

from fontTools import subset
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent / 'plugin' / 'skills' / 'floored' / 'app' / 'web' / 'engine'
FONT_DIR = ENGINE / 'fonts'
SRC_DIR = HERE / 'fonts-src'
GOOGLE_FONTS_COMMIT = '5bb28733cec313b63fbd415b574b5ae35c8aa8b8'
RAW = 'https://raw.githubusercontent.com/google/fonts/%s/ofl/' % GOOGLE_FONTS_COMMIT


def _chars(*ranges):
    out = []
    for a, b in ranges:
        out.extend(chr(c) for c in range(a, b + 1))
    return out


# Basic Latin, Latin-1 Supplement, Latin Extended-A, and the typographic marks the layout keeps.
# Two code points of those ranges are left out on purpose: U+00AD (soft hyphen: invisible, the layout strips it) and U+0149
# (deprecated ŉ: upper-cases to ʼN, and Inter, Poppins, Instrument Serif and Big Shoulders have no glyph for it).
_NOT_KEPT = {chr(0xAD), chr(0x149)}
CHARSET = ''.join(_chars((0x20, 0x7E), (0xA0, 0xFF), (0x100, 0x17F), (0x2018, 0x2019), (0x201C, 0x201D), (0x2013, 0x2014), (0x2026, 0x2026), (0x20AC, 0x20AC)))
CHARSET = ''.join(c for c in dict.fromkeys(CHARSET) if c not in _NOT_KEPT)
UI_EXTRA = ''.join(_chars((0x2022, 0x2022), (0x2190, 0x2193)))    # bullet and arrows: studio UI only (Inter has them)
INTER_FILE = 'inter.woff2'
INTER_SRC = ('inter/Inter[opsz,wght].ttf', {'opsz': 14})   # wght stays variable

# id -> where it comes from. axes pins a variable font's axes before subsetting; weight is the CSS weight data.js draws it at.
FONTS = {
    'condensed': dict(src='anton/Anton-Regular.ttf', axes=None, weight=400, file='anton.woff2'),
    'serif':     dict(src='instrumentserif/InstrumentSerif-Regular.ttf', axes=None, weight=400, file='serif.woff2'),
    'geo':       dict(src='poppins/Poppins-Black.ttf', axes=None, weight=900, file='geo.woff2'),
    'mono':      dict(src='jetbrainsmono/JetBrainsMono[wght].ttf', axes={'wght': 700}, weight=700, file='mono.woff2'),
    'stencil':   dict(src='bigshouldersstencil/BigShouldersStencil[opsz,wght].ttf', axes={'wght': 900, 'opsz': 14}, weight=900,
                      file='stencil.woff2'),
    'hand':      dict(src='gochihand/GochiHand-Regular.ttf', axes=None, weight=400, file='gochihand.woff2'),
}

# Characters a font may lack (Inter draws them, scaled to the font's cap height). Anything else missing from a font's
# cmap is an error. Gochi Hand has no Latin Extended-A to speak of (Ł ł are there, Ś Ż Ń Ą are not); the others only lack
# rare letters (Esperanto ĉ, Dutch ĳ, Maltese ħ ...) and, for Instrument Serif, a few Latin-1 symbols (¤ ¦ ¬ ± ² ³ µ ¹ ¼ ½ ¾).
_FB = {
    'condensed': [],
    'serif': [(0xA4,), (0xA6,), (0xAC,), (0xB1, 0xB3), (0xB5,), (0xB9,), (0xBC, 0xBE), (0x108, 0x109), (0x114, 0x115),
               (0x11C, 0x11D), (0x124, 0x125), (0x128, 0x129), (0x12C, 0x12D), (0x134, 0x135), (0x138,), (0x13F, 0x140),
               (0x14E, 0x14F), (0x15C, 0x15D), (0x162, 0x163), (0x166, 0x169), (0x17F,)],
    'geo': [(0x108, 0x109), (0x11C, 0x11D), (0x124, 0x127), (0x132, 0x135), (0x138,), (0x14A, 0x14B), (0x15C, 0x15D),
            (0x166, 0x167), (0x17F,)],
    'mono': [(0x132, 0x133)],
    'stencil': [(0x132, 0x133), (0x17F,)],
    'hand': [(0x100, 0x126), (0x12A, 0x130), (0x132,), (0x136,), (0x139, 0x13F), (0x145, 0x151), (0x155,), (0x15A, 0x15F),
             (0x162, 0x177), (0x179, 0x17C), (0x17F,)],
}
FALLBACK_OK = {k: set(chr(c) for r in v for c in range(r[0], r[-1] + 1)) & set(CHARSET) for k, v in _FB.items()}


def source_path(rel):
    return SRC_DIR / Path(rel).name


def fetch_source(rel):
    p = source_path(rel)
    if p.exists():
        return p
    SRC_DIR.mkdir(parents=True, exist_ok=True)
    url = RAW + urllib.parse.quote(rel, safe='/,')
    print('download', url)
    with urllib.request.urlopen(url, timeout=120) as r:
        data = r.read()
    p.write_bytes(data)
    return p


def load_instance(rel, axes):
    font = TTFont(str(fetch_source(rel)))
    if 'fvar' in font:
        font = instantiateVariableFont(font, dict(axes or {}), inplace=False)
        buf = io.BytesIO()                   # reload: subsetting a freshly instanced variable font trips on its lazy gvar
        font.save(buf)
        buf.seek(0)
        font = TTFont(buf)
    return font


# OFL section 3: a Modified Version (a subset is one) must not use a Reserved Font Name. Only Gochi Hand reserves its names
# ("Gochi", "Gochi Hand"); its family is renamed to the CSS family. The copyright notice (name ID 0) is kept as it is.
RENAME = {'hand': ('FT Hand', 'FTHand')}


def rename_family(font, family, ps):
    """Replace the family name in the name table (IDs 1, 3, 4, 6, 16, 18, 21) on every platform; style names are kept."""
    for rec in list(font['name'].names):
        if rec.nameID in (1, 16, 18, 21):
            rec.string = family
        elif rec.nameID == 4:
            rec.string = family
        elif rec.nameID == 6:
            rec.string = ps + '-Regular'
        elif rec.nameID == 3:
            rec.string = '%s-Regular; subset of the OFL font' % ps
    return font


def subset_font(font, unicodes, out_path):
    opts = subset.Options()
    opts.flavor = 'woff2'
    opts.layout_features = ['ccmp']          # the engine turns kern, liga and calt off; accents are precomposed glyphs
    opts.name_IDs = ['*']                    # keep the copyright and OFL notices
    opts.notdef_outline = True
    opts.glyph_names = False
    opts.drop_tables += ['DSIG']
    sub = subset.Subsetter(opts)
    sub.populate(unicodes=[ord(c) for c in unicodes])
    sub.subset(font)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    subset.save_font(font, str(out_path), opts)


def r4(v):
    return round(v + 1e-12, 4)


def advances(font, chars):
    cmap, hmtx, upm = font.getBestCmap(), font['hmtx'], font['head'].unitsPerEm
    return {c: hmtx[cmap[ord(c)]][0] / upm for c in chars if ord(c) in cmap}


def build_fonts():
    for fid, f in FONTS.items():
        font = load_instance(f['src'], f['axes'])
        if fid in RENAME:
            rename_family(font, *RENAME[fid])
        subset_font(font, CHARSET, FONT_DIR / f['file'])
        print('wrote', f['file'], (FONT_DIR / f['file']).stat().st_size, 'bytes')
    subset_font(load_instance(*INTER_SRC), CHARSET + UI_EXTRA, FONT_DIR / INTER_FILE)
    print('wrote', INTER_FILE, (FONT_DIR / INTER_FILE).stat().st_size, 'bytes')


_INTER = {}


def inter_at(weight):
    if weight not in _INTER:
        _INTER[weight] = instantiateVariableFont(TTFont(str(FONT_DIR / INTER_FILE)), {'wght': weight}, inplace=False)
    return _INTER[weight]


def missing_chars(font_file):
    cmap = TTFont(str(FONT_DIR / font_file)).getBestCmap()
    return [c for c in CHARSET if ord(c) not in cmap]


DEPTH_MIN = 0.04               # a marked letter counts as hanging below the baseline when it reaches this far (em) under it
MARK_MIN = 0.04                # a letter counts as marked when it reaches this far (em) above the cap height; round letters overshoot ~0.01


def ymax(font, ch):
    """Top of the glyph for ch in em, or None when the font has no glyph for it."""
    cmap = font.getBestCmap()
    if ord(ch) not in cmap:
        return None
    gs = font.getGlyphSet()
    pen = BoundsPen(gs)
    gs[cmap[ord(ch)]].draw(pen)
    return None if pen.bounds is None else pen.bounds[3] / font['head'].unitsPerEm


def ymin(font, ch):
    """Bottom of the glyph for ch in em (negative below the baseline), or None when the font has no glyph for it."""
    cmap = font.getBestCmap()
    if ord(ch) not in cmap:
        return None
    gs = font.getGlyphSet()
    pen = BoundsPen(gs)
    gs[cmap[ord(ch)]].draw(pen)
    return None if pen.bounds is None else pen.bounds[1] / font['head'].unitsPerEm


def has_mark(ch):
    return any(unicodedata.category(c) == 'Mn' for c in unicodedata.normalize('NFD', ch))


def rises(font, inter, capH, adj):
    """em above cap height per accented character, as the browser draws it: the font's own glyph, else Inter's times adj."""
    t = {}
    for c in CHARSET:
        if not has_mark(c):
            continue
        top = ymax(font, c)
        if top is None:
            top = ymax(inter, c)
            top = None if top is None else top * adj
        if top is not None and top - capH > MARK_MIN:
            t[c] = r4(top - capH)
    return t


def depths(font, inter, adj):
    """em that an accented character reaches under the baseline further than its plain base letter does (cedilla, ogonek,
    comma below...), as the browser draws it: the font's own glyph, else Inter's times adj. The base letter's own overshoot
    is left out (a hand font's O dips 0.08 em), so plain letters never count and unaccented rows lay out exactly as before."""
    def bottom(ch):
        v = ymin(font, ch)
        if v is None:
            v = ymin(inter, ch)
            v = None if v is None else v * adj
        return v
    b = {}
    for c in CHARSET:
        if not has_mark(c):
            continue
        bot, base = bottom(c), bottom(unicodedata.normalize('NFD', c)[0])
        if bot is None or base is None:
            continue
        d = min(base, 0) - bot
        if d > DEPTH_MIN:
            b[c] = r4(d)
    return b


def compute_metrics():
    out = {}
    for fid, f in FONTS.items():
        font = TTFont(str(FONT_DIR / f['file']))
        upm = font['head'].unitsPerEm
        capH = font['OS/2'].sCapHeight / upm
        adv = advances(font, CHARSET)
        miss = [c for c in CHARSET if c not in adv]
        if set(miss) != set(FALLBACK_OK[fid]):
            raise SystemExit('%s: missing characters differ from FALLBACK_OK: new %r, no longer missing %r' % (
                fid, ''.join(sorted(set(miss) - set(FALLBACK_OK[fid]))), ''.join(sorted(set(FALLBACK_OK[fid]) - set(miss)))))
        inter = inter_at(f['weight'])
        icap = inter['OS/2'].sCapHeight / inter['head'].unitsPerEm
        adj = r4(capH / icap)
        iadv = advances(inter, miss)
        w = {}
        for c in CHARSET:
            w[c] = r4(adv[c]) if c in adv else r4(iadv[c] * adj)
        upper = [adv[c] for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ']
        out[fid] = dict(capH=r4(capH), asc=r4(font['hhea'].ascent / upm), desc=r4(-font['hhea'].descent / upm),
                        fallback=r4(sum(upper) / len(upper)), fbAdj=adj, w=w,
                        t=rises(font, inter, capH, adj), b=depths(font, inter, adj))
    return out


HEADER = ("/* floored font metrics, generated from the font files by dev/gen_metrics.py with fontTools (stencil instanced at\n"
          "   wght 900, opsz 14). capH/asc/desc and advance widths are in em. w covers every character the engine keeps (see\n"
          "   FTLayout.words); a character the font lacks has Inter's advance times fbAdj (the CSS size-adjust of the Inter\n"
          "   fallback face). t lists how far each accented letter reaches above the cap height, in em, and b how far a letter with a cedilla, ogonek or comma below reaches under the baseline, so the rows can leave\n"
          "   room for the marks. Layout uses these instead of canvas so it is synchronous and identical in the studio and the\n"
          "   render. */\n")


def write_metrics(m):
    body = json.dumps(m, ensure_ascii=False, separators=(',', ':'))
    (ENGINE / 'metrics.js').write_text(HEADER + 'window.FT_METRICS = ' + body + ';\n', encoding='utf-8', newline='\n')
    print('wrote metrics.js (%d bytes)' % (ENGINE / 'metrics.js').stat().st_size)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--metrics', action='store_true', help='only rewrite metrics.js from the woff2 files already there')
    a = ap.parse_args()
    if not a.metrics:
        build_fonts()
    write_metrics(compute_metrics())


if __name__ == '__main__':
    main()
