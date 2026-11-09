"""Measuring a cutout and checking the take.

measure() finds the feet (the floor anchor, the midpoint of the two shoe soles), the person's height and k0 (the
person's size on the floor), the frames that touch the edge, how far the feet wander and how often a second person
shows up. take_warnings() turns that, plus what the upload looks like, into friendly warnings. Every threshold lives
in ft.calibration.
"""
import subprocess

import numpy as np

from ft import calibration as cal
from ft.media import PipelineError
from ft.proc import NO_WINDOW, tool


def _flood(coarse, seed):
    """The connected cells (8-neighbourhood) of `coarse` that contain the cell `seed`."""
    reach = np.zeros_like(coarse)
    reach[seed] = True
    while True:
        p = np.pad(reach, 1)
        grown = (p[:-2, :-2] | p[:-2, 1:-1] | p[:-2, 2:] | p[1:-1, :-2] | p[1:-1, 1:-1] | p[1:-1, 2:]
                 | p[2:, :-2] | p[2:, 1:-1] | p[2:, 2:]) & coarse
        if np.array_equal(grown, reach):
            return reach
        reach = grown


def _blobs(m, cell=cal.BLOB_CELL):
    """(mask of the biggest connected blob, its pixel count, the pixel count of the second biggest blob).
    numpy only: a flood fill on a coarse grid. RVM sometimes leaves stray bits (a chair, a shadow); they must not move
    the feet or the head top, and a second person must be noticed."""
    H, W = m.shape
    ch, cw = -(-H // cell), -(-W // cell)
    pad = np.zeros((ch * cell, cw * cell), bool)
    pad[:H, :W] = m
    cnt = pad.reshape(ch, cell, cw, cell).sum(axis=(1, 3))
    coarse = cnt > 0
    if not coarse.any():
        return m, 0, 0
    reach = _flood(coarse, np.unravel_index(np.argmax(cnt), cnt.shape))
    rest = coarse & ~reach
    second = 0
    if rest.any():
        second = int(cnt[_flood(rest, np.unravel_index(np.argmax(np.where(rest, cnt, 0)), cnt.shape))].sum())
    keep = np.repeat(np.repeat(reach, cell, 0), cell, 1)[:H, :W]
    return m & keep, int(cnt[reach].sum()), second


def _largest_blob(m, cell=cal.BLOB_CELL):
    """Keep only the biggest connected blob of a boolean mask."""
    return _blobs(m, cell)[0]


def _frame_stats(a):
    """Per-frame numbers from one alpha frame (uint8 HxW), or None when no person is there."""
    m16, main, second = _blobs(a > cal.ALPHA_SOFT)
    m = m16 & (a > cal.ALPHA_SOLID)
    if int(m.sum()) < cal.MIN_PERSON_PX:
        return None
    ys, xs = np.nonzero(m)
    top, bot, left, right = int(ys.min()), int(ys.max()), int(xs.min()), int(xs.max())
    # the two shoes: columns opaque in the bottom of the silhouette, split at the widest gap
    band = m[max(0, bot - cal.SHOE_BAND_PX):bot + 1]
    cols = np.nonzero(band.any(axis=0))[0]
    gaps = np.diff(cols)
    g = int(np.argmax(gaps)) if len(gaps) else 0
    two = bool(len(gaps)) and gaps[g] > cal.SHOE_GAP_PX
    shoes = [cols[:g + 1], cols[g + 1:]] if two else [cols]
    soles = []
    for c in shoes:
        sub = m[:, c.min():c.max() + 1]
        yb = int(np.nonzero(sub.any(axis=1))[0].max())                            # lowest opaque row of this shoe
        xb = np.nonzero(sub[max(0, yb - cal.SOLE_ROWS):yb + 1].any(axis=0))[0]    # its sole, a few rows up
        soles.append((float(c.min() + xb.mean()), yb))
    # how wide the bottom of the cutout is against the shoulders: about 1 when it was cut at the hips (legs lost).
    # The bottom is a span (it includes the gap between the legs), the shoulders a count of filled pixels in one row:
    # a wide stance reads higher, which the measured takes allow (kept legs 0.34-0.66, lost legs 1.04-1.08).
    upper = m[top:top + (bot - top) // 2]
    shoulders = int(upper.sum(axis=1).max()) if upper.size else 0
    e = cal.EDGE_PX
    edge = bool(m16[:, :e].any() or m16[:, -e:].any() or m16[:e].any() or m16[-e:].any())
    return {'top': top, 'bot': bot, 'left': left, 'right': right,
            'fx': float(np.mean([s[0] for s in soles])), 'fy': float(np.mean([s[1] for s in soles])),
            'shoes': len(soles), 'dist': abs(soles[1][0] - soles[0][0]) if len(soles) == 2 else None,
            'width': int(cols.max() - cols.min()) if len(cols) else 0, 'edge': edge,
            'legs': (int(cols.max() - cols.min()) / shoulders) if (len(cols) and shoulders) else 0.0,
            'second': second / main if main else 0.0}


def _runs(frames):
    runs, start, prev = [], None, None
    for f in frames:
        if start is None:
            start = prev = f
        elif f == prev + 1:
            prev = f
        else:
            runs.append((start, prev))
            start = prev = f
    if start is not None:
        runs.append((start, prev))
    return runs


def _times_text(frames, fps, limit=3):
    """'around 1.3 s, 2.6 s and 4.0 s': the middle of each run of frames."""
    mids = [(a + b + 1) / 2 / fps for a, b in _runs(frames)]
    txt = ['%.1f s' % t for t in mids[:limit]]
    if len(txt) > 1:
        out = ', '.join(txt[:-1]) + ' and ' + txt[-1]
    else:
        out = txt[0] if txt else ''
    return 'around ' + out + (' and later' if len(mids) > limit else '')


def measure(person, W, H, fps, progress=None):
    """Feet, height, k0, aoWidth, edge frames and the second-person share of an RVM cutout (a VP9-alpha webm of W x H
    pixels). Returns (fields for take.json, diagnostics). When nobody is found, diag['found'] is False and the fields
    are empty: that is not an error here, the caller decides what to do (the take check warns about it)."""
    p = subprocess.Popen([tool('ffmpeg'), '-loglevel', 'error', '-c:v', 'libvpx-vp9', '-i', str(person), '-vf',
                          'alphaextract', '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    rows, areas = [], []
    try:
        while True:
            buf = p.stdout.read(W * H)
            if len(buf) < W * H:
                break
            a = np.frombuffer(buf, np.uint8).reshape(H, W)
            rows.append(_frame_stats(a))
            areas.append(float((a > cal.ALPHA_SOLID).mean()))
            if progress and len(rows) % 8 == 0:
                progress(len(rows))
    finally:
        p.stdout.close()
        code = p.wait()
    n = len(rows)
    if code != 0 or n == 0:                                       # a missing or broken file is not "nobody there"
        raise PipelineError("We couldn't read the cut-out video. Try again, and if it keeps happening, ask Claude for help.")
    good = [i for i, r in enumerate(rows) if r]
    missing = [i for i, r in enumerate(rows) if not r]
    base = {'frames': n, 'width': W, 'height': H, 'fps': fps, 'noPersonFrames': missing,
            'areaMedian': round(float(np.median(areas)), 4) if areas else 0.0}
    height = 0.0
    if len(good) >= max(cal.MIN_GOOD_FRAMES, n * cal.MIN_GOOD_SHARE):
        height = float(np.median([rows[i]['fy'] - rows[i]['top'] for i in good]))
    if height < cal.MIN_HEIGHT_PX:
        fields = {'feet': None, 'height': 0, 'k0': None, 'aoWidth': 0, 'edgeFrames': []}
        diag = dict(base, found=False, oneShoeFrames=[], fallbackFrames=[], drift=0.0, driftMax=0.0, shoeSpread=0.0,
                    people=0.0, legsRatio=0.0, feetX=[None] * n, feetY=[None] * n, top=[None] * n)
        return fields, diag
    fx = np.array([rows[i]['fx'] for i in good])
    fy = np.array([rows[i]['fy'] for i in good])
    feet_x, feet_y = float(np.median(fx)), float(np.median(fy))
    k0 = round(cal.K0_SCALE * cal.K0_REF_HEIGHT / height, 4)
    # contact-shadow width: the distance between the two shoe soles (median); legs together: the width of the legs
    dists = [rows[i]['dist'] for i in good if rows[i]['dist'] is not None]
    span = (float(np.median(dists)) if len(dists) >= max(cal.MIN_GOOD_FRAMES, cal.ONE_SHOE_SHARE * len(good))
            else float(np.median([rows[i]['width'] for i in good])))
    ao_width = int(round(span * k0 + cal.AO_PAD_PX))
    edge_frames = [i for i in good if rows[i]['edge']]
    # drift: how far apart the feet are across the clip (the 10th to the 90th percentile of their position, x and y
    # together). A slow slide and a late step both spread the position; a hand near the floor that fools the shoe finder
    # for a few frames (under 10 % of them) falls outside the percentiles and does not count.
    lo_x, hi_x = np.percentile(fx, [cal.DRIFT_LOW, cal.DRIFT_HIGH])
    lo_y, hi_y = np.percentile(fy, [cal.DRIFT_LOW, cal.DRIFT_HIGH])
    drift = float(np.hypot(hi_x - lo_x, hi_y - lo_y))
    dev = np.hypot(fx - feet_x, fy - feet_y)
    one_shoe = [i for i in good if rows[i]['shoes'] < 2]
    people = sum(1 for i in good if rows[i]['second'] >= cal.PEOPLE_RATIO) / len(good)
    fields = {'feet': {'x': int(round(feet_x)), 'y': int(round(feet_y))}, 'height': int(round(height)), 'k0': k0,
              'aoWidth': ao_width, 'edgeFrames': edge_frames}
    diag = dict(base, found=True, oneShoeFrames=one_shoe, fallbackFrames=one_shoe, drift=round(drift, 1),
                driftMax=round(float(dev.max()), 1), shoeSpread=round(span, 1), people=round(people, 3),
                legsRatio=round(float(np.median([rows[i]['legs'] for i in good])), 3),
                feetX=[round(rows[i]['fx'], 1) if rows[i] else None for i in range(n)],
                feetY=[round(rows[i]['fy'], 1) if rows[i] else None for i in range(n)],
                top=[rows[i]['top'] if rows[i] else None for i in range(n)])
    return fields, diag


def take_warnings(info, fields, diag):
    """The take check: friendly warnings for the creator, [{code, message}], always in this order.
    info is ft.media.probe()'s dict (w, h and dur as the creator sees the video, hdr); fields and diag come from
    measure() (the edge times use diag['fps'], falling back to info['fps'])."""
    out = []

    def add(code, message):
        out.append({'code': code, 'message': message})

    w, h, dur = info['w'], info['h'], float(info.get('dur') or info.get('duration') or 0)
    if dur < cal.SHORT_S:
        add('short', 'This clip is only %.1f s long. Film at least %g seconds so there is time for the words.'
            % (dur, cal.SHORT_S))
    if dur > cal.MAX_S:
        add('long', 'This clip is just over %g seconds. It still works, but %g seconds or less looks best.'
            % (cal.MAX_S, cal.LONG_S))
    elif dur > cal.LONG_S:
        add('long', 'This clip is %.1f s long. About %g seconds or less works best, and longer clips take longer to '
            'process.' % (dur, cal.LONG_S))
    if w > h:
        add('landscape', 'This video is wide, not tall. Hold your phone upright and film again.')
    if h < cal.LOWRES_H:
        add('lowres', 'This video has a low resolution, so it may look soft. Film at 1080p or better if you can.')
    if abs(w / h - 9 / 16) > cal.ASPECT_TOL:
        add('aspect', "This video isn't the usual tall phone shape (9:16), so the sides may be cropped. Film with the "
            'phone upright.')
    if info.get('hdr'):
        add('hdr', 'This is HDR video. We turn it into standard colors, so it may look a little different from your '
            'phone.')
    ef = fields.get('edgeFrames') or []
    if ef:
        add('edge', 'Part of you touches the edge of the frame %s. Step back a little or zoom out so there is room on '
            'every side.' % _times_text(ef, diag.get('fps') or info.get('fps') or 24))
    legs_lost = diag.get('legsRatio', 0) >= cal.LEGS_RATIO
    if legs_lost:
        add('legs', "We couldn't find your legs and feet, so the words may cover them. Film from a little further back "
            'and less straight down, so your legs show.')
    if not legs_lost and diag.get('drift', 0) > cal.MOVED_PX * (diag.get('width') or 1080) / 1080.0:
        add('moved', 'Your feet move during the clip, so the words may not stay lined up with you. Stand still next '
            'time.')
    if diag.get('people', 0) >= cal.PEOPLE_SHARE:
        add('people', 'It looks like there is more than one person in the frame. floored works best with just you.')
    if diag.get('areaMedian', 1) < cal.NOPERSON_AREA:
        add('noperson', "We couldn't see a person in this clip. Make sure you are in the frame, from head to toe.")
    return out
