"""floored: export. Fills the composition template, renders it with HyperFrames, builds and mixes the sound.

    Exporter(pipe).submit(take_id, settings, events) -> export id      (POST /api/export)
    Exporter.status(id) -> {id, stage, progress, message, file, path, ...}   (GET /api/exports/<id>)

Stages (progress 0..1 inside each stage, like the take pipeline): writing -> rendering -> sound -> done | error.
One export at a time. Everything lands in exports/<stamp>/:

    index.html, assets/...       the filled composition (SPEC "Export template")
    render.mp4                   HyperFrames' near-lossless render (CRF 8)
    video.mp4                    our own encode of it (x264 CRF 14, or two-pass at the floor), picture only
    sfx.wav, premix.wav          the synthesised effects, and voice + effects before loudness normalisation
    (all of these, and assets/, are deleted once the export passed its check; a failed export keeps them for the log)
    <take name> - floored.mp4 the result (video copied, AAC 192k, about -14 LUFS)
    job.json, status.json, export.log

Renders keep the take's quality, from take.json's `out`: the take's size (1080x1920, or 2160x3840 for a 4K take), its
frame rate, H.264, video bitrate at least max(upload bitrate, 8 Mbps). The picture is made in two steps, because a
bitrate-mode encode drops the faint, frame-varying film grain of some looks (dev/notes/acceptance-2026-11-09.md, section 4):
HyperFrames renders a near-lossless intermediate (`--crf 8`), then ffmpeg encodes it at constant quality (x264 CRF 14,
preset slow). When that comes out below the floor (flat looks), the same intermediate is encoded again, two-pass, at the
floor plus 5 %. The composition keeps the 1080 layout; a 4K take
is rendered with HyperFrames' own `--resolution portrait-4k` (Chrome at device scale 2) over the full-resolution cutout
(`take.files.person`). The renderer is the locally installed, pinned HyperFrames (renderer_bin(); never npx), run with the
telemetry opt-out so a finished setup works offline. Before `done` the file is probed (check_output): size, frame rate,
frame count, video bitrate and loudness must match the take, or the export ends in `error` and says so.
"""
import json
import math
import os
import queue
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
import traceback
import urllib.parse
from fractions import Fraction

from ft import paths, proc, sfx
from ft.pipeline import now_iso, read_json, write_json
from ft.proc import NO_WINDOW, run

ENGINE = os.environ.get('FT_ENGINE_DIR') or str(paths.WEB_DIR / 'engine')    # env: tests only
TEMPLATE = os.path.join(ENGINE, 'composition.html')
ENGINE_FILES = ['data.js', 'metrics.js', 'layout.js', 'engine.js', 'engine.css', 'gsap.min.js']   # GSAP 3.14.2 bundled: exports work offline
HYPERFRAMES_VERSION = '0.9.22'              # pinned: Task 19 installs exactly this into <user dir>/renderer
RENDERER_MISSING = "The video maker isn't installed yet. Ask Claude to finish the setup."
CHECK_FAILED = ("The export didn't come out at your take's quality, so we stopped. Try again, and if it keeps happening, "
                "ask Claude for help.")
DEFAULT_RENDER_SEC_PER_FRAME = {'1': 1.3, '2': 2.7}   # wall-clock s per frame until this machine has a measured value
CHROME_PATH_BUDGET = 200       # characters; Windows stops at 260 and HyperFrames then exits with no message (renderer.md)
MIN_MBPS = 8
INTERMEDIATE_CRF = 8           # HyperFrames' render: near-lossless H.264, so the grain reaches our own encode intact
ENCODE_CRF = 14                # our encode of it: constant quality, which keeps the grain (a bitrate-mode encode freezes it)
ENCODE_PRESET = 'slow'
BITRATE_MARGIN = 1.05      # ask the encoder for 5 % more than the floor: x264 averages ~1-2 % under what it is asked
SR = 48000
LUFS, TRUE_PEAK, LRA = -14.0, -1.0, 11.0
SFX_UNDER_VOICE_DB = 6.0
# data.js (FT_DATA.FONTS[id].file) is the source of truth; this copy is only used when that file cannot be parsed
FONT_FILES = {'condensed': 'anton.woff2', 'serif': 'serif.woff2', 'geo': 'geo.woff2', 'mono': 'mono.woff2',
              'stencil': 'stencil.woff2', 'hand': 'gochihand.woff2'}
RENDER_TIMEOUT = 25 * 60        # the least a render is given; render_timeout() lets long and 4K takes have more
TIMEOUT_MARGIN = 3              # x the slowest known seconds-per-frame (stored or default), so a slow PC is not cut off
RENDER_SHARE = 0.7             # the render fills the progress bar up to here, the encode the rest
CHECK_TIMEOUT = 150
SKIP_CHECK = os.environ.get('FT_SKIP_CHECK', '1') == '1'   # `hyperframes check` only logs and adds 1-2 min; FT_SKIP_CHECK=0 runs it
LUFS_TOLERANCE = 1.0
EXPORT_ID = re.compile(r'[0-9]{8}-[0-9]{6}-[0-9a-f]{4}')
IS_NT = os.name == 'nt'
HELPER_TIMEOUT = 600           # seconds an ffprobe / ffmpeg helper may take (probes, loudness, the mix) before it counts as hung
HELPER_TIMEOUT_COPY = "The video took too long to process, so we stopped. Try again, and if it keeps happening, ask Claude for help."
TOOLS_MISSING = "The video tools aren't installed yet. Ask Claude to finish the setup."
SILENT_VOICE_DB = -60.0        # a voice track whose loudest sample is under this counts as no voice (nothing to normalise to -14 LUFS)
NO_LOUDNESS_LUFS = -70.0       # loudnorm's pass 1 reading at or under this (or -inf) means the same


class ExportError(Exception):
    def __init__(self, message, code=400, detail=None):
        super().__init__(message)
        self.code = code
        self.detail = detail                    # numbers for export.log that the creator does not need to read


# -- small helpers -------------------------------------------------------------------------------------------------
def font_file(font_id):
    """File name of a font id, read from engine/data.js (FT_DATA.FONTS), or None for an unknown id."""
    if not isinstance(font_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,40}', font_id):
        return None
    try:
        with open(os.path.join(ENGINE, 'data.js'), encoding='utf-8') as f:
            text = f.read()
        text = text[text.find('FONTS'):]
        m = re.search(r"\b%s\s*:\s*\{[^}]*?\bfile\s*:\s*['\"]([^'\"]+)['\"]" % re.escape(font_id), text)
        if m:
            return m.group(1)
    except OSError:
        pass
    return FONT_FILES.get(font_id)


def safe_filename(name):
    name = re.sub(r'[\x00-\x1f<>:"/\\|?*]', ' ', str(name or 'Take'))
    name = re.sub(r'\s+', ' ', name).strip(' .')
    return (name or 'Take')[:80].strip(' .')


def fps_arg(fps):
    """HyperFrames --fps wants an integer or an ffmpeg-style rational."""
    if abs(fps - round(fps)) < 0.002:
        return str(int(round(fps)))
    for n in (24000, 30000, 60000):
        if abs(fps - n / 1001.0) < 0.002:
            return '%d/1001' % n
    f = Fraction(fps).limit_denominator(1001)
    return '%d/%d' % (f.numerator, f.denominator)


def num_text(x, places=3):
    return ('%.*f' % (places, x)).rstrip('0').rstrip('.') or '0'


def js_literal(obj):
    """JSON that is safe inside an inline <script>."""
    return (json.dumps(obj, ensure_ascii=False).replace('</', '<\\/').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029'))


# -- the renderer and the take's quality ----------------------------------------------------------------------------
def renderer_dir():
    """Where Task 19's setup installs HyperFrames: <user dir>/renderer. FLOORED_RENDERER_DIR moves it (tests only)."""
    env = os.environ.get('FLOORED_RENDERER_DIR')
    return os.path.abspath(os.path.expanduser(env)) if env else str(paths.user_dir() / 'renderer')


def renderer_bin():
    """The local, pinned HyperFrames as an argument list. Never npx: a missing install is an error, not a download."""
    exe = os.path.join(renderer_dir(), 'node_modules', '.bin', 'hyperframes.cmd' if os.name == 'nt' else 'hyperframes')
    if not os.path.isfile(exe):
        raise ExportError(RENDERER_MISSING, 503)
    return [exe]


def renderer_env():
    """The environment of every HyperFrames call: no telemetry, no update check (dev/notes/renderer.md), and a short
    Chrome cache when the default one would be too deep for Windows' 260-character limit. The folders of the node and
    ffmpeg that the setup recorded (config.json "tools") go first on PATH: right after a winget or brew install this
    shell's PATH is stale, and HyperFrames starts both of them by name."""
    env = dict(os.environ, HYPERFRAMES_NO_TELEMETRY='1', DO_NOT_TRACK='1', HYPERFRAMES_NO_UPDATE_CHECK='1')
    folders = []
    for name in ('node', 'ffmpeg'):
        try:
            folder = os.path.dirname(proc.tool(name))
        except proc.MissingTool:
            continue
        if folder not in folders:
            folders.append(folder)
    if folders:
        env['PATH'] = os.pathsep.join(folders + [env.get('PATH', '')])
    if not env.get('HYPERFRAMES_CACHE_DIR') and os.name == 'nt':
        deepest = os.path.join(os.path.expanduser('~'), '.cache', 'hyperframes', 'chrome', 'chrome-headless-shell',
                               'win64-152.0.7977.30', 'chrome-headless-shell-win64', 'chrome-headless-shell.exe')
        if len(deepest) > CHROME_PATH_BUDGET:
            env['HYPERFRAMES_CACHE_DIR'] = str(paths.user_dir() / 'hf-cache')
    return env


def out_spec(take):
    """take.json's `out` {w, h, fps, fpsStr, bitrate}; a take written before it existed gets it from w, h, fps, bitrate."""
    out = take.get('out') if isinstance(take.get('out'), dict) else {}
    fps = float(out.get('fps') or take.get('fps') or 0)
    return {'w': int(out.get('w') or take.get('w') or 1080), 'h': int(out.get('h') or take.get('h') or 1920), 'fps': fps,
            'fpsStr': str(out.get('fpsStr') or fps_arg(fps)),
            'bitrate': int(out.get('bitrate') or take.get('bitrate') or 0)}


def take_files(take):
    """take.json's `files` {person, shadow, audio}; the plain names when a take has none."""
    files = take.get('files') if isinstance(take.get('files'), dict) else {}
    return {'person': files.get('person') or 'person.webm', 'shadow': files.get('shadow') or 'shadow.webm',
            'audio': files['audio'] if 'audio' in files else ('audio.m4a' if take.get('hasAudio') else None)}


def floor_mbps(bitrate):
    """The floor in Mbps: the larger of the take's bitrate and 8 Mbps."""
    return max(float(bitrate or 0), MIN_MBPS * 1e6) / 1e6


def abr_bitrate(bitrate):
    """Bits per second for the floor re-encode: ceil(max(take, 8 Mbps) x 1.05)."""
    return int(math.ceil(max(float(bitrate or 0), MIN_MBPS * 1e6) * BITRATE_MARGIN - 1e-6))


def render_cmd(base, comp_dir, dest, out):
    """The HyperFrames render of the intermediate: near-lossless CRF, never `--video-bitrate`. `base` is renderer_bin()."""
    cmd = list(base) + ['render', comp_dir, '-o', dest, '--fps', out['fpsStr'], '--crf', str(INTERMEDIATE_CRF),
                        '--player-ready-timeout', '120000']
    if out['h'] > 1920:                                  # 4K: HyperFrames' own device-scale flag (dev/notes/renderer.md (d))
        cmd += ['--resolution', 'portrait-4k']
    return cmd


def _tool(name):
    """ffmpeg / ffprobe as the setup recorded them (config.json "tools"), else PATH: a stale PATH must not break an export."""
    try:
        return proc.tool(name)
    except proc.MissingTool:
        raise ExportError(TOOLS_MISSING, 503)


def _run(cmd, timeout=HELPER_TIMEOUT):
    """run() with a deadline: a hung ffprobe / ffmpeg becomes an ExportError (friendly copy; the numbers go to the log)."""
    try:
        return run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ExportError(HELPER_TIMEOUT_COPY, 500,
                          detail='%s timed out after %d s: %s' % (os.path.basename(str(cmd[0])), timeout, ' '.join(map(str, cmd))))


def _x264_head(src):
    return [_tool('ffmpeg'), '-hide_banner', '-nostdin', '-y', '-progress', 'pipe:1', '-nostats', '-i', src, '-map', '0:v:0', '-an',
            '-fps_mode', 'passthrough', '-c:v', 'libx264', '-preset', ENCODE_PRESET, '-pix_fmt', 'yuv420p']


# what HyperFrames wrote before this step existed (ffprobe of its mp4): High profile, yuv420p, limited range, BT.709 everywhere
# (ffmpeg 8.1 drops the -color_primaries / -color_trc output options, so the stream itself is tagged through x264)
_TAGS = ['-colorspace', 'bt709', '-color_range', 'tv', '-x264-params', 'colorprim=bt709:transfer=bt709:colormatrix=bt709']


def encode_cmd(src, dest):
    """Our encode of the intermediate at constant quality."""
    return _x264_head(src) + ['-crf', str(ENCODE_CRF)] + _TAGS + ['-movflags', '+faststart', dest]


def abr_cmds(src, dest, bitrate, passlog):
    """Two-pass ABR from the same intermediate at the floor (+5 %): (pass 1, pass 2)."""
    rate = str(abr_bitrate(bitrate))
    first = _x264_head(src) + ['-b:v', rate, '-pass', '1', '-passlogfile', passlog] + _TAGS + ['-f', 'null', os.devnull]
    second = _x264_head(src) + ['-b:v', rate, '-pass', '2', '-passlogfile', passlog] + _TAGS + ['-movflags', '+faststart', dest]
    return first, second


def encode_timeout(frames, tier):
    """Seconds an encode pass may take: at least 10 min, else frames x (2 s at 1080, 8 s at 4K)."""
    return max(600, int(frames * (8 if tier == 2 else 2)))


def parse_rate(text):
    """'24', '24/1' or '30000/1001' -> Fraction."""
    num, _, den = str(text).partition('/')
    return Fraction(int(num), int(den or 1))


def probe_output(path):
    """What the finished file really is: size, r_frame_rate (a Fraction), decoded frame count, video bitrate (bits/s,
    from the packet sizes over the stream's own duration) and its audio streams."""
    code, out, err = _run([_tool('ffprobe'), '-v', 'error', '-count_frames', '-show_entries',
                          'stream=index,codec_type,codec_name,width,height,r_frame_rate,nb_read_frames,sample_rate,channels'
                          ':packet=size,stream_index', '-of', 'json', path])
    if code != 0:
        raise ExportError('The finished video could not be read (%s).' % err.strip()[-200:], 500)
    j = json.loads(out)
    streams = j.get('streams') or []
    video = next((s for s in streams if s.get('codec_type') == 'video'), {})
    audio = [s for s in streams if s.get('codec_type') == 'audio']
    rate = parse_rate(video.get('r_frame_rate') or '0/1') if str(video.get('r_frame_rate') or '0/1').split('/')[-1] != '0' else Fraction(0)
    frames = int(video.get('nb_read_frames') or 0)
    vindex = video.get('index', 0)
    vbytes = sum(int(p.get('size') or 0) for p in (j.get('packets') or []) if p.get('stream_index') == vindex)
    vdur = float(frames / rate) if rate and frames else 0.0
    return {'codec': video.get('codec_name'), 'width': video.get('width'), 'height': video.get('height'), 'rate': rate,
            'frames': frames, 'duration': vdur, 'bitrate': int(vbytes * 8 / vdur) if vdur else 0,
            'audio': [{'codec': a.get('codec_name'), 'rate': int(a.get('sample_rate') or 0), 'channels': a.get('channels')}
                      for a in audio]}


def probe_bitrate(path):
    """Video bitrate (bits/s) from the packet sizes over frames / rate: no decoding, so it is cheap inside an encode."""
    code, out, err = _run([_tool('ffprobe'), '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                           'stream=r_frame_rate:packet=size', '-of', 'json', path])
    if code != 0:
        raise ExportError('The encoded video could not be read (%s).' % err.strip()[-200:], 500)
    j = json.loads(out)
    video = (j.get('streams') or [{}])[0]
    rate_text = str(video.get('r_frame_rate') or '0/1')
    rate = parse_rate(rate_text) if rate_text.split('/')[-1] != '0' else Fraction(0)
    packets = j.get('packets') or []
    dur = float(len(packets) / rate) if rate and packets else 0.0
    return int(sum(int(p.get('size') or 0) for p in packets) * 8 / dur) if dur else 0


def check_output(path, out, frames, expect_lufs, expect_audio=False):
    """The rule "never silent quality loss": returns (problems, numbers). It checks the size, the frame rate, the frame
    count, the audio and the loudness; never the video bitrate (a file under the take's bitrate is not a problem: the
    worker logs it). `expect_lufs` is True when the voice is in the mix (the loudness must then be -14 +- 1 LUFS);
    `expect_audio` is True when voice or effects are in (an AAC stream at 48 kHz must then exist). It measures once and
    returns everything `details` needs. An empty problems list means the file is what the take asked for."""
    got = probe_output(path)
    problems = []
    if (got['width'], got['height']) != (out['w'], out['h']):
        problems.append('size %sx%s, wanted %dx%d' % (got['width'], got['height'], out['w'], out['h']))
    if got['rate'] != parse_rate(out['fpsStr']):
        problems.append('frame rate %s, wanted %s' % (got['rate'], parse_rate(out['fpsStr'])))
    if got['frames'] != frames:
        problems.append('%d frames, wanted %d' % (got['frames'], frames))
    # the video bitrate is not checked: a flat drawn picture comes out near lossless under the take's own bitrate, so a
    # file under the floor is finished and fine (the worker logs the number)
    if expect_audio:
        first = got['audio'][0] if got['audio'] else None
        if not first:
            problems.append('no audio stream, wanted AAC at %d Hz' % SR)
        elif first['codec'] != 'aac' or first['rate'] != SR:
            problems.append('audio %s at %s Hz, wanted aac at %d Hz' % (first['codec'], first['rate'], SR))
    lufs, peak = (None, None)
    if expect_lufs:
        lufs, peak = loudness(path)
        if lufs is None or abs(lufs - LUFS) > LUFS_TOLERANCE:
            problems.append('loudness %s LUFS, wanted %g +- %g' % (lufs, LUFS, LUFS_TOLERANCE))
    numbers = {'width': got['width'], 'height': got['height'], 'frameRate': str(got['rate']), 'fps': float(got['rate']),
               'frames': got['frames'], 'codec': got['codec'], 'duration': got['duration'],
               'videoBitrate': got['bitrate'], 'lufs': lufs, 'truePeak': peak, 'audio': got['audio']}
    return problems, numbers


def render_timeout(frames, tier):
    """Seconds a render may take: at least 25 min, and frames x the slowest of (stored, default) seconds-per-frame for the
    tier x 3. A 10 s take at 60 fps in 4K is 600 frames x 2.7 s = 1620 s, which a fixed 25 min would cut off."""
    from ft import pipeline
    key = str(tier)
    per_frame = DEFAULT_RENDER_SEC_PER_FRAME.get(key, 2.7)
    try:
        stored = (read_json(str(pipeline.machine_file()), {}) or {}).get('renderSecPerFrame')
        value = stored.get(key) if isinstance(stored, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            per_frame = max(per_frame, value)
    except (OSError, ValueError, TypeError):
        pass
    return max(RENDER_TIMEOUT, int(frames * per_frame * TIMEOUT_MARGIN))


def record_render_speed(tier, seconds_per_frame):
    """machine.json["renderSecPerFrame"][tier] = 0.5 * old + 0.5 * measured (wall time, honest). Never raises OSError."""
    from ft import pipeline
    try:
        machine = read_json(str(pipeline.machine_file()), {}) or {}
        stored = machine.get('renderSecPerFrame') if isinstance(machine.get('renderSecPerFrame'), dict) else {}
        key = str(tier)
        old = stored.get(key)
        if not isinstance(old, (int, float)) or isinstance(old, bool) or old <= 0:
            old = DEFAULT_RENDER_SEC_PER_FRAME.get(key, 2.7)
        stored[key] = round(0.5 * old + 0.5 * seconds_per_frame, 3)
        machine['renderSecPerFrame'] = stored
        os.makedirs(str(paths.user_dir()), exist_ok=True)
        write_json(str(pipeline.machine_file()), machine)
        return stored[key]
    except (OSError, ValueError, TypeError):
        return None


def fill_template(html, dur, fps, take, settings, font):
    cut = html.lower().find('<html')
    if cut > 0:        # the notes comment above <html> names the placeholders: drop it so user text ("-->") cannot end it early
        html = re.sub(r'<!--.*?-->', '', html[:cut], flags=re.S) + html[cut:]
    subs = {'__DUR__': num_text(dur), '__FPS__': num_text(fps), '__FONT_FILE__': font,        # plain values first,
            '__TAKE_JSON__': js_literal(take), '__SETTINGS_JSON__': js_literal(settings)}    # user text last
    for key, value in subs.items():
        html = html.replace(key, value)
    return html


def probe_video(path):
    code, out, err = _run([_tool('ffprobe'), '-v', 'error', '-select_streams', 'v:0', '-count_packets', '-show_entries',
                          'stream=codec_name,width,height,avg_frame_rate,nb_read_packets:format=duration,size',
                          '-of', 'json', path])
    if code != 0:
        raise ExportError('The rendered video could not be read (%s).' % err.strip()[-200:], 500)
    j = json.loads(out)
    s = (j.get('streams') or [{}])[0]
    f = j.get('format') or {}
    num, _, den = str(s.get('avg_frame_rate') or '0/1').partition('/')
    fps = float(num) / float(den or 1) if float(den or 1) else 0.0
    dur = float(f.get('duration') or 0)
    size = int(f.get('size') or os.path.getsize(path))
    return {'codec': s.get('codec_name'), 'width': s.get('width'), 'height': s.get('height'), 'fps': round(fps, 3),
            'frames': int(s.get('nb_read_packets') or 0), 'duration': dur,
            'bitrate': int(size * 8 / dur) if dur else 0}


def volume_peak_db(path):
    """Loudest sample of an audio file in dBFS (volumedetect), or None."""
    code, out, err = _run([_tool('ffmpeg'), '-hide_banner', '-nostdin', '-i', path, '-vn', '-af', 'volumedetect', '-f', 'null', '-'])
    m = re.search(r'max_volume:\s*(-inf|-?[\d.]+) dB', err)
    return float(m.group(1)) if m else None


def loudness(path):
    """(integrated LUFS, true peak dBTP) of a file's audio via ebur128, or (None, None)."""
    code, out, err = _run([_tool('ffmpeg'), '-hide_banner', '-nostdin', '-nostats', '-i', path, '-vn', '-af',
                          'ebur128=peak=true', '-f', 'null', '-'])
    tail = err[err.rfind('Summary:'):] if 'Summary:' in err else err
    i = re.search(r'\bI:\s+(-?[\d.]+)\s+LUFS', tail)
    p = re.search(r'\bPeak:\s+(-?[\d.]+)\s+dBFS', tail)
    return (float(i.group(1)) if i else None, float(p.group(1)) if p else None)


# -- the exporter -------------------------------------------------------------------------------------------------
class Exporter:
    def __init__(self, pipe, exports_dir):
        self.pipe = pipe
        self.exports = str(exports_dir)
        self.jobs = {}
        self.q = queue.Queue()
        self.proc = None
        self.lock = threading.Lock()
        self._last_save = 0.0
        os.makedirs(self.exports, exist_ok=True)
        threading.Thread(target=self._worker, name='export', daemon=True).start()

    # -- API ---------------------------------------------------------------------------------------------------
    def submit(self, take_id, settings, events):
        if not isinstance(take_id, str) or not take_id:
            raise ExportError('Send {takeId, settings, events}.')
        item = self.pipe.get(take_id)
        if not item:
            raise ExportError('No such take.', 404)
        if (item['status'] or {}).get('stage') != 'ready':
            raise ExportError("This take isn't ready yet.", 409)
        if not isinstance(settings, dict):
            raise ExportError('Send the look as {settings}.')
        if events is None:
            events = []
        if not isinstance(events, list) or len(events) > 2000:
            raise ExportError('{events} must be a list of {t, kind, gain}.')
        font = font_file(settings.get('font'))
        if not font:
            raise ExportError('Unknown font "%s".' % settings.get('font'))
        for ff in (font, 'inter.woff2'):
            if not os.path.exists(os.path.join(ENGINE, 'fonts', ff)):
                raise ExportError('The font file %s is missing from engine/fonts.' % ff, 500)
        missing = [n for n in ENGINE_FILES if not os.path.exists(os.path.join(ENGINE, n))]
        if not os.path.exists(TEMPLATE):
            missing.append('composition.html')
        if missing:
            raise ExportError("The export engine isn't built yet (missing %s)." % ', '.join(missing), 503)
        take_dir = self.pipe.folder(take_id)
        files = take_files(read_json(os.path.join(take_dir, 'take.json')) or {})
        for n in ('take.json', files['person'], files['shadow']):
            if not os.path.exists(os.path.join(take_dir, n)):
                raise ExportError('This take is missing %s. Drop the clip in again.' % n, 409)
        renderer_bin()                                   # no video maker installed: say so now, not after a minute of waiting
        eid = '%s-%s' % (time.strftime('%Y%m%d-%H%M%S'), secrets.token_hex(2))
        d = os.path.join(self.exports, eid)
        os.makedirs(d)
        job = {'id': eid, 'dir': d, 'takeId': take_id, 'settings': settings, 'events': events, 'font': font,
               'stage': 'writing', 'progress': 0.0, 'message': 'Waiting for its turn' if (self.q.qsize() or self.proc) else 'Starting',
               'file': None, 'path': None, 'created': now_iso()}
        self.jobs[eid] = job
        write_json(os.path.join(d, 'job.json'), {'takeId': take_id, 'settings': settings, 'events': events, 'created': job['created']})
        self._save(job, force=True)
        self.q.put(eid)
        return eid

    def status(self, eid):
        if not isinstance(eid, str) or not EXPORT_ID.fullmatch(eid):
            return None
        job = self.jobs.get(eid)
        if job is None:
            st = read_json(os.path.join(self.exports, eid, 'status.json'))
            if st is None:
                return None
            if st.get('stage') not in ('done', 'error'):          # the server restarted mid-export
                st = dict(st, stage='error', progress=0, message='The server restarted before this export was finished. Export again.',
                          error='The server restarted before this export was finished. Export again.')
            return st
        with self.lock:
            return self._public(job)

    def shutdown(self):
        self._kill_tree()

    # -- internals ---------------------------------------------------------------------------------------------
    @staticmethod
    def _public(job):
        keys = ('id', 'stage', 'progress', 'message', 'file', 'path', 'error', 'details', 'created')
        return {k: job[k] for k in keys if k in job}

    def _save(self, job, force=False):
        now = time.time()
        if not force and now - self._last_save < 0.4:
            return
        self._last_save = now
        with self.lock:
            snap = self._public(job)
        write_json(os.path.join(job['dir'], 'status.json'), snap)

    def _set(self, job, stage, progress, message, force=False, **extra):
        with self.lock:
            job.update(stage=stage, progress=round(max(0.0, min(1.0, progress)), 3), message=message, **extra)
        self._save(job, force=force)

    def _log(self, job, text):
        try:
            with open(os.path.join(job['dir'], 'export.log'), 'a', encoding='utf-8') as f:
                f.write('%s  %s\n' % (time.strftime('%H:%M:%S'), text))
        except OSError:
            pass

    def _kill_tree(self):
        p = self.proc
        if p and p.poll() is None:
            if IS_NT:
                subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)], capture_output=True, creationflags=NO_WINDOW)
            else:                                            # the render's own session: Chrome and ffmpeg die with HyperFrames
                try:
                    os.killpg(os.getpgid(p.pid), getattr(signal, 'SIGKILL', 9))
                except OSError:
                    p.kill()

    def _worker(self):
        while True:
            eid = self.q.get()
            job = self.jobs[eid]
            try:
                self._run(job)
            except ExportError as e:
                if e.detail:
                    self._log(job, e.detail)
                self._note_kept(job)
                self._fail(job, str(e))
            except Exception as e:                               # a bug: say so, keep the details in the log
                self._log(job, traceback.format_exc())
                self._note_kept(job)
                self._fail(job, 'Something went wrong while exporting (%s: %s).' % (type(e).__name__, e))

    def _note_kept(self, job):
        """Any failure that leaves the intermediate render behind (a render cut short, the encode, the mix, the check, a
        bug) says where it is. A successful export has deleted it."""
        path = os.path.join(job['dir'], 'render.mp4')
        if os.path.exists(path):
            self._log(job, 'kept the intermediate at %s' % path)

    def _fail(self, job, message):
        self._log(job, 'ERROR: ' + message)
        self._set(job, 'error', 0, message, force=True, error=message)

    def _stream(self, job, cmd, on_line, timeout, cwd=None, env=None):
        """Run cmd, feed every output line to on_line; keep every line in export.log. Returns (exit code, last lines)."""
        self._log(job, '$ ' + ' '.join('"%s"' % c if ' ' in c else c for c in cmd))
        extra = {} if IS_NT else {'start_new_session': True}
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                             errors='replace', cwd=cwd, env=env, stdin=subprocess.DEVNULL, creationflags=NO_WINDOW, **extra)
        self.proc = p
        timer = threading.Timer(timeout, self._kill_tree)
        timer.start()
        tail = []
        try:
            for line in p.stdout:
                line = line.rstrip()
                if not line:
                    continue
                tail.append(line)
                del tail[:-60]
                self._log(job, '  ' + line)
                on_line(line)
            code = p.wait()
        finally:
            timer.cancel()
            self.proc = None
        return code, tail

    # -- the three stages ----------------------------------------------------------------------------------------
    def _run(self, job):
        d, eid = job['dir'], job['id']
        timings = {}
        t0 = time.time()
        take_dir = self.pipe.folder(job['takeId'])
        take = read_json(os.path.join(take_dir, 'take.json'))
        if not take or not take.get('dur') or not take.get('fps'):
            raise ExportError('This take has not been measured yet.', 409)
        settings, events = job['settings'], job['events']
        dur, fps = float(take['dur']), float(take['fps'])
        out = out_spec(take)
        files = take_files(take)
        tier = 2 if (take.get('tier') == 2 or out['h'] > 1920) else 1
        frames = int(take.get('frames') or round(dur * fps))
        # HyperFrames renders ceil(duration * fps) frames; 5.042 s * 24 = 121.008 would give 122. A quarter frame short of
        # the last frame's time gives exactly the take's frame count, and the last frame (t = (frames-1)/fps) is still inside.
        comp_dur = (frames - 0.25) / fps
        name = safe_filename(take.get('name') or take.get('file') or job['takeId'])
        final = os.path.join(d, '%s - floored.mp4' % name)
        video = os.path.join(d, 'video.mp4')
        render = os.path.join(d, 'render.mp4')

        # 1. writing: the composition folder
        self._set(job, 'writing', 0.05, 'Preparing the scene')
        os.makedirs(os.path.join(d, 'assets', 'engine', 'fonts'), exist_ok=True)
        for n in ENGINE_FILES:
            shutil.copyfile(os.path.join(ENGINE, n), os.path.join(d, 'assets', 'engine', n))
        for ff in (job['font'], 'inter.woff2'):         # the font, and Inter: it draws the characters that font lacks
            shutil.copyfile(os.path.join(ENGINE, 'fonts', ff), os.path.join(d, 'assets', 'engine', 'fonts', ff))
        # the full-resolution cutout (take.files.person), never the studio's 1080 proxy
        shutil.copyfile(os.path.join(take_dir, files['person']), os.path.join(d, 'assets', 'person.webm'))
        shutil.copyfile(os.path.join(take_dir, files['shadow']), os.path.join(d, 'assets', 'shadow.webm'))
        with open(TEMPLATE, encoding='utf-8') as f:
            html = f.read()
        html = fill_template(html, comp_dur, fps, take, settings, job['font'])
        with open(os.path.join(d, 'index.html'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(html)
        left = sorted(set(re.findall(r'__[A-Z][A-Z_]{2,}__', html)))
        if left:
            self._log(job, 'WARNING: placeholders left in index.html: %s' % ', '.join(left))
        self._set(job, 'writing', 0.3, 'Preparing the scene')
        if not SKIP_CHECK:
            self._set(job, 'writing', 0.4, 'Checking the scene')
            code, tail = self._stream(job, renderer_bin() + ['check', d, '--budget', '90s', '--samples', '5'],
                                      lambda line: None, CHECK_TIMEOUT, env=renderer_env())
            self._log(job, 'hyperframes check exit code %s (logged only)' % code)
        timings['writing'] = round(time.time() - t0, 1)

        # 2. rendering
        t1 = time.time()
        mbps = floor_mbps(out['bitrate'])                      # the floor: never below the take (min 8 Mbps)
        notes = []
        self._set(job, 'rendering', 0.0, 'Starting the render')
        last = {'p': 0.0}

        def on_render(line):
            # HyperFrames prints `@hf-progress {"code":"capture","done":12,"total":122,"pct":28}` (pct = whole render, 0-100)
            if line.lstrip().startswith('@hf-progress'):
                try:
                    ev = json.loads(line.split('@hf-progress', 1)[1])
                except ValueError:
                    return
                code, done, total = ev.get('code'), ev.get('done'), ev.get('total')
                if code == 'capture' and total:
                    msg = 'Rendering frame %d of %d' % (done or 0, total)
                elif code == 'encode':
                    msg = 'Encoding the video'
                elif code == 'assemble':
                    msg = 'Finishing the file'
                elif code in ('compile', 'extract_video', 'process_audio', 'start_browsers'):
                    msg = 'Getting the scene ready'
                else:
                    msg = 'Rendering'
                last['p'] = max(last['p'], min(float(ev.get('pct') or 0) / 100.0, 0.99) * RENDER_SHARE)   # never goes backwards
                self._set(job, 'rendering', last['p'], msg)
            elif not last['p'] and re.search(r'waiting for (another|other)|another render', line.lower()):
                self._set(job, 'rendering', 0.0, 'Waiting for another render to finish')

        cmd = render_cmd(renderer_bin(), d, render, out)
        code, tail = self._stream(job, cmd, on_render, render_timeout(frames, tier), env=renderer_env())
        if code != 0 or not os.path.exists(render):
            raise ExportError("The render didn't finish: %s" % (' / '.join(tail[-3:])[:300] or 'no output'), 500)
        vinfo = probe_video(render)
        self._log(job, 'rendered (intermediate, crf %d): %s, %.1f MB' % (INTERMEDIATE_CRF, json.dumps(vinfo),
                                                                       os.path.getsize(render) / 1e6))
        timings['rendering'] = round(time.time() - t1, 1)

        # 2b. our encode of the intermediate (constant quality; two-pass at the floor when that comes out below it)
        t1b = time.time()
        encoded = self._encode(job, render, video, out, frames, tier)
        timings['encoding'] = round(time.time() - t1b, 1)
        if frames:
            wall = timings['rendering'] + timings['encoding']       # wall time of render + encode, honest
            self._log(job, 'render speed: %.2f s per frame (stored tier %d: %s)'
                      % (wall / frames, tier, record_render_speed(tier, wall / frames)))

        # 3. sound
        t2 = time.time()
        self._set(job, 'sound', 0.1, 'Building the sound')
        sound = settings.get('sound') if isinstance(settings.get('sound'), dict) else {}
        want_voice = sound.get('voice', True) is not False
        want_sfx = sound.get('sfx', True) is not False
        voice = os.path.join(take_dir, files['audio'] or 'audio.m4a')
        have_voice = want_voice and bool(take.get('hasAudio')) and bool(files['audio']) and os.path.exists(voice)
        usable_events = [e for e in events if isinstance(e, dict) and e.get('kind') in sfx.MAKERS]
        have_sfx = want_sfx and bool(usable_events)
        vdur = vinfo['duration'] or dur
        sfx_wav = os.path.join(d, 'sfx.wav')
        if have_sfx:
            sfx.write_wav(sfx_wav, sfx.synth(events, vdur, SR), SR)
        self._set(job, 'sound', 0.35, 'Mixing the sound')
        audio_info = self._mix(job, video, voice if have_voice else None, sfx_wav if have_sfx else None, final, vdur)
        timings['sound'] = round(time.time() - t2, 1)

        # the check: size, frame rate, frames, audio and loudness must match the take, or the export stops (the video
        # bitrate never stops it: it is only logged below)
        problems, numbers = check_output(final, out, frames, bool(audio_info and audio_info.get('voice')),
                                         expect_audio=bool(audio_info))
        self._log(job, 'check: %s' % json.dumps(numbers, default=str))
        floor_bps = floor_mbps(out['bitrate']) * 1e6
        if numbers['videoBitrate'] < floor_bps:
            self._log(job, "note: video bitrate %.2f Mbps is under the %.2f Mbps floor (the take's bitrate, %g Mbps at least). "
                      "That never stops an export: the file is kept."
                      % (numbers['videoBitrate'] / 1e6, floor_bps / 1e6, MIN_MBPS))
        if problems:
            self._log(job, 'CHECK FAILED: %s' % '; '.join(problems))
            raise ExportError(CHECK_FAILED, 500)
        self._clean_up(job, render, video, sfx_wav)               # on any failure above, the files stay (the log says where)
        timings['total'] = round(time.time() - t0, 1)
        details = {'width': numbers['width'], 'height': numbers['height'], 'fps': numbers['fps'], 'codec': numbers['codec'],
                   'duration': round(numbers['duration'], 3), 'videoBitrate': numbers['videoBitrate'],
                   'targetMbps': round(mbps, 2), 'audio': audio_info, 'lufs': numbers['lufs'], 'truePeak': numbers['truePeak'],
                   'tier': tier, 'timings': timings, 'notes': notes, 'encode': encoded}
        self._log(job, 'done: %s' % json.dumps(details))
        rel = os.path.basename(final)
        self._set(job, 'done', 1.0, 'Your video is ready', force=True,
                  file='/exports/%s/%s' % (eid, urllib.parse.quote(rel)), path=os.path.abspath(final), details=details)

    def _clean_up(self, job, *files):
        """Once the check has passed: delete the work files. What stays: index.html, job.json, status.json, export.log and
        the final mp4. (render.mp4, video.mp4, sfx.wav, premix.wav and assets/ would double the folder's size.)"""
        d = job['dir']
        for f in list(files) + [os.path.join(d, 'premix.wav')]:
            try:
                os.remove(f)
            except OSError:
                pass
        shutil.rmtree(os.path.join(d, 'assets'), ignore_errors=True)
        if os.path.exists(os.path.join(d, 'assets')):
            self._log(job, 'WARNING: could not remove the assets folder')

    def _encode(self, job, src, dest, out, frames, tier):
        """src (the near-lossless render) -> dest, x264 at CRF 14. If its video bitrate is below the floor, encode src
        again two-pass at floor + 5 %. Logs both results; returns {crf, crfBitrate, floorMbps, floorReencode, bitrate}.
        A failed encode keeps src and says where."""
        floor = floor_mbps(out['bitrate']) * 1e6
        base_p = RENDER_SHARE

        def on_encode(lo, hi):                               # ffmpeg -progress prints `frame=N`: map it into lo..hi of the bar
            def f(line):
                m = re.match(r'frame=(\d+)', line)
                if m and frames:
                    self._set(job, 'rendering', lo + (hi - lo) * min(int(m.group(1)) / float(frames), 1.0), 'Encoding the video')
            return f

        def fail(code, tail):
            raise ExportError("The video couldn't be encoded: %s" % (' / '.join(tail[-3:])[:300] or 'no output'), 500)

        self._set(job, 'rendering', base_p, 'Encoding the video')
        code, tail = self._stream(job, encode_cmd(src, dest), on_encode(base_p, 0.9), encode_timeout(frames, tier))
        if code != 0 or not os.path.exists(dest):
            fail(code, tail)
        got = probe_bitrate(dest)
        info = {'crf': ENCODE_CRF, 'crfBitrate': got, 'floorMbps': round(floor / 1e6, 2), 'floorReencode': False, 'bitrate': got}
        self._log(job, 'encode: crf %d %s gives %.2f Mbps, %.1f MB; floor %.2f Mbps'
                  % (ENCODE_CRF, ENCODE_PRESET, got / 1e6, os.path.getsize(dest) / 1e6, floor / 1e6))
        if got < floor:
            rate = abr_bitrate(out['bitrate'])
            self._log(job, 'floor re-encode: ran (%.2f Mbps is under the %.2f Mbps floor), two-pass at %.2f Mbps'
                      % (got / 1e6, floor / 1e6, rate / 1e6))
            self._set(job, 'rendering', 0.9, 'Encoding the video')
            first, second = abr_cmds(src, dest, out['bitrate'], 'x264pass')
            d = job['dir']
            try:
                for n, cmd in enumerate((first, second)):
                    code, tail = self._stream(job, cmd, on_encode(0.9 + 0.045 * n, 0.945 + 0.045 * n), encode_timeout(frames, tier), cwd=d)
                    if code != 0:
                        fail(code, tail)
            finally:                                         # a failed pass leaves its stats files too
                for leftover in os.listdir(d):
                    if leftover.startswith('x264pass'):
                        try:
                            os.remove(os.path.join(d, leftover))
                        except OSError:
                            pass
            if not os.path.exists(dest):
                fail(1, [])
            info.update(floorReencode=True, bitrate=probe_bitrate(dest), abrBitrate=rate)
            self._log(job, 'floor re-encode: gives %.2f Mbps, %.1f MB' % (info['bitrate'] / 1e6, os.path.getsize(dest) / 1e6))
        else:
            self._log(job, 'floor re-encode: not needed')
        return info

    def _mix(self, job, video, voice, sfx_wav, final, vdur):
        """Voice + effects (6 dB under the voice peak) -> loudnorm two-pass -> AAC 192k beside the copied video.
        Returns a dict describing the audio, or None when the result has no audio.

        A voice track that is digital silence, or whose loudest sample is under -60 dBFS, or that loudnorm reads at -70 LUFS or
        lower (a single click), counts as no voice: the effects get their alone gain, nothing is normalised, and
        `voice` is False, so the check does not ask for -14 LUFS (a take from an AI generator often carries a silent track)."""
        base = [_tool('ffmpeg'), '-hide_banner', '-nostdin', '-y']
        if not voice and not sfx_wav:
            self._log(job, 'no sound wanted or available: the video is kept without an audio track')
            code, out, err = _run(base + ['-i', video, '-map', '0:v:0', '-c:v', 'copy', '-an', '-movflags', '+faststart', final])
            if code != 0:
                raise ExportError("The video couldn't be finished.", 500)
            return None
        d = job['dir']
        premix = os.path.join(d, 'premix.wav')
        D = '%.4f' % vdur
        peak = volume_peak_db(voice) if voice else None
        audible = bool(voice) and (peak is None or peak >= SILENT_VOICE_DB)       # peak None: unmeasurable, treat as a voice
        voice_lufs = None
        if audible:                                                # a single click is loud in peak but not in LUFS
            voice_lufs = loudness(voice)[0]
            audible = voice_lufs is None or voice_lufs > NO_LOUDNESS_LUFS
        info = {'voice': audible, 'sfx': bool(sfx_wav)}
        if peak is not None:
            info['voicePeakDb'] = peak
        if voice and not audible:
            self._log(job, 'the voice track is silent (peak %s dBFS, %s LUFS): no voice in the mix, no loudness target' % (peak, voice_lufs))

        def gain_for(voice_audible):
            if voice_audible and peak is not None:
                return peak - SFX_UNDER_VOICE_DB - (-3.0)          # the effects file peaks at -3 dBFS
            if voice_audible:
                return -SFX_UNDER_VOICE_DB                         # the voice peak cannot be measured: a literal -6 dB
            return -3.0                                            # effects alone: peak at -6 dBFS, no loudness target

        def build_premix(gain_db):
            inputs, parts, labels = [], [], []
            if voice:
                parts.append('[%d:a]aresample=%d,aformat=channel_layouts=stereo,apad=whole_dur=%s,atrim=0:%s[v]' % (len(inputs), SR, D, D))
                inputs += ['-i', voice]
                labels.append('[v]')
            if sfx_wav:
                info['sfxGainDb'] = round(gain_db, 2)
                parts.append('[%d:a]aresample=%d,aformat=channel_layouts=stereo,volume=%.3fdB,apad=whole_dur=%s,atrim=0:%s[s]'
                             % (len(inputs) // 2, SR, gain_db, D, D))
                inputs += ['-i', sfx_wav]
                labels.append('[s]')
            if len(labels) == 2:
                parts.append('%samix=inputs=2:duration=longest:normalize=0[m]' % ''.join(labels))
            else:
                parts.append('%sanull[m]' % labels[0])
            code, out, err = _run(base + inputs + ['-filter_complex', ';'.join(parts), '-map', '[m]', '-ar', str(SR), '-c:a', 'pcm_s16le',
                                                   premix])
            if code != 0:
                self._log(job, err[-1500:])
                raise ExportError("The sound couldn't be mixed.", 500)

        build_premix(gain_for(audible) if sfx_wav else 0.0)

        afilter = 'aresample=%d' % SR
        if audible:                                                # loudness target only makes sense with the voice in
            self._set(job, 'sound', 0.6, 'Matching the loudness')
            code, out, err = _run(base + ['-i', premix, '-af', 'loudnorm=I=%g:TP=%g:LRA=%g:print_format=json' % (LUFS, TRUE_PEAK, LRA),
                                          '-f', 'null', '-'])
            m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', err, re.S)
            if code == 0 and m:
                j = json.loads(m.group(0))
                info['measured'] = {k: j.get(k) for k in ('input_i', 'input_tp', 'input_lra', 'input_thresh')}
                try:
                    measured = float(j['input_i'])               # "-inf" parses to -inf
                    if measured > NO_LOUDNESS_LUFS:
                        afilter = ('loudnorm=I=%g:TP=%g:LRA=%g:measured_I=%s:measured_LRA=%s:measured_TP=%s:measured_thresh=%s:'
                                   'offset=%s:linear=true,aresample=%d' % (LUFS, TRUE_PEAK, LRA, j['input_i'], j['input_lra'],
                                                                           j['input_tp'], j['input_thresh'], j['target_offset'], SR))
                    else:                                        # nothing there to normalise: no voice after all
                        audible = info['voice'] = False
                        self._log(job, 'the voice reads %s LUFS: no voice in the mix, no loudness target' % j['input_i'])
                        if sfx_wav:
                            build_premix(gain_for(False))
                except (KeyError, ValueError):
                    pass
            if audible and afilter == 'aresample=%d' % SR:
                self._log(job, 'WARNING: loudnorm pass 1 gave no usable measurement; the mix keeps its level')
        self._set(job, 'sound', 0.85, 'Finishing the video')
        code, out, err = _run(base + ['-i', video, '-i', premix, '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'copy', '-af', afilter,
                                      '-c:a', 'aac', '-b:a', '192k', '-ar', str(SR), '-t', '%.4f' % vdur,
                                      '-movflags', '+faststart', final])
        if code != 0:
            self._log(job, err[-1500:])
            raise ExportError("The video couldn't be finished.", 500)
        info['codec'] = 'aac 192k 48 kHz stereo'
        return info
