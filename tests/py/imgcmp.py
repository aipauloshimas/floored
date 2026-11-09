"""Image comparison for the visual-regression bench, with ffmpeg only."""
import re
import subprocess
from pathlib import Path


def _ffmpeg(args):
    r = subprocess.run(['ffmpeg', '-hide_banner', '-nostdin', '-loglevel', 'info'] + [str(a) for a in args],
                       capture_output=True, text=True, encoding='utf-8', errors='replace')
    if r.returncode:
        raise RuntimeError('ffmpeg failed: ' + r.stderr.strip()[-400:])
    return r.stderr


def ssim(a: Path, b: Path) -> float:
    """Structural similarity of two same-size images (ffmpeg's ssim filter, the 'All:' value; 1.0 = identical)."""
    err = _ffmpeg(['-i', a, '-i', b, '-lavfi', 'ssim', '-f', 'null', '-'])
    m = re.search(r'All:([0-9.]+)', err)
    if not m:
        raise RuntimeError('ffmpeg printed no SSIM: ' + err.strip()[-400:])
    return float(m.group(1))


def downscale(src: Path, dst: Path, w: int, h: int) -> Path:
    """Lanczos resize to w x h, written as PNG."""
    _ffmpeg(['-y', '-i', src, '-vf', 'scale=%d:%d:flags=lanczos' % (w, h), '-frames:v', '1', dst])
    return Path(dst)
