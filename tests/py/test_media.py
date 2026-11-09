"""Phone footage normalisation (ft.media): rotation, HEVC, HDR, VFR, 120 fps, 20:9, the 4K tier, the alpha proxy."""
import json
import subprocess

import pytest

from ft.media import is_hdr, make_proxy, probe, stage_fps, stage_size, tier, to_stage
from ft.proc import tool


def _ff(*args):
    r = subprocess.run([tool('ffmpeg'), '-y', '-v', 'error', '-nostdin', *map(str, args)], capture_output=True)
    assert r.returncode == 0, r.stderr.decode('utf-8', 'replace')


def _stream(path, kind='v:0'):
    r = subprocess.run([tool('ffprobe'), '-v', 'error', '-select_streams', kind, '-show_streams', '-of', 'json', str(path)],
                       capture_output=True, text=True)
    streams = json.loads(r.stdout)['streams']
    return streams[0] if streams else None


def _mean_luma(path, crop):
    """Average luma (0..255) of a crop 'w:h:x:y' of the first frame."""
    r = subprocess.run([tool('ffmpeg'), '-v', 'error', '-nostdin', '-i', str(path), '-frames:v', '1', '-vf',
                        'crop=%s,scale=1:1:flags=area,format=gray' % crop, '-f', 'rawvideo', '-'], capture_output=True)
    assert r.returncode == 0 and len(r.stdout) == 1, r.stderr
    return r.stdout[0]


def _convert(src, dst, t=1):
    info = probe(src)
    lines = []
    to_stage(src, dst, info, t, lines.append)
    assert dst.exists(), lines
    return info, probe(dst)


def test_rotated_iphone_is_portrait(iphone_rot):
    assert (probe(iphone_rot)["w"], probe(iphone_rot)["h"]) == (1080, 1920)
    assert probe(iphone_rot)["rot"] in (90, 270)


def _gray(path, vf, size=(54, 96)):
    """First frame as a small grayscale byte string (vf runs first, then a scale to size)."""
    r = subprocess.run([tool('ffmpeg'), '-v', 'error', '-nostdin', '-i', str(path), '-frames:v', '1', '-vf',
                        '%sscale=%d:%d:flags=area,format=gray' % (vf, *size), '-f', 'rawvideo', '-'], capture_output=True)
    assert r.returncode == 0 and len(r.stdout) == size[0] * size[1], r.stderr
    return r.stdout


def _differs_from_upright(stage, stored):
    """Mean absolute luma difference (0..255) between a stage video and the stored landscape picture turned upright by
    hand: transpose=2 is 90 degrees counter-clockwise, which is what a display matrix of 90 means."""
    a, b = _gray(stage, ''), _gray(stored, 'transpose=2,')
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def test_rotation_is_applied_to_the_stage(iphone_rot, landscape_1080, tmp_path):
    info, out = _convert(iphone_rot, tmp_path / "s.mp4")
    assert (out["w"], out["h"]) == (1080, 1920) and out["rot"] == 0
    assert _differs_from_upright(tmp_path / "s.mp4", landscape_1080) < 8             # same picture as the hand-turned one
    assert _mean_luma(tmp_path / "s.mp4", "100:1920:0:0") > 80                        # left edge is picture, not black bars


def test_rotation_check_catches_a_clip_left_unrotated(landscape_1080, tmp_path):
    """Negative control: with no rotation flag the stage is letterboxed landscape, and the check above must say so."""
    info, out = _convert(landscape_1080, tmp_path / "s.mp4")
    assert (out["w"], out["h"]) == (1080, 1920)                                      # same size, wrong picture
    assert _differs_from_upright(tmp_path / "s.mp4", landscape_1080) > 30
    assert _mean_luma(tmp_path / "s.mp4", "100:1920:0:0") < 60


def test_tier(hevc_4k, portrait_1080):
    assert tier(probe(hevc_4k)) == 2 and tier(probe(portrait_1080)) == 1
    assert tier({"w": 1920, "h": 1080}) == 1                                # a 1080p landscape take is a 1080 take
    assert tier({"w": 3840, "h": 2160}) == 2                                # a 4K landscape take is a 4K take
    assert tier({"w": 1080, "h": 2400}) == 1 and tier({"w": 2160, "h": 3840}) == 2
    assert stage_size(1) == (1080, 1920) and stage_size(2) == (2160, 3840)


def test_4k_stage_keeps_resolution(hevc_4k, tmp_path):
    info, out = _convert(hevc_4k, tmp_path / "s.mp4", t=2)
    assert info["codec"] == "hevc"
    assert (out["w"], out["h"]) == (2160, 3840)
    assert out["codec"] == "h264" and out["pix_fmt"] == "yuv420p"


def test_hlg_is_tonemapped(hlg_10bit, tmp_path):
    src = probe(hlg_10bit)
    assert src["hdr"] and src["transfer"] == "arib-std-b67" and src["bits"] == 10
    info, out = _convert(hlg_10bit, tmp_path / "s.mp4")
    assert out["pix_fmt"] == "yuv420p" and out["bits"] == 8 and not out["hdr"]
    assert out["transfer"] in ("bt709", None)
    assert (out["w"], out["h"]) == (1080, 1920)
    assert _mean_luma(tmp_path / "s.mp4", "1080:200:0:0") > 20            # tone-mapped, not crushed to black


def test_hdr_rule():
    assert is_hdr("arib-std-b67", 10) and is_hdr("smpte2084", 10)         # HLG and PQ
    assert not is_hdr("bt709", 10)                                        # 10-bit SDR is not HDR
    assert not is_hdr("bt709", 8) and not is_hdr(None, 8)
    assert not is_hdr("arib-std-b67", 8)                                  # an 8-bit HLG tag is not a real HDR clip


def test_sdr_clip_is_not_hdr(portrait_1080):
    info = probe(portrait_1080)
    assert not info["hdr"] and info["bits"] == 8


def test_vfr_becomes_cfr(vfr, tmp_path):
    src = probe(vfr)
    assert src["vfr"]
    info, out = _convert(vfr, tmp_path / "s.mp4")
    assert not out["vfr"] and out["fps"] == 30


def test_cfr_clip_is_not_vfr(portrait_1080, fps120):
    assert not probe(portrait_1080)["vfr"] and not probe(fps120)["vfr"]


def test_120_halves_to_60(fps120):
    assert stage_fps(probe(fps120)) == 60


def test_stage_fps_rules():
    base = {"fps": 30.0, "avg_fps": 30.0, "vfr": False}
    assert stage_fps(dict(base, fps=29.97, avg_fps=29.97)) == pytest.approx(29.97)      # constant rates are kept
    assert stage_fps(dict(base, fps=119.88, avg_fps=119.88)) == pytest.approx(59.94)
    assert stage_fps(dict(base, fps=240.0, avg_fps=240.0)) == 60                         # halved until <= 60
    assert stage_fps(dict(base, fps=60.0, avg_fps=28.4, vfr=True)) == pytest.approx(29.97)  # 5.2% off: snap to nearest
    assert stage_fps(dict(base, fps=60.0, avg_fps=30.4, vfr=True)) == 30                 # nearest standard rate
    assert stage_fps(dict(base, fps=120.0, avg_fps=119.0, vfr=True)) == pytest.approx(59.94)  # halve first, then snap
    assert stage_fps(dict(base, fps=60.0, avg_fps=45.0, vfr=True)) == 45                 # nothing within 6%: keep


def test_tall_is_letterboxed(tall_20_9, tmp_path):
    info, out = _convert(tall_20_9, tmp_path / "s.mp4")
    assert (info["w"], info["h"]) == (1080, 2400)
    assert (out["w"], out["h"]) == (1080, 1920)
    # 1080x2400 fits 864x1920: black bars left and right, picture in the middle
    assert _mean_luma(tmp_path / "s.mp4", "100:1920:0:0") < 20
    assert _mean_luma(tmp_path / "s.mp4", "100:600:490:0") > 40


def test_audio_is_aac_48k_stereo(portrait_1080, tmp_path):
    _convert(portrait_1080, tmp_path / "s.mp4")
    a = _stream(tmp_path / "s.mp4", "a:0")
    assert a["codec_name"] == "aac" and a["sample_rate"] == "48000" and a["channels"] == 2


def test_no_audio_stays_silent(no_audio, tmp_path):
    info, out = _convert(no_audio, tmp_path / "s.mp4")
    assert info["audio"] is None and out["audio"] is None


def test_clip_12s(clip_12s):
    assert 11.9 < probe(clip_12s)["dur"] < 12.1


def test_proxy_keeps_frames(tmp_path):
    big = tmp_path / "big.webm"
    _ff("-f", "lavfi", "-i", "color=c=red@0.5:s=2160x3840:r=24:d=0.5,format=yuva420p", "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuva420p", "-deadline", "realtime", "-cpu-used", "8", "-b:v", "0", "-crf", "40", "-auto-alt-ref", "0", big)
    proxy = tmp_path / "proxy.webm"
    make_proxy(big, proxy, "24", 12)
    a, b = probe(big), probe(proxy)
    assert (a["w"], a["h"], a["frames"]) == (2160, 3840, 12)
    assert (b["w"], b["h"], b["frames"]) == (1080, 1920, 12)
    r = subprocess.run([tool('ffmpeg'), '-v', 'error', '-nostdin', '-c:v', 'libvpx-vp9', '-i', str(proxy), '-frames:v', '1',
                        '-vf', 'alphaextract,scale=1:1:flags=area', '-pix_fmt', 'gray', '-f', 'rawvideo', '-'], capture_output=True)
    assert r.returncode == 0 and 100 < r.stdout[0] < 150                  # alpha kept (0.5 -> ~128), not dropped to opaque


def test_fractional_rates_are_written_as_fractions_that_export_and_hyperframes_accept():
    from fractions import Fraction
    from ft import export
    from ft.media import ffmpeg_rate
    assert ffmpeg_rate(24) == '24' and ffmpeg_rate(30.0004) == '30'
    assert ffmpeg_rate(23.976) == '24000/1001' and ffmpeg_rate(29.97) == '30000/1001' and ffmpeg_rate(59.94) == '60000/1001'
    assert ffmpeg_rate(12.5) == '25/2' and ffmpeg_rate(29.5) == '59/2'
    assert ffmpeg_rate(14.985) == '2997/200'
    for f, want in ((12.5, Fraction(25, 2)), (29.5, Fraction(59, 2)), (14.985, Fraction(2997, 200)), (29.97, Fraction(30000, 1001))):
        s = ffmpeg_rate(f)
        assert export.parse_rate(s) == want                                       # the post-render check reads it
        assert export.parse_rate(export.fps_arg(f)) == want                       # and so does HyperFrames' --fps (n/d or integer)
        assert all(c in '0123456789/' for c in s)
