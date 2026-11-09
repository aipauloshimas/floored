"""The engine's fonts cover the Latin charset (or Inter draws the rest) and metrics.js measures every character."""
import json
import re
import unicodedata
import sys
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'dev'))
import gen_metrics as G  # noqa: E402

ENGINE = G.ENGINE
FONT_DIR = ENGINE / 'fonts'
DATA_JS = (ENGINE / 'data.js').read_text(encoding='utf-8')
# FONTS = { id: { ..., file: 'x.woff2', weight: N ...} } in data.js
FONT_IDS = dict(re.findall(r"^\s{4}(\w+):\s*\{[^}]*?file:\s*'([\w.]+)'", DATA_JS, re.M))
FONT_FILES = sorted(set(FONT_IDS.values()) | {G.INTER_FILE})


def metrics():
    text = (ENGINE / 'metrics.js').read_text(encoding='utf-8')
    return json.loads(text[text.index('window.FT_METRICS = ') + len('window.FT_METRICS = '):text.rindex(';')])


def id_of(file):
    return next((k for k, v in FONT_IDS.items() if v == file), None)


def test_data_js_lists_the_six_fonts():
    assert set(FONT_IDS) == set(G.FONTS) and len(FONT_IDS) == 6
    assert set(FONT_IDS.values()) == {f['file'] for f in G.FONTS.values()}


@pytest.mark.parametrize("font", FONT_FILES)
def test_font_covers_charset_or_falls_back(font):
    cmap = TTFont(str(FONT_DIR / font)).getBestCmap()
    allowed = G.FALLBACK_OK[id_of(font)] if id_of(font) else set()      # inter.woff2 allows nothing
    missing = {c for c in G.CHARSET if ord(c) not in cmap}
    assert missing <= allowed, 'missing from %s: %s' % (font, ''.join(sorted(missing - allowed)))
    if font == G.INTER_FILE:
        assert not missing and all(ord(c) in cmap for c in G.UI_EXTRA)
    if font == 'gochihand.woff2':
        assert {'Ś', 'Ż', 'Ą'} <= missing         # the reason Inter is in the stack
    if font == 'anton.woff2':
        assert all(ord(c) in cmap for c in 'ŁŚŻĆÓ')


def test_inter_is_variable_in_weight_only():
    t = TTFont(str(FONT_DIR / G.INTER_FILE))
    assert [(a.axisTag, a.minValue, a.maxValue) for a in t['fvar'].axes] == [('wght', 100.0, 900.0)]


def test_metrics_cover_charset():
    m = metrics()
    assert set(m) == set(FONT_IDS)
    for fid, mm in m.items():
        missing = [c for c in G.CHARSET if c not in mm['w']]
        assert not missing, '%s has no width for %r' % (fid, ''.join(missing))
        assert all(isinstance(v, (int, float)) and v >= 0 for v in mm['w'].values())
        assert {'capH', 'asc', 'desc', 'fallback', 'fbAdj'} <= set(mm)


def test_metrics_match_the_font_files():
    m = metrics()
    for fid, f in G.FONTS.items():
        font = TTFont(str(FONT_DIR / f['file']))
        cmap, hmtx, upm = font.getBestCmap(), font['hmtx'], font['head'].unitsPerEm
        for c in G.CHARSET:
            if ord(c) in cmap:
                assert abs(m[fid]['w'][c] - hmtx[cmap[ord(c)]][0] / upm) < 6e-5, (fid, c)
        assert abs(m[fid]['capH'] - font['OS/2'].sCapHeight / upm) < 6e-5


def test_fallback_characters_use_inter_scaled_to_the_cap_height():
    m = metrics()['hand']
    inter = G.inter_at(400)
    iw = G.advances(inter, 'Ś')['Ś']
    assert abs(m['w']['Ś'] - iw * m['fbAdj']) < 1e-3
    assert abs(m['fbAdj'] - m['capH'] / (inter['OS/2'].sCapHeight / inter['head'].unitsPerEm)) < 1e-3


@pytest.mark.parametrize("fid", sorted(G.FONTS))
def test_rise_table_is_the_height_of_the_marks_above_the_cap_height(fid):
    """metrics.js `t` lists exactly the accented letters that reach over the cap height, as the browser draws them."""
    f = G.FONTS[fid]
    font = TTFont(str(FONT_DIR / f['file']))
    capH = font['OS/2'].sCapHeight / font['head'].unitsPerEm
    inter = G.inter_at(f['weight'])
    adj = capH / (inter['OS/2'].sCapHeight / inter['head'].unitsPerEm)
    t = metrics()[fid]['t']
    for c in G.CHARSET:
        top = G.ymax(font, c)
        top = top if top is not None else (G.ymax(inter, c) or 0) * adj      # a missing glyph is Inter's, scaled
        rise = top - capH
        if G.has_mark(c) and rise > G.MARK_MIN:
            assert t[c] == pytest.approx(rise, abs=0.0006), c
        else:
            assert c not in t, c
    assert all(G.has_mark(c) for c in t)
    assert all(0.1 < t[c] < 0.4 for c in 'ÊÃÓŻŚ')      # a circumflex, tilde, acute or dot is a tenth to a third of an em tall


@pytest.mark.parametrize("fid", sorted(G.FONTS))
def test_depth_table_is_the_reach_below_the_baseline_beyond_the_base_letter(fid):
    """metrics.js `b` lists the accented letters that hang under the baseline further than their plain base letter does
    (cedilla, ogonek, comma below), as the browser draws them: the font's glyph, else Inter's scaled by fbAdj."""
    f = G.FONTS[fid]
    font = TTFont(str(FONT_DIR / f['file']))
    capH = font['OS/2'].sCapHeight / font['head'].unitsPerEm
    inter = G.inter_at(f['weight'])
    adj = capH / (inter['OS/2'].sCapHeight / inter['head'].unitsPerEm)

    def bottom(c):
        v = G.ymin(font, c)
        return v if v is not None else (G.ymin(inter, c) or 0) * adj

    b = metrics()[fid]['b']
    for c in G.CHARSET:
        base = unicodedata.normalize('NFD', c)[0]
        d = min(bottom(base), 0) - bottom(c)
        if G.has_mark(c) and d > G.DEPTH_MIN:
            assert b[c] == pytest.approx(d, abs=0.0006), c
        else:
            assert c not in b, c
    assert all(G.has_mark(c) for c in b)
    assert all(0.06 < b[c] < 0.4 for c in 'ÇĄĘŞ')     # a cedilla or an ogonek hangs a fifth to a third of an em
    assert not any(c in b for c in 'ÊÃÓŻŚÁQJ,;')


def _font_files():
    return [(fid, G.FONTS[fid]['file']) for fid in sorted(G.FONTS)] + [('inter', G.INTER_FILE)]


@pytest.mark.parametrize("fid,file", _font_files())
def test_every_accented_glyph_has_its_own_outline(fid, file):
    """A letter and its accented form must not share an outline: the mark has to be in the glyph (composites decomposed)."""
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    font = TTFont(str(FONT_DIR / file))
    cmap, gs = font.getBestCmap(), font.getGlyphSet()

    def outline(ch):
        pen = DecomposingRecordingPen(gs)
        gs[cmap[ord(ch)]].draw(pen)
        return pen.value

    checked, same = 0, []
    for c in G.CHARSET:
        base = unicodedata.normalize('NFD', c)[0]
        if not G.has_mark(c) or ord(c) not in cmap or ord(base) not in cmap:
            continue
        checked += 1
        if outline(c) == outline(base):
            same.append(c)
    assert checked > 60 or fid == 'hand', (fid, checked)
    assert not same, '%s draws %s exactly like its base letter' % (fid, ''.join(same))


@pytest.mark.parametrize("fid,file", _font_files())
def test_every_accented_letter_renders_differently_from_its_base(fid, file, tmp_path):
    """Rasterised by FreeType from the shipped woff2 (as a TTF): each accented letter's bitmap differs from its base letter's,
    and a letter whose table says it has marks above (t) or below (b) has ink there."""
    from PIL import Image, ImageDraw, ImageFont
    font = TTFont(str(FONT_DIR / file))
    font.flavor = None
    ttf = tmp_path / 'f.ttf'
    font.save(str(ttf))
    cmap = font.getBestCmap()
    size = 200
    im_font = ImageFont.truetype(str(ttf), size)
    upm = font['head'].unitsPerEm
    capH = font['OS/2'].sCapHeight / upm
    metr = metrics().get(fid, {})

    def draw(ch):
        im = Image.new('L', (size * 2, size * 3), 0)
        ImageDraw.Draw(im).text((size // 2, size), ch, font=im_font, fill=255, anchor='ls')    # baseline at y = size
        return im

    same, no_ink = [], []
    for c in G.CHARSET:
        base = unicodedata.normalize('NFD', c)[0]
        if not G.has_mark(c) or ord(c) not in cmap or ord(base) not in cmap:
            continue
        a, b = draw(c), draw(base)
        if a.tobytes() == b.tobytes():
            same.append(c)
        cap_y = size - capH * size
        above = a.crop((0, 0, a.width, int(cap_y) - 4)).getbbox()      # ink more than 4 px over the cap height
        below = a.crop((0, size + 4, a.width, a.height)).getbbox()     # ink more than 4 px under the baseline
        if c in metr.get('t', {}) and metr['t'][c] * size > 8 and above is None:
            no_ink.append(c + ' (above)')
        if c in metr.get('b', {}) and metr['b'][c] * size > 8 and below is None:
            no_ink.append(c + ' (below)')
    assert not same, '%s renders %s like its base letter' % (fid, ''.join(same))
    assert not no_ink, '%s: no ink where the tables say there are marks: %s' % (fid, no_ink)
