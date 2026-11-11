"""Phone footage: probe a clip, normalise it to the stage video, pick the output tier, make the cutout's proxy.

Whatever a phone gives (HEVC, a rotation flag, HDR/HLG 10-bit, variable frame rate, 120 fps, 20:9 screens) becomes
the stage video the cutout and the export run on: 8-bit yuv420p H.264, constant frame rate, upright, 9:16.

Tier 1 is the 1080x1920 stage; tier 2 is 2160x3840, for a take whose short side is over 1080 px on screen (a 4K phone clip).
"""
import json
import os
import re
from fractions import Fraction

from ft.proc import run, run_lines, tool

STAGE_BASE = (1080, 1920)                       # tier 1; tier t is t times this
STD_RATES = (23.976, 24, 25, 29.97, 30, 50, 59.94, 60)
SNAP = 0.06                                     # a variable rate within 6 % of a usual rate is snapped to it
VFR_GAP = 0.02                                  # r_frame_rate vs avg_frame_rate further apart than 2 % = variable
HDR_TRANSFERS = ('arib-std-b67', 'smpte2084')   # HLG, PQ (HDR10 / Dolby Vision's HDR10 base)

# HDR to SDR, ahead of the scaling. SDR white is put at 203 nits (BT.2408), so a phone's HDR clip keeps the brightness
# it has on its own screen. The tone-mapping is Mobius: linear up to 0.6, so skin and mid-tones keep their brightness
# and only the highlights are rolled off. Chosen on a real phone HDR clip against a reference player's rendering.
HDR_TO_SDR = ('zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=mobius:param=0.6:desat=0,'
              'zscale=t=bt709:m=bt709:r=tv,format=yuv420p')


class PipelineError(Exception):
    """A failure with a message the creator can read."""


# ----------------------------------------------------------------------------------------------------- frame rates

def rate(s):
    """'30000/1001' -> 29.97; '30' -> 30.0; anything unreadable -> 0.0."""
    try:
        a, _, b = str(s).partition('/')
        return float(a) / float(b) if b and float(b) else float(a)
    except (ValueError, ZeroDivisionError):
        return 0.0


def fps_value(f):
    return int(round(f)) if abs(f - round(f)) < 1e-3 else round(f, 3)


def ffmpeg_rate(f):
    """A frame rate as ffmpeg and HyperFrames want it: '24', '30000/1001' (NTSC rates), else a plain fraction ('25/2')."""
    if abs(f - round(f)) < 1e-3:
        return str(int(round(f)))
    for n in (24, 30, 60):
        if abs(f - n * 1000 / 1001) < 0.01:
            return '%d000/1001' % n
    q = Fraction(f).limit_denominator(1001)
    return '%d/%d' % (q.numerator, q.denominator)


# ------------------------------------------------------------------------------------------------------- ffprobe

def is_hdr(transfer, bits):
    """HDR = the stream says its transfer is HLG (arib-std-b67) or PQ (smpte2084) AND it is more than 8 bits deep.
    10-bit SDR (bt709) is not HDR; an 8-bit stream that merely carries an HLG tag is treated as SDR (it cannot hold
    the extra range, and tone-mapping it would only darken it)."""
    return transfer in HDR_TRANSFERS and bits > 8


def _bits(stream):
    try:
        raw = int(stream.get('bits_per_raw_sample') or 0)
    except ValueError:
        raw = 0
    if raw:
        return raw
    m = re.search(r'p(\d+)(?:le|be)?$', stream.get('pix_fmt') or '')     # yuv420p10le -> 10, gbrp12be -> 12
    return int(m.group(1)) if m else 8


def num(value):
    """A number from an ffprobe field: 0.0 for missing, 'N/A' or garbage (never a ValueError)."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def probe(path):
    """Everything the pipeline needs to know about a video file (frames counted by decoding: exact).

    w, h are the DISPLAYED size (rotation applied); rot is the clip's rotation flag (0/90/180/270).
    vfr: r_frame_rate and avg_frame_rate differ by more than 2 % (a phone clip whose timestamps are irregular reports
    the fastest step as r_frame_rate and the true mean as avg_frame_rate).
    transfer: the stream's colour transfer ('arib-std-b67', 'smpte2084', 'bt709'...) or None; bits: 8, 10, 12.
    hdr: see is_hdr()."""
    code, out, err = run([tool('ffprobe'), '-v', 'error', '-select_streams', 'v:0', '-count_frames', '-show_streams',
                          '-show_format', '-of', 'json', str(path)], timeout=180)
    data = json.loads(out) if out.strip() else {}
    streams = data.get('streams') or []
    if code != 0 or not streams:
        raise PipelineError("That file doesn't look like a video we can read. Try an MP4 or MOV.")
    s, fmt = streams[0], data.get('format', {})
    w, h = int(s.get('width') or 0), int(s.get('height') or 0)
    rot = 0
    for sd in s.get('side_data_list') or []:
        if 'rotation' in sd:
            rot = int(round(float(sd['rotation'])))
    if not rot and (s.get('tags') or {}).get('rotate'):
        rot = int(float(s['tags']['rotate']))
    rot %= 360
    if rot in (90, 270):
        w, h = h, w
    r_rate, avg_rate = rate(s.get('r_frame_rate')), rate(s.get('avg_frame_rate'))
    fps = r_rate or avg_rate
    frames = 0
    for key in ('nb_read_frames', 'nb_frames'):
        try:
            frames = int(s.get(key) or 0)
        except ValueError:
            frames = 0
        if frames:
            break
    dur = num(s.get('duration')) or num(fmt.get('duration'))      # 'N/A' or missing (screen recorders, MediaRecorder webm)
    if not frames and fps:
        frames = int(round(dur * fps))
    if not (w and h and fps and frames):
        raise PipelineError("That file doesn't look like a video we can read. Try an MP4 or MOV.")
    if dur <= 0 and frames:
        dur = frames / (avg_rate if (avg_rate and abs(r_rate - avg_rate) / max(r_rate, 1) > VFR_GAP) else fps)
    bitrate = int(num(s.get('bit_rate'))) or int(num(fmt.get('bit_rate')))
    if not bitrate and dur:
        bitrate = int(os.path.getsize(path) * 8 / dur)
    code, aout, _ = run([tool('ffprobe'), '-v', 'error', '-select_streams', 'a:0', '-show_entries', 'stream=codec_name',
                         '-of', 'json', str(path)], timeout=60)
    audio = (json.loads(aout).get('streams') or [{}])[0].get('codec_name') if code == 0 and aout.strip() else None
    transfer = s.get('color_transfer')
    transfer = transfer if transfer and transfer != 'unknown' else None
    bits = _bits(s)
    return {'w': w, 'h': h, 'rot': rot, 'codec': s.get('codec_name'), 'pix_fmt': s.get('pix_fmt'), 'fps': fps,
            'fps_str': s.get('r_frame_rate') or str(fps),
            'vfr': bool(avg_rate) and abs(r_rate - avg_rate) / max(r_rate, 1) > VFR_GAP,
            'avg_fps': avg_rate, 'frames': frames, 'dur': dur, 'bitrate': bitrate, 'audio': audio,
            'hdr': is_hdr(transfer, bits), 'transfer': transfer, 'bits': bits}


# ------------------------------------------------------------------------------------------------ the sound's start

SOUND_SLACK = 0.010                             # a sound starting this close to the picture is "together" with it


def stream_starts(path):
    """The start time (s) of the first picture stream and of the first sound stream of a file, plus the sound's codec
    and the sample rate its header states. A missing or unreadable start time counts as 0.0; no sound stream gives None
    for 'audio'."""
    code, out, _ = run([tool('ffprobe'), '-v', 'error', '-show_entries',
                        'stream=index,codec_type,codec_name,start_time,sample_rate', '-of', 'json', str(path)],
                       timeout=60)
    streams = (json.loads(out).get('streams') or []) if code == 0 and out.strip() else []
    v = next((s for s in streams if s.get('codec_type') == 'video'), {})
    a = next((s for s in streams if s.get('codec_type') == 'audio'), None)
    return {'video': num(v.get('start_time')), 'audio': num(a.get('start_time')) if a else None,
            'rate': (int(num(a.get('sample_rate'))) or 48000) if a else None,
            'codec': a.get('codec_name') if a else None}


def sound_fix(starts):
    """How the take's sound must change so that its time zero is the first picture frame: None when it already is
    (the two start times differ by at most SOUND_SLACK, plus one AAC frame, 1024 samples, because a file written without
    an edit list shows the encoder's priming in the sound's start time), else ('pad', seconds) when the sound starts
    after the picture, ('cut', seconds) when it starts before it. Always the difference of the two start times: a clip
    whose two tracks both start late is not shifted."""
    if starts.get('audio') is None:
        return None
    off = starts['audio'] - starts['video']
    slack = SOUND_SLACK + (1024.0 / starts['rate'] if starts.get('codec') == 'aac' and starts.get('rate') else 0.0)
    if abs(off) <= slack:
        return None
    return ('pad', off) if off > 0 else ('cut', -off)


def sound_filter(fix):
    """The ffmpeg audio filter that realises sound_fix: silence in front ('pad'), or the lead-in cut off ('cut'); the
    output starts at zero. Both are given in time, so ffmpeg counts the samples at the rate it really decodes (a file's
    header can state half of it). adelay takes milliseconds: it reads a fraction with the "s" suffix as milliseconds too."""
    kind, secs = fix
    if kind == 'pad':
        return 'adelay=delays=%.3f:all=1,asetpts=PTS-STARTPTS' % (secs * 1000.0)
    return 'asetpts=PTS-STARTPTS,atrim=start=%.6f,asetpts=PTS-STARTPTS' % secs


# ----------------------------------------------------------------------------------------------------- the stage

def tier(info):
    """1 when the clip's short side, as displayed, is at most 1080 px, else 2 (the 4K tier). A 1920x1080 landscape
    take is a 1080 take and is not upscaled into a 4K stage; a 3840x2160 one is 4K."""
    return 1 if min(info['w'], info['h']) <= STAGE_BASE[0] else 2


def stage_size(t):
    return STAGE_BASE[0] * t, STAGE_BASE[1] * t


def stage_fps(info):
    """The constant frame rate of the stage video.
    A constant-rate clip keeps its rate; a variable-rate one uses its average rate. Above 60 the rate is halved (as
    often as needed: 120 -> 60, 240 -> 60); then a variable rate is snapped to the nearest of 23.976, 24, 25, 29.97,
    30, 50, 59.94, 60 when within 6 % of it, else kept."""
    fps = info['avg_fps'] if info['vfr'] and info['avg_fps'] else info['fps']
    while fps > 60:
        fps /= 2
    if info['vfr']:
        std = min(STD_RATES, key=lambda s: abs(fps - s))
        if abs(fps - std) / std < SNAP:
            fps = std
    return fps


def to_stage(src, dst, info, t, on_line, sound=None):
    """Re-encode to the stage video: rotation applied, HDR tone-mapped to SDR, scaled and letterboxed to
    stage_size(t), constant frame rate (stage_fps), 8-bit yuv420p H.264 CRF 14, AAC 48 kHz stereo 192k, faststart.
    `sound` = the fix from sound_fix: both tracks then start at zero, the clip's own first picture frame, with no frame
    the creator never filmed."""
    w, h = stage_size(t)
    chain = ['setpts=PTS-STARTPTS'] if sound else []
    chain += [HDR_TO_SDR] if info.get('hdr') else []             # ffmpeg rotates by the flag on its own, before this
    chain.append('scale=%d:%d:force_original_aspect_ratio=decrease:flags=lanczos,pad=%d:%d:(ow-iw)/2:(oh-ih)/2:color=black,'
                 'setsar=1,format=yuv420p' % (w, h, w, h))
    cmd = [tool('ffmpeg'), '-y', '-v', 'error', '-nostdin', '-i', str(src), '-map', '0:v:0', '-map', '0:a:0?',
           '-vf', ','.join(chain)]
    if sound:
        cmd += ['-af', sound_filter(sound)]
    cmd += ['-fps_mode', 'cfr', '-r', ffmpeg_rate(stage_fps(info)),
            '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '14', '-pix_fmt', 'yuv420p']
    if info.get('hdr'):                                          # say what the tone-mapping produced
        cmd += ['-color_primaries', 'bt709', '-color_trc', 'bt709', '-colorspace', 'bt709', '-color_range', 'tv']
    cmd += ['-c:a', 'aac', '-b:a', '192k', '-ar', '48000', '-ac', '2', '-movflags', '+faststart', str(dst)]
    code, tail = run_lines(cmd, on_line, timeout=3600)
    if code != 0 or not os.path.exists(dst):
        raise PipelineError("We couldn't convert this clip. Try exporting it again as an MP4.")


def make_proxy(src_webm, dst_webm, fps_str, frames):
    """A 1080x1920 VP9 alpha copy of a (4K) cutout, for the editor's preview; same frame count as the source."""
    cmd = [tool('ffmpeg'), '-y', '-v', 'error', '-nostdin', '-c:v', 'libvpx-vp9', '-i', str(src_webm),
           '-vf', 'scale=%d:%d:flags=lanczos,format=yuva420p' % STAGE_BASE, '-r', str(fps_str),
           '-frames:v', str(frames), '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-crf', '18', '-b:v', '0',
           '-row-mt', '1', '-auto-alt-ref', '0', str(dst_webm)]
    code, tail = run_lines(cmd, lambda line: None, timeout=3600)
    if code != 0 or not os.path.exists(dst_webm):
        raise PipelineError("We couldn't make the preview (%s)." % (tail[-1] if tail else 'ffmpeg failed'))
