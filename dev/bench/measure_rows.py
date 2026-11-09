"""Objective check for the font sheet: map the red ink of each font snapshot back to floor-plane coordinates
(inverse of the engine's camera: translate3d / rotateX / scale / perspective 2000 @ (540,150), para rotate(-theta)) and report
where the ink of wall row c1 (cap top should be para y -150, baseline -150 + 0.86*360 = 159.6) really sits."""
import math, sys, json
import numpy as np
from PIL import Image
S_, A_, AX, AY, THETA = 0.62, 38.0, 545.0, 1150.0, 29.0     # camera 'still', wall layout
TOP, BASE = -150.0, -150.0 + 0.86 * 360
def to_local(X, Y):
    a = math.radians(A_)
    u = 2000.0 * (Y - AY) / ((Y - 150.0) * math.sin(a) + 2000.0 * math.cos(a))      # fy * S
    k = 2000.0 / (2000.0 - u * math.sin(a))
    sx = (540.0 + (X - 540.0) / k) - AX
    fx, fy = sx / S_, u / S_
    t = math.radians(THETA)
    return fx * math.cos(t) - fy * math.sin(t), fx * math.sin(t) + fy * math.cos(t)
out = {}
for font in ['condensed', 'serif', 'geo', 'mono', 'stencil', 'hand']:
    im = np.asarray(Image.open('font-%s/snaps/at-3s.png' % font).convert('RGB')).astype(int)
    R, G, B = im[..., 0], im[..., 1], im[..., 2]
    mask = (R > 150) & (G < 100) & (B < 100)
    ys, xs = np.nonzero(mask)
    X = xs.astype(float) + 0.5; Y = ys.astype(float) + 0.5
    a = math.radians(A_)
    u = 2000.0 * (Y - AY) / ((Y - 150.0) * math.sin(a) + 2000.0 * math.cos(a))
    k = 2000.0 / (2000.0 - u * math.sin(a))
    sx = (540.0 + (X - 540.0) / k) - AX
    fx, fy = sx / S_, u / S_
    t = math.radians(THETA)
    px = fx * math.cos(t) - fy * math.sin(t); py = fx * math.sin(t) + fy * math.cos(t)
    sel = (px > 300) & (px < 1400) & (py > -162) & (py < 172)
    p = py[sel]
    n = int(sel.sum())
    lo, hi = np.percentile(p, [0.15, 99.85]) if n else (float('nan'),) * 2
    out[font] = dict(ink_px=n, top=round(float(lo), 1), bottom=round(float(hi), 1), dtop=round(float(lo) - TOP, 1), dbase=round(float(hi) - BASE, 1))
    # gap check: ink between c0's baseline (-170.4) and c1's cap top (-150) -> only overshoot allowed; ink between c1 baseline and c2 cap top (180)
    g1 = (px > 300) & (px < 1400) & (py > -168) & (py < -152)
    g2 = (px > 300) & (px < 1400) & (py > 162) & (py < 176)
    out[font]['ink_in_gap_above'] = int(g1.sum()); out[font]['ink_in_gap_below'] = int(g2.sum())
print(json.dumps(out, indent=1))
print('expected: top %.1f  baseline %.1f   (cap size 360, 0.86 box)' % (TOP, BASE))
