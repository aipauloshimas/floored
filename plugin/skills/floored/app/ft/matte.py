"""The person cutout: Robust Video Matting (RVM) on onnxruntime.

  python -m ft.matte SRC DST [--downsample X] [--provider auto|cpu|dml|coreml] [--model PATH]
                             [--matte-only] [--warmup N] [--floor LO HI] [--crf Q]

Output (default): VP9 webm with alpha (yuva420p), same size, fps and frame count as SRC.
  - colour: the original pixel in the core (alpha ~1), RVM's `fgr` on the soft edges (no background fringe round
    blurred fingers);
  - alpha below LO is cut, ramping back to the raw alpha by HI (default 0.03 0.10), so no faint veil of the
    background lands over whatever sits under the cutout.
--matte-only: a grayscale video of the alpha instead (white = person).
--downsample: RVM's internal ratio; `downsample_for(stage_h)` gives 0.75 at 1920 and 0.375 at 3840.
The recurrent state is warmed on the first N frames (default 12) before the real pass.

Progress: `rvm_matte: N frames` every 48 frames; the last line is `rvm_matte: OK ...` only when the output has exactly
the source's frame count and size. Exit codes: 0 OK, 1 mismatch or encode failure, 4 weights missing (the line
`MODEL_MISSING <path>`). The weights are never downloaded here.

People are cut out with RVM only: never u2net, rembg or keying.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np

from ft import paths
from ft.proc import NO_WINDOW, tool

PROVIDER_EP = {'cpu': 'CPUExecutionProvider', 'dml': 'DmlExecutionProvider', 'coreml': 'CoreMLExecutionProvider'}
CPU_EP = PROVIDER_EP['cpu']
PARITY_TOLERANCE = 4 / 255      # a pixel "differs" when CPU and provider alphas are further apart than this
PARITY_WORST = 0.001            # ok when no frame has more than this share of differing pixels


def downsample_for(stage_h):
    """RVM's downsample ratio for a stage of this height: 0.75 at 1080p (1920 tall), 0.375 at 4K (3840 tall)."""
    return 0.75 * 1920 / stage_h


def _available():
    import onnxruntime as ort
    return list(ort.get_available_providers())


def _recorded_provider():
    """`machine.json["matteProvider"]` (written by the doctor after a parity check); cpu when absent or unreadable."""
    try:
        with open(paths.user_dir() / 'machine.json', encoding='utf-8') as f:
            value = json.load(f).get('matteProvider')
    except (OSError, ValueError, AttributeError):
        return 'cpu'
    return value if value in PROVIDER_EP else 'cpu'


def providers(choice):
    """onnxruntime provider list for a choice: cpu; dml/coreml then CPU; auto = what machine.json recorded, else cpu.
    A provider this onnxruntime does not offer falls back to CPU (and says so on stderr)."""
    if choice == 'auto':
        choice = _recorded_provider()
    if choice not in PROVIDER_EP:
        raise ValueError('unknown provider %r' % (choice,))
    if choice == 'cpu':
        return [CPU_EP]
    if PROVIDER_EP[choice] not in _available():
        print('rvm_matte: provider %s is not available in this onnxruntime, using the CPU' % choice,
              file=sys.stderr, flush=True)
        return [CPU_EP]
    return [PROVIDER_EP[choice], CPU_EP]


_telemetry_off = False


def _session(model, provider_list):
    global _telemetry_off
    import onnxruntime as ort
    if not _telemetry_off:                              # the Windows wheels send usage events; nothing may leave the computer
        _telemetry_off = True
        switch = getattr(ort, 'disable_telemetry_events', None)
        if switch:
            switch()
    so = ort.SessionOptions()
    so.intra_op_num_threads = os.cpu_count() or 4
    if provider_list[0] == PROVIDER_EP['dml']:          # DirectML requires these two
        so.enable_mem_pattern = False
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    return ort.InferenceSession(str(model), so, providers=provider_list)


class Matter:
    """One RVM session plus its recurrent state; `step(rgb_uint8_hwc)` -> (fgr float hwc 0..1, alpha float hw 0..1)."""

    def __init__(self, model, provider_list, ratio):
        self.sess = _session(model, provider_list)
        self.ratio = np.array([ratio], np.float32)
        self.rec = [np.zeros((1, 1, 1, 1), np.float32)] * 4

    def step(self, img):
        x = (img.astype(np.float32) / 255).transpose(2, 0, 1)[None]
        fgr, pha, *self.rec = self.sess.run(None, {'src': x, 'r1i': self.rec[0], 'r2i': self.rec[1], 'r3i': self.rec[2],
                                                   'r4i': self.rec[3], 'downsample_ratio': self.ratio})
        return fgr[0].transpose(1, 2, 0), pha[0, 0]


def probe(path, count=False):
    args = [tool('ffprobe'), '-v', 'error']
    if count:
        args += ['-count_frames']
    args += ['-select_streams', 'v:0', '-show_entries',
             'stream=width,height,r_frame_rate' + (',nb_read_frames' if count else ''), '-of', 'json', str(path)]
    out = subprocess.run(args, capture_output=True, text=True, check=True, creationflags=NO_WINDOW).stdout
    return json.loads(out)['streams'][0]


def read_frames(path, w, h, limit=None):
    """Exactly the decoded frames: ffmpeg's default may duplicate or drop frames to force a constant rate (e.g. on a
    stream-copied trim with an edit list), so the matte stays frame-for-frame with the source."""
    cmd = [tool('ffmpeg'), '-v', 'error', '-nostdin', '-i', str(path), '-fps_mode', 'passthrough']
    if limit:
        cmd += ['-frames:v', str(limit)]
    cmd += ['-f', 'rawvideo', '-pix_fmt', 'rgb24', '-']
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
    n = w * h * 3
    try:
        while True:
            b = p.stdout.read(n)
            if len(b) < n:
                break
            yield np.frombuffer(b, np.uint8).reshape(h, w, 3)
    finally:
        p.stdout.close()
        p.kill()
        p.wait()


def _worst_diff_share(a, b):
    """Over frames: the largest share of pixels where the two alpha stacks (n, h, w, floats 0..1) differ by more than
    4/255."""
    worst = 0.0
    for x, y in zip(a, b):
        worst = max(worst, float((np.abs(x - y) > PARITY_TOLERANCE + 1e-6).mean()))
    return worst


def parity(src, provider, frames=12, model=None):
    """Run the first `frames` frames through the CPU and through `provider` (cpu/dml/coreml); compare the alphas.
    {"ok": worst <= 0.001, "worst": largest share of pixels differing by more than 4/255 on any frame}."""
    model = model or paths.rvm_model_path()
    if provider != 'cpu' and providers(provider)[0] == CPU_EP:
        # the runtime lacks this provider: comparing the CPU with itself would pass for nothing
        return {'ok': False, 'worst': 1.0, 'reason': 'provider %s is not available in this onnxruntime' % provider}
    s = probe(src)
    w, h = int(s['width']), int(s['height'])
    ratio = downsample_for(h)
    cpu = Matter(model, [CPU_EP], ratio)
    other = Matter(model, providers(provider), ratio)
    worst, n = 0.0, 0
    for img in read_frames(src, w, h, limit=frames):
        _, a = cpu.step(img)
        _, b = other.step(img)
        worst = max(worst, _worst_diff_share([a], [b]))
        n += 1
    if n == 0:
        return {'ok': False, 'worst': 1.0}
    return {'ok': worst <= PARITY_WORST, 'worst': worst}


def main(argv=None):
    ap = argparse.ArgumentParser(prog='python -m ft.matte', description='Cut the person out of a video with RVM.')
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--matte-only', action='store_true', help='write a grayscale alpha video instead of RGBA')
    ap.add_argument('--downsample', type=float, default=None)
    ap.add_argument('--provider', choices=['auto', 'cpu', 'dml', 'coreml'], default='auto')
    ap.add_argument('--model', default=None, help='path to the cutout model file (default: FLOORED_RVM_MODEL, else the file in ~/.cache/rvm)')
    ap.add_argument('--warmup', type=int, default=12)
    ap.add_argument('--floor', type=float, nargs=2, default=(0.03, 0.10), metavar=('LO', 'HI'))
    ap.add_argument('--crf', type=int, default=12)
    a = ap.parse_args(argv)

    model = a.model or paths.rvm_model_path()
    if not os.path.isfile(model):
        print('MODEL_MISSING %s' % model, file=sys.stderr, flush=True)
        return 4

    s = probe(a.src)
    W, H, fps = int(s['width']), int(s['height']), s['r_frame_rate']
    ratio = a.downsample or min(1.0, 576.0 / max(W, H))
    lo, hi = a.floor
    matter = Matter(model, providers(a.provider), ratio)

    for k, img in enumerate(read_frames(a.src, W, H)):        # warm the recurrent state on the first frames
        matter.step(img)
        if k + 1 >= a.warmup:
            break

    if a.matte_only:
        enc_in = ['-f', 'rawvideo', '-pix_fmt', 'gray', '-s', '%dx%d' % (W, H), '-r', fps, '-i', '-']
        ext = os.path.splitext(a.dst)[1].lower()
        enc_out = (['-c:v', 'libx264', '-crf', str(a.crf), '-pix_fmt', 'yuv420p'] if ext in ('.mp4', '.mov')
                   else ['-c:v', 'libvpx-vp9', '-crf', str(a.crf), '-b:v', '0', '-pix_fmt', 'yuv420p', '-row-mt', '1'])
    else:
        enc_in = ['-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', '%dx%d' % (W, H), '-r', fps, '-i', '-']
        enc_out = ['-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-crf', str(a.crf), '-b:v', '0', '-row-mt', '1',
                   '-deadline', 'good', '-cpu-used', '2', '-auto-alt-ref', '0']
    enc = subprocess.Popen([tool('ffmpeg'), '-v', 'error', '-y'] + enc_in + enc_out + ['-an', str(a.dst)],
                           stdin=subprocess.PIPE, creationflags=NO_WINDOW)
    n = 0
    for img in read_frames(a.src, W, H):
        fgr, pha = matter.step(img)
        al = np.clip(pha, 0, 1)
        al = np.where(al < lo, 0, np.where(al < hi, (al - lo) / (hi - lo) * al, al))
        a8 = (al * 255 + 0.5).astype(np.uint8)
        if a.matte_only:
            enc.stdin.write(a8.tobytes())
        else:
            w = np.clip((al - 0.9) / 0.08, 0, 1)[..., None]      # core: original pixel; edge: RVM's clean colour
            rgb = img.astype(np.float32) * w + np.clip(fgr * 255, 0, 255) * (1 - w)
            enc.stdin.write(np.dstack([rgb.astype(np.uint8), a8]).tobytes())
        n += 1
        if n % 48 == 0:
            print('rvm_matte: %d frames' % n, file=sys.stderr, flush=True)
    enc.stdin.close()
    if enc.wait() != 0:
        print('rvm_matte: ffmpeg encode failed', file=sys.stderr, flush=True)
        return 1

    src_n = int(probe(a.src, count=True)['nb_read_frames'])
    dec = ['-c:v', 'libvpx-vp9'] if str(a.dst).lower().endswith('.webm') else []
    out = json.loads(subprocess.run([tool('ffprobe'), '-v', 'error'] + dec + ['-count_frames', '-select_streams', 'v:0',
                                     '-show_entries', 'stream=width,height,nb_read_frames', '-of', 'json', str(a.dst)],
                                    capture_output=True, text=True, check=True, creationflags=NO_WINDOW).stdout)['streams'][0]
    ok = int(out['nb_read_frames']) == src_n == n and int(out['width']) == W and int(out['height']) == H
    print('rvm_matte: %s %dx%d @%s, %d frames (source %d) -> %s' % ('OK' if ok else 'MISMATCH', W, H, fps, n, src_n, a.dst),
          flush=True)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
