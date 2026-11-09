"""Per-frame alpha stats of an RVM cutout: height, feet point (midpoint of the two shoe soles), drift, edge contact.
Usage: python -I measure_take.py <person.webm> [W H]
"""
import subprocess, sys
import numpy as np

src = sys.argv[1]
W, H = (int(sys.argv[2]), int(sys.argv[3])) if len(sys.argv) > 3 else (1080, 1920)
p = subprocess.Popen(['ffmpeg', '-loglevel', 'error', '-c:v', 'libvpx-vp9', '-i', src, '-vf', 'alphaextract',
                      '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], stdout=subprocess.PIPE)
rows = []
n = 0
while True:
    buf = p.stdout.read(W * H)
    if len(buf) < W * H:
        break
    a = np.frombuffer(buf, np.uint8).reshape(H, W)
    m = a > 128
    ys, xs = np.nonzero(m)
    top, bot, left, right = ys.min(), ys.max(), xs.min(), xs.max()
    # the two shoes: columns opaque in the bottom 260 px of the silhouette, split at the widest gap
    band = m[bot - 260:bot + 1]
    cols = np.nonzero(band.any(axis=0))[0]
    gaps = np.diff(cols)
    g = int(np.argmax(gaps)) if len(gaps) else 0
    if len(gaps) and gaps[g] > 8:
        shoes = [cols[:g + 1], cols[g + 1:]]
    else:
        shoes = [cols]
    soles = []
    for c in shoes:
        sub = m[:, c.min():c.max() + 1]
        yb = np.nonzero(sub.any(axis=1))[0].max()          # lowest opaque row of this shoe
        xb = np.nonzero(sub[yb - 6:yb + 1].any(axis=0))[0]  # its sole, a few rows up
        soles.append((c.min() + xb.mean(), yb))
    fx = float(np.mean([s[0] for s in soles]))
    fy = float(np.mean([s[1] for s in soles]))
    edge = dict(l=int((a[:, 0] > 16).sum()), r=int((a[:, -1] > 16).sum()), t=int((a[0] > 16).sum()), b=int((a[-1] > 16).sum()))
    rows.append((n, top, bot, left, right, fx, fy, len(soles), soles, edge))
    n += 1
p.wait()

print('frames', n)
arr = np.array([(r[1], r[2], r[3], r[4], r[5], r[6]) for r in rows], float)
for name, col in zip(['top', 'bottom', 'left', 'right', 'feet_x', 'feet_y'], arr.T):
    print('%-7s min %6.0f  median %6.0f  max %6.0f' % (name, col.min(), np.median(col), col.max()))
print('height (bottom - top) median %.0f' % np.median(arr[:, 1] - arr[:, 0]))
print('height (feet_y - top) median %.0f' % np.median(arr[:, 5] - arr[:, 0]))
one = [r[0] for r in rows if r[7] < 2]
print('frames where only one shoe was found:', one[:20], '...' if len(one) > 20 else '')
for r in rows[::10]:
    print('f%03d soles %s edge %s' % (r[0], [(round(x), int(y)) for x, y in r[8]], r[9]))
touch = [r[0] for r in rows if any(v > 0 for v in r[9].values())]
print('frames touching the frame edge:', len(touch), touch[:30])
