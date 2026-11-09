"""floored: take pipeline (one take at a time, in a worker thread).

A take is a folder  takes/<id>/  with:
  source<ext>        the upload as it came (kept)
  stage.mp4          the stage video: 8-bit H.264, constant frame rate, upright, 9:16 at 1080x1920 (tier 1) or 2160x3840
                     (tier 2, a 4K take); the cutout and the export run on it
  person.webm        the RVM cutout (VP9 alpha) at the stage size
  person_proxy.webm  tier 2 only: a 1080x1920 copy of the cutout, what the studio plays and measures
  shadow.webm, audio.m4a (when the clip has sound), poster.jpg (360x640), take.json, status.json, measure.json, log.txt

The stages (status.json `stage`, with the weight each has in `overall`):
  checking   0.05  refuse what cannot work (no picture, over MAX_S) within seconds, then probe, make stage.mp4, poster, audio
  cutting    0.75  RVM only (python -m ft.matte, downsample_for(stage height), never u2net / rembg / keying); tier 2 ends
                   with the proxy (the last 5 % of the stage)
  measuring  0.07  feet, height, k0, aoWidth, edge frames, the take check's warnings; reads files.preview
  shadow     0.05  the blurred black shadow video; reads files.preview
  words      0.08  speech word timestamps (faster-whisper, optional)

status.json: {stage, progress 0..1 within the stage, overall 0..1, message, error?} and, while cutting, `eta` (seconds
left) and `etaGuess` (true while this machine has no measured seconds-per-frame for the provider and tier). The measured
values live in <user dir>/machine.json  {"secPerFrame": {"cpu-1": 3.4, ...}}: after each real cut the stored value
becomes 0.5 * old + 0.5 * measured.

take.json is the contract the studio, the Claude bridge and the export read. Geometry (feet, height, k0, aoWidth) is
always in 1080 units; `w`, `h`, `fps`, `frames` describe that frame, `out` the render (stage size, stage frame rate,
max(upload bitrate, 8 Mbps)), `files` the media names (`preview` = the proxy for tier 2, else person.webm; `audio` is
null for a silent clip), `bitrate` the upload's own.

DEV / TEST ONLY: FT_FAKE_MATTE=1 replaces the cutout with sample/person.webm scaled to the stage size and looped or trimmed
to the stage's frame count, so UI tests and dev runs skip RVM (the tier 2 proxy still runs). It never records timings.
FT_FAKE_MATTE_DELAY=<seconds> makes the fake wait first (so a test can watch the cutting status). Neither is ever set
by the app itself.
"""
import datetime
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
import traceback

from ft import calibration, matte, paths, words
from ft.measure import measure, take_warnings
from ft.media import (STAGE_BASE, PipelineError, ffmpeg_rate, fps_value, make_proxy, num, probe, rate,   # noqa: F401  (re-exported)
                      stage_size, tier, to_stage)
from ft.proc import NO_WINDOW, MissingTool, kill_tree, run, run_lines, tool

VIDEO_EXTS = ('.mp4', '.mov', '.m4v', '.webm', '.mkv', '.avi')
MIN_OUT_BITRATE = 8_000_000                # the export never goes below 8 Mbps
STALE = ('queued', 'checking', 'cutting', 'measuring', 'shadow', 'words')
STAGE_ORDER = ('checking', 'cutting', 'measuring', 'shadow')       # the stages that leave files; 'words' always runs last
WEIGHTS = (('checking', 0.05), ('cutting', 0.75), ('measuring', 0.07), ('shadow', 0.05), ('words', 0.08))
PROXY_SHARE = 0.05                         # tier 2: the proxy is the last 5 % of the cutting stage
SEC_PER_FRAME = {'cpu-1': 3.4, 'cpu-2': 10.2, 'dml-1': 1.2, 'dml-2': 3.6, 'coreml-1': 1.2, 'coreml-2': 3.6}   # first guesses
PROVIDERS = ('cpu', 'dml', 'coreml')
CUT_STALL_FLOOR = 600                      # seconds: a cutout is never judged stuck before 10 minutes without a progress line


def cut_stall_limit(spf):
    """Seconds without a progress line before the cutout counts as stuck: twenty progress intervals (the cutout reports
    every 48 frames), never under 10 minutes."""
    return max(CUT_STALL_FLOOR, 20 * spf * 48)


COPY_CUT_STOPPED = 'The cutout stopped before the end. Try again, and if it keeps happening, ask Claude for help.'
COPY_NO_MODEL = "The cutout tool isn't set up yet. Ask Claude to finish the floored setup, then try again."
COPY_CANT_OPEN = "We couldn't open this video. Try exporting it again as an MP4 or MOV."
COPY_NO_VIDEO = "We couldn't find a video in this file. Add an MP4 or MOV with a picture."
COPY_CHECK_TIMEOUT = "We couldn't check this video in time. Try exporting it again as an MP4 or MOV."
COPY_BUG = 'Something went wrong while processing this clip. Try again, and if it keeps happening, ask Claude for help.'


class Refusal(PipelineError):
    """A clip we turn down before doing any work: nothing but the log and the error is kept."""


class RetryError(PipelineError):
    """A take that cannot be re-queued; `code` is the HTTP status the server answers with."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# ----------------------------------------------------------------------------------------------------- small helpers

def read_json(path, default=None):
    """None-safe JSON read. On Windows a file that is being replaced cannot be opened for a few ms: retry before giving up."""
    for attempt in range(8):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except (OSError, ValueError):
            time.sleep(0.02)
    return default


def write_json(path, obj):
    """Atomic: the UI polls these files while the worker rewrites them."""
    tmp = '%s.%d.tmp' % (path, threading.get_ident())
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    for _ in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:          # a reader has it open for a moment (Windows)
            time.sleep(0.05)
    os.replace(tmp, path)


def missing_tool_copy(e):
    return ("A tool floored needs (%s) isn't installed. Ask Claude to finish the floored setup, "
            'then try again.' % e.name)


def now_iso():
    return datetime.datetime.now().isoformat(timespec='seconds')


def clean_name(filename):
    stem = os.path.splitext(os.path.basename(filename or ''))[0]
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ', stem)
    stem = re.sub(r'\s+', ' ', stem).strip(' .')
    return (stem or 'Untitled take')[:60]


def new_take_id():
    return time.strftime('%y%m%d-%H%M%S') + '-' + secrets.token_hex(2)


def info_fps_str(vi):
    """The frame rate as ffmpeg wants it in a lavfi source: '24' or '30000/1001'."""
    return ffmpeg_rate(vi['fps'])


# ----------------------------------------------------------------------------------------------- the machine's speed

def machine_file():
    return paths.user_dir() / 'machine.json'


def machine_provider():
    """The cutout provider machine.json recorded (cpu when there is none): the first half of the timing key."""
    value = (read_json(machine_file(), {}) or {}).get('matteProvider')
    return value if value in PROVIDERS else 'cpu'


def sec_per_frame(key):
    """(seconds per frame, is_guess) for a timing key such as 'cpu-1': the measured value, else the first guess."""
    stored = ((read_json(machine_file(), {}) or {}).get('secPerFrame') or {}).get(key)
    if isinstance(stored, (int, float)) and stored > 0:
        return float(stored), False
    return SEC_PER_FRAME.get(key, 3.4), True


def record_sec_per_frame(key, measured):
    """After a real cut: the stored value becomes 0.5 * old + 0.5 * measured (the first guess counts as 'old')."""
    machine = read_json(machine_file(), {}) or {}
    spf = machine.setdefault('secPerFrame', {})
    old, _ = sec_per_frame(key)
    spf[key] = round(0.5 * old + 0.5 * measured, 3)
    os.makedirs(str(paths.user_dir()), exist_ok=True)
    write_json(str(machine_file()), machine)
    return spf[key]


def left_text(seconds):
    return 'less than a minute' if seconds < 50 else 'about %d min' % max(1, round(seconds / 60.0))


# --------------------------------------------------------------------------------------------------------- the cutout

def matte_command(src, dst, downsample=0.75, provider='auto'):
    """The cutout subprocess: `python -m ft.matte` with absolute paths (the take's workspace may be given as a relative
    path) and PYTHONPATH set so `ft` imports from wherever the process runs. RVM only; the downsample is picked per
    tier by the pipeline (ft.matte.downsample_for). Returns (argument list, environment)."""
    app_dir = str(paths.APP_DIR)
    env = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1',
               PYTHONPATH=os.pathsep.join([app_dir] + ([os.environ['PYTHONPATH']] if os.environ.get('PYTHONPATH') else [])))
    cmd = [sys.executable, '-m', 'ft.matte', os.path.abspath(src), os.path.abspath(dst), '--downsample', '%g' % downsample,
           '--provider', provider]
    return cmd, env


_FAKE_RUNNER = 'import subprocess, sys, time\ntime.sleep(float(sys.argv[1]))\nsys.exit(subprocess.call(sys.argv[2:]))'


def fake_matte_command(dst, w, h, fps_str, frames):
    """DEV / TEST ONLY (FT_FAKE_MATTE=1): sample/person.webm scaled to w x h and looped or trimmed to `frames` frames."""
    delay = os.environ.get('FT_FAKE_MATTE_DELAY') or '0'
    ff = [tool('ffmpeg'), '-y', '-v', 'error', '-nostdin', '-stream_loop', '-1', '-c:v', 'libvpx-vp9',
          '-i', str(paths.SAMPLE_DIR / 'person.webm'),
          '-vf', 'scale=%d:%d:flags=bilinear,format=yuva420p' % (w, h), '-r', fps_str, '-frames:v', str(frames),
          '-c:v', 'libvpx-vp9', '-pix_fmt', 'yuva420p', '-crf', '18', '-b:v', '0', '-row-mt', '1', '-auto-alt-ref', '0',
          '-deadline', 'realtime', '-cpu-used', '8', os.path.abspath(dst)]
    return [sys.executable, '-c', _FAKE_RUNNER, delay] + ff, dict(os.environ)


# --------------------------------------------------------------------------------------------- shadow, words, audio

def make_shadow(person, dst, fps_str, frames, dur, k0, progress=None, log=None):
    """SPEC step 4: the cutout's alpha, scaled to 540x960, blurred, black, as a VP9 alpha webm."""
    sigma = 17.2 / (2 * k0)
    fc = ('[0:v]alphaextract,scale=540:960,gblur=sigma=%.2f[al];[1:v][al]alphamerge,format=yuva420p[out]' % sigma)
    cmd = [tool('ffmpeg'), '-y', '-v', 'error', '-progress', 'pipe:1', '-nostats', '-c:v', 'libvpx-vp9', '-i', str(person),
           '-f', 'lavfi', '-i', 'color=c=black:s=540x960:r=%s:d=%.3f' % (fps_str, dur + 0.2),
           '-filter_complex', fc, '-map', '[out]', '-frames:v', str(frames), '-c:v', 'libvpx-vp9',
           '-pix_fmt', 'yuva420p', '-b:v', '0', '-crf', '24', '-row-mt', '1', '-auto-alt-ref', '0', str(dst)]

    def on_line(line):
        m = re.match(r'frame=(\d+)', line)
        if m and progress:
            progress(int(m.group(1)))
    code, tail = run_lines(cmd, on_line, timeout=1200)
    if code != 0 or not os.path.exists(dst):
        if log:
            log('shadow failed (exit %s): %s' % (code, ' | '.join(tail[-5:])))
        raise PipelineError("We couldn't draw your shadow. Try again, and if it keeps happening, ask Claude for help.")


def words_fields(src, has_audio, log, fn=None):
    """The take fields of the words stage: transcript, language, words. Empty (and no warning, ever) when the clip has
    no sound, speech recognition is not installed, or it fails; typed and suggested text still work then.
    `fn(path, log)` replaces words.transcribe (an injected one is used without asking words.available())."""
    if not has_audio or (fn is None and not words.available()):
        return words.empty()
    try:
        r = (fn or words.transcribe)(src, log)
    except Exception as e:                           # noqa: BLE001  (words are optional: never fail the take over them)
        log('speech recognition failed: %s' % e)
        return words.empty()
    return {'transcript': r['transcript'], 'language': r['language'], 'words': r['words']}


# ----------------------------------------------------------------------------------------- the refusals, fast

def packet_duration(path):
    """The length of the first video stream from its packets' timestamps (demuxing only, no decoding): the fallback for a
    container that states no duration (a MediaRecorder or screen-recorder webm). 0.0 when it cannot be told."""
    code, out, _ = run([tool('ffprobe'), '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                        'packet=pts_time,duration_time', '-of', 'csv=p=0', str(path)], timeout=120)
    end = 0.0
    for line in out.splitlines():
        pts, _, dur = line.strip().partition(',')
        end = max(end, num(pts) + num(dur))
    return end if code == 0 else 0.0


def refuse_if_too_long(dur, log):
    if dur > calibration.MAX_S + calibration.MAX_S_GRACE:
        log('refused: %.2f s is over the %g s limit (+ %g s grace)' % (dur, calibration.MAX_S, calibration.MAX_S_GRACE))
        raise Refusal('This clip is %.1f seconds long. Trim it to %g seconds or less and add it again.'
                      % (dur, calibration.MAX_S))


def check_clip(path, log):
    """Within seconds, before any conversion or cutout, and before the take joins the queue: a file we cannot open, one
    with no picture, one that is too long. Reads the container only (no decoding), so a long 4K clip is turned down as
    quickly as a short one; a container with no duration is measured from its packets. Raises Refusal.
    Returns the duration (s) found."""
    code, out, err = run([tool('ffprobe'), '-v', 'error', '-show_entries', 'format=duration:stream=codec_type',
                          '-of', 'json', str(path)], timeout=60)
    try:
        data = json.loads(out) if out.strip() else {}
    except ValueError:
        data = {}
    if code != 0 or 'format' not in data:
        log('ffprobe could not open the file (exit %s): %s' % (code, err.strip()[-300:]))
        raise Refusal(COPY_CANT_OPEN)
    if not any(s.get('codec_type') == 'video' for s in data.get('streams') or []):
        log('no video stream in the file')
        raise Refusal(COPY_NO_VIDEO)
    dur = num(data['format'].get('duration'))
    if dur <= 0:
        dur = packet_duration(path)
        log('the container states no duration; its packets run for %.2f s' % dur)
    refuse_if_too_long(dur, log)
    return dur


# ------------------------------------------------------------------------------------------------------ the queue

class Pipeline:
    def __init__(self, ws, matte_cmd=None, words_fn=None):
        """ws: a ft.paths.Workspace. matte_cmd(src, dst, downsample, provider) -> (argv, env) replaces matte_command (tests);
        words_fn(path, log) -> {transcript, language, words} replaces words.transcribe."""
        self.takes = str(getattr(ws, 'takes', ws))          # the workspace's takes folder (read and write)
        self.sample = str(paths.SAMPLE_DIR)                 # the built-in sample take (read only)
        self.matte_cmd = matte_cmd or matte_command
        self.words_fn = words_fn
        os.makedirs(self.takes, exist_ok=True)
        self.q = queue.Queue()
        self.busy = None                   # id of the take being processed
        self.proc = None                   # the running cutout subprocess (killed at shutdown)
        self.last = {}                     # id -> the status last written (answers a poll if the file is mid-replace)
        self.lock = threading.Lock()
        self._last_write = 0.0
        self.recover()
        threading.Thread(target=self._worker, name='pipeline', daemon=True).start()

    # -- reading ---------------------------------------------------------------------------------------------
    def folder(self, tid):
        if tid == 'sample' and self.sample:
            return self.sample
        return os.path.join(self.takes, tid)

    def get(self, tid):
        """{take, status} for one take, or None."""
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', tid or '') or tid.startswith('.'):
            return None
        d = self.folder(tid)
        if not os.path.isdir(d):
            return None
        take = read_json(os.path.join(d, 'take.json'))
        status = read_json(os.path.join(d, 'status.json')) or self.last.get(tid)
        if take is None and status is None:
            return None
        if status is None:
            status = {'stage': 'ready', 'progress': 1, 'message': 'Ready'}
        return {'take': take or {'id': tid, 'name': tid}, 'status': status}

    def list(self):
        items = []
        ids = [t for t in os.listdir(self.takes) if os.path.isdir(os.path.join(self.takes, t)) and t != 'sample']
        if self.sample and os.path.isdir(self.sample):
            ids.append('sample')
        for tid in ids:
            item = self.get(tid)
            if item:
                items.append(item)
        # newest first, the sample last
        items.sort(key=lambda it: str(it['take'].get('created') or ''), reverse=True)
        items.sort(key=lambda it: it['take'].get('id') == 'sample')
        return items

    # -- uploads ---------------------------------------------------------------------------------------------
    def begin_upload(self, filename):
        ext = os.path.splitext(filename or '')[1].lower()
        if ext not in VIDEO_EXTS:
            raise PipelineError('Please drop a video file (MP4, MOV, M4V, WebM, MKV or AVI).')
        tid = new_take_id()
        d = self.folder(tid)
        os.makedirs(d)
        path = os.path.join(d, 'source' + ext)
        # status first: a poll that sees take.json without a status would call the take ready
        st = {'stage': 'queued', 'progress': 0, 'overall': 0, 'message': 'Uploading'}
        self.last[tid] = st
        write_json(os.path.join(d, 'status.json'), st)
        write_json(os.path.join(d, 'take.json'), {'id': tid, 'name': clean_name(filename), 'file': os.path.basename(filename),
                                                  'created': now_iso()})
        return tid, path

    def abort_upload(self, tid):
        shutil.rmtree(self.folder(tid), ignore_errors=True)

    def finish_upload(self, tid):
        d = self.folder(tid)
        try:                                                # refuse now, even while another take is cutting
            src = next((os.path.join(d, f) for f in sorted(os.listdir(d)) if f.startswith('source.')), None)
            if src:
                check_clip(src, lambda t: self._log(tid, t))
        except Refusal as e:
            self._discard_media(tid)
            self._fail(tid, str(e))
            return
        except MissingTool as e:                            # this runs on the HTTP thread: never leave the take "queued"
            self._log(tid, 'missing tool: %s' % e)
            self._fail(tid, missing_tool_copy(e))
            return
        except subprocess.TimeoutExpired as e:
            self._log(tid, 'the check timed out: %s' % e)
            self._fail(tid, COPY_CHECK_TIMEOUT)
            return
        except Exception:
            self._log(tid, traceback.format_exc())
            self._fail(tid, COPY_BUG)
            return
        waiting = self.q.qsize() + (1 if self.busy else 0)
        self._set(tid, 'queued', 0, 'Waiting for its turn' if waiting else 'Starting', force=True)
        self.q.put(tid)

    def recover(self):
        """A server restart kills the worker: a take that was mid-way would stay 'cutting' forever."""
        for tid in os.listdir(self.takes):
            st = read_json(os.path.join(self.takes, tid, 'status.json'))
            if st and st.get('stage') in STALE:
                msg = 'The server restarted before this clip was finished. Drop it in again.'
                write_json(os.path.join(self.takes, tid, 'status.json'),
                           {'stage': 'error', 'progress': 0, 'message': msg, 'error': msg})

    def source_of(self, tid):
        d = self.folder(tid)
        try:
            return next((os.path.join(d, f) for f in sorted(os.listdir(d)) if f.startswith('source.') and f.lower().endswith(VIDEO_EXTS)), None)
        except OSError:
            return None

    def retry(self, tid):
        """Queue a failed take again; it resumes from its first unfinished stage (see resume_point). Returns that stage.
        RetryError: 404 no such take (the sample too), 409 it did not fail, 422 the upload is gone (a refused clip: the
        message is the reason it was refused)."""
        item = self.get(tid) if tid != 'sample' else None
        if not item:
            raise RetryError(404, 'No such take.')
        st = item['status'] or {}
        if st.get('stage') != 'error':
            raise RetryError(409, 'This take has not failed (it is %s).' % (st.get('stage') or 'unknown'))
        if not self.source_of(tid):
            raise RetryError(422, st.get('message') or 'The uploaded file is gone. Add the clip again.')
        with self.lock:
            if tid == self.busy or tid in list(self.q.queue):
                raise RetryError(409, 'This take is already queued.')
            stage = self.resume_point(tid)
            self._log(tid, 'retry: resuming from %s' % stage)
            waiting = self.q.qsize() + (1 if self.busy else 0)
            self._set(tid, 'queued', 0, 'Waiting for its turn' if waiting else 'Starting', force=True)
            self.q.put(tid)
        return stage

    def done_stages(self, tid):
        """The stages finished in order, each still backed by its files (stages.json says which ones ended; a stage that
        died half-way left files that must not be trusted)."""
        d = self.folder(tid)
        marked = read_json(os.path.join(d, 'stages.json'), []) or []
        take = read_json(os.path.join(d, 'take.json'), {}) or {}
        tier2 = take.get('tier') == 2
        need = {'checking': ['stage.mp4'] + (['audio.m4a'] if take.get('hasAudio') else []),
                'cutting': ['person.webm'] + (['person_proxy.webm'] if tier2 else []),
                'measuring': ['measure.json'], 'shadow': ['shadow.webm']}
        out = []
        for name in STAGE_ORDER:
            if name not in marked or not all(os.path.exists(os.path.join(d, f)) for f in need[name]):
                break
            if name == 'checking' and not take.get('frames'):
                break
            if name == 'measuring' and 'k0' not in take:
                break
            out.append(name)
        return out

    def resume_point(self, tid):
        done = self.done_stages(tid)
        return next((n for n in STAGE_ORDER if n not in done), 'words')

    def _mark_stage(self, tid, stage):
        f = os.path.join(self.folder(tid), 'stages.json')
        marked = read_json(f, []) or []
        if stage not in marked:
            write_json(f, marked + [stage])

    def shutdown(self):
        p = self.proc
        if p and p.poll() is None:
            kill_tree(p)

    # -- the worker ------------------------------------------------------------------------------------------
    def _set(self, tid, stage, progress, message, force=False, **extra):
        now = time.time()
        if not force and now - self._last_write < 0.4:
            return
        self._last_write = now
        progress = round(max(0.0, min(1.0, progress)), 3)
        st = {'stage': stage, 'progress': progress, 'overall': self._overall(stage, progress), 'message': message}
        st.update(extra)
        self.last[tid] = st
        write_json(os.path.join(self.folder(tid), 'status.json'), st)

    @staticmethod
    def _overall(stage, progress):
        if stage == 'ready':
            return 1.0
        done = 0.0
        for name, weight in WEIGHTS:
            if name == stage:
                return round(done + weight * progress, 3)
            done += weight
        return 0.0

    def _worker(self):
        while True:
            tid = self.q.get()
            self.busy = tid
            try:
                self.process(tid)
            except Refusal as e:
                self._discard_media(tid)
                self._fail(tid, str(e))
            except PipelineError as e:
                self._fail(tid, str(e))
            except MissingTool as e:
                self._log(tid, 'missing tool: %s' % e)
                self._fail(tid, missing_tool_copy(e))
            except Exception:                           # a bug: keep the details in the log, not on the screen
                self._log(tid, traceback.format_exc())
                self._fail(tid, COPY_BUG)
            finally:
                self.busy = None

    def _log(self, tid, text):
        try:
            with open(os.path.join(self.folder(tid), 'log.txt'), 'a', encoding='utf-8') as f:
                f.write('%s  %s\n' % (time.strftime('%H:%M:%S'), text))
        except OSError:
            pass

    def _fail(self, tid, msg):
        self._log(tid, 'ERROR: ' + msg)
        self._set(tid, 'error', 0, msg, force=True, error=msg)

    def _discard_media(self, tid):
        """After a refusal: the upload and everything made from it go; the log, the status and the card's name stay."""
        d = self.folder(tid)
        for f in os.listdir(d):
            if f not in ('log.txt', 'status.json', 'take.json'):
                try:
                    os.remove(os.path.join(d, f))
                except OSError:
                    pass

    # -- the whole take ---------------------------------------------------------------------------------------
    def process(self, tid):
        d = self.folder(tid)
        log = lambda t: self._log(tid, t)
        take = read_json(os.path.join(d, 'take.json'), {'id': tid})
        src_up = next((os.path.join(d, f) for f in sorted(os.listdir(d)) if f.startswith('source.') and f.lower().endswith(VIDEO_EXTS)), None)
        if not src_up:
            raise PipelineError('The uploaded file is missing. Drop the clip in again.')
        timings = {}
        t_stage = [time.time()]
        have = self.done_stages(tid)                                  # a retry skips what is already made
        write_json(os.path.join(d, 'stages.json'), have)

        def done(stage):
            timings[stage] = round(time.time() - t_stage[0], 1)
            t_stage[0] = time.time()
            if stage != 'words':
                self._mark_stage(tid, stage)
            log('stage %s done in %.1f s' % (stage, timings[stage]))

        # 1 -- checking ----------------------------------------------------------------------------------------
        self._set(tid, 'checking', 0.05, 'Checking your clip', force=True)
        check_clip(src_up, log)                             # again: a take can reach the queue another way
        try:
            info = probe(src_up)
        except PipelineError as e:
            log('probe failed: %s' % e)
            raise Refusal(COPY_CANT_OPEN)
        refuse_if_too_long(info['dur'] if info['dur'] > 0 else info['frames'] / info['fps'], log)
        log('probe: %s' % {k: info[k] for k in ('w', 'h', 'rot', 'codec', 'pix_fmt', 'fps', 'vfr', 'frames', 'dur', 'audio', 'bitrate')})
        t = tier(info)
        sw, sh = stage_size(t)
        stage = os.path.join(d, 'stage.mp4')
        plain = (src_up.lower().endswith('.mp4') and info['codec'] == 'h264' and info['pix_fmt'] == 'yuv420p'
                 and info['rot'] == 0 and (info['w'], info['h']) == (sw, sh) and not info['vfr']
                 and info['fps'] <= 60 and not info['hdr'])
        if 'checking' in have:
            log('resuming: stage.mp4, the poster and the sound are already made')
            vi = probe(stage)
        else:
            if plain:
                vi = info
                shutil.copyfile(src_up, stage)
            else:
                self._set(tid, 'checking', 0.2, 'Converting your clip to %d x %d' % (sw, sh), force=True)
                log('normalising to %dx%d cfr h264 (tier %d)' % (sw, sh, t))
                to_stage(src_up, stage, info, t, lambda line: log('ffmpeg: ' + line))
                vi = probe(stage)
        fps, frames = vi['fps'], vi['frames']
        fps_str = info_fps_str(vi)
        dur = round(frames / fps, 3)
        has_audio = bool(vi['audio'])
        audio = os.path.join(d, 'audio.m4a')
        if 'checking' in have:
            has_audio = bool(take.get('hasAudio'))
        else:
            if os.path.exists(audio):
                os.remove(audio)
            # poster and sound are cheap: do them now so the card has a picture while the cutout runs
            code, _, err = run([tool('ffmpeg'), '-y', '-v', 'error', '-ss', '%.3f' % (dur / 2), '-i', stage, '-frames:v', '1',
                                '-vf', 'scale=360:640', '-q:v', '3', os.path.join(d, 'poster.jpg')], timeout=120)
            if code != 0:
                log('poster failed (exit %s): %s' % (code, err.strip()[-300:]))
            if has_audio:
                acodec = ['-c:a', 'copy'] if vi['audio'] == 'aac' else ['-c:a', 'aac', '-b:a', '192k']
                code, _, err = run([tool('ffmpeg'), '-y', '-v', 'error', '-i', stage, '-vn'] + acodec + [audio], timeout=300)
                if code != 0 or not os.path.exists(audio) or os.path.getsize(audio) == 0:
                    log('sound extraction failed (exit %s): %s' % (code, err.strip()[-300:]))
                    if os.path.exists(audio):
                        os.remove(audio)
                    has_audio = False                           # never point at a file that is not there
            take.update({'id': tid, 'name': take.get('name') or clean_name(take.get('file')),
                         'file': take.get('file') or os.path.basename(src_up), 'tier': t,
                         'w': STAGE_BASE[0], 'h': STAGE_BASE[1], 'fps': fps_value(fps), 'frames': frames, 'dur': dur,
                         'bitrate': info['bitrate'], 'hasAudio': has_audio,
                         'out': {'w': sw, 'h': sh, 'fps': fps_value(fps), 'fpsStr': fps_str,
                                 'bitrate': int(max(info['bitrate'], MIN_OUT_BITRATE))},
                         'files': {'person': 'person.webm', 'preview': 'person_proxy.webm' if t == 2 else 'person.webm',
                                   'shadow': 'shadow.webm', 'audio': 'audio.m4a' if has_audio else None},
                         'warnings': []})
            write_json(os.path.join(d, 'take.json'), take)
        done('checking')

        # 2 -- cutting -----------------------------------------------------------------------------------------
        person = os.path.join(d, 'person.webm')
        preview = os.path.join(d, 'person_proxy.webm') if t == 2 else person
        if 'cutting' in have:
            log('resuming: the cutout is already made')
        else:
            for f in (person, preview):
                if os.path.exists(f):
                    os.remove(f)
            fake = os.environ.get('FT_FAKE_MATTE') == '1'
            key = '%s-%d' % (machine_provider(), t)
            spf, guess = sec_per_frame(key)
            if fake:
                cmd, env = fake_matte_command(person, sw, sh, fps_str, frames)
            else:
                cmd, env = self.matte_cmd(stage, person, matte.downsample_for(sh), 'auto')
            log('cutting%s (%s, about %.1f s per frame%s): %s' % (' with the FAKE cutout' if fake else '', key, spf,
                                                                  ', a guess' if guess else '', ' '.join(map(str, cmd[:6]))))
            share = 1.0 - PROXY_SHARE if t == 2 else 1.0
            measured = self._cut(tid, cmd, env, person, frames, spf, guess, share, fake, log)
            if t == 2:
                self._set(tid, 'cutting', share, 'Making a quick preview of your cutout', force=True)
                try:
                    make_proxy(person, preview, fps_str, frames)
                except PipelineError as e:
                    log('proxy failed: %s' % e)
                    raise PipelineError('We couldn\'t make the preview of your cutout. Try again, and if it keeps happening, '
                                        'ask Claude for help.')
            if not fake and frames:
                try:
                    log('measured %.2f s per frame (stored %s: %.3f)' % (measured, key, record_sec_per_frame(key, measured)))
                except OSError as e:                            # a read-only home must not turn a good cut into an error
                    log('could not save the timing (%s): %s' % (key, e))
        done('cutting')

        # 3 -- measuring (always the 1080 picture: the proxy for a 4K take) ------------------------------------
        if 'measuring' in have:
            log('resuming: the measurements are already made')
            fields, warnings = {'k0': take['k0']}, take.get('warnings') or []
        else:
            self._set(tid, 'measuring', 0, 'Finding your feet and height', force=True)
            fields, diag = measure(preview, STAGE_BASE[0], STAGE_BASE[1], fps,
                                   lambda n: self._set(tid, 'measuring', n / frames, 'Finding your feet and height'))
            if not diag['found']:
                raise PipelineError("We couldn't find a person in this clip. Make sure you are in the frame, from head to toe, "
                                    'then add it again.')
            if diag['frames'] != frames:
                log('measured %d frames, the stage has %d' % (diag['frames'], frames))
                raise PipelineError(COPY_CUT_STOPPED)
            warnings = take_warnings(info, fields, diag)
            take.update(fields)
            take['warnings'] = warnings
            write_json(os.path.join(d, 'take.json'), take)
            diag['source'] = {'w': info['w'], 'h': info['h'], 'fps': info['fps'], 'bitrate': info['bitrate'],
                              'codec': info['codec'], 'rot': info['rot']}      # the upload as it came (export reads it)
            write_json(os.path.join(d, 'measure.json'), diag)
            if diag['oneShoeFrames']:
                log('feet: one shoe found in %d frame(s), used the lowest rows: %s' % (len(diag['oneShoeFrames']), diag['oneShoeFrames'][:20]))
        done('measuring')

        # 4 -- shadow ------------------------------------------------------------------------------------------
        if 'shadow' in have:
            log('resuming: the shadow is already made')
        else:
            self._set(tid, 'shadow', 0, 'Drawing your shadow', force=True)
            make_shadow(preview, os.path.join(d, 'shadow.webm'), fps_str, frames, dur, fields['k0'],
                        lambda n: self._set(tid, 'shadow', n / frames, 'Drawing your shadow'), log)
        done('shadow')

        # 5 -- words -------------------------------------------------------------------------------------------
        if not has_audio:
            wmsg = 'No sound in this clip'
        elif self.words_fn is None and not words.available():
            wmsg = "Skipping the words (speech reading isn't installed)"
        else:
            wmsg = 'Listening to what you say'
        self._set(tid, 'words', 0.1, wmsg, force=True)
        take.update(words_fields(audio if has_audio else stage, has_audio, log, self.words_fn))
        take['warnings'] = warnings
        take['created'] = take.get('created') or now_iso()
        done('words')
        write_json(os.path.join(d, 'take.json'), take)
        write_json(os.path.join(d, 'timings.json'), timings)
        self._set(tid, 'ready', 1, 'Ready', force=True)
        log('ready, stages: %s' % timings)

    # -- the cutout subprocess, watched -----------------------------------------------------------------------
    def _cut(self, tid, cmd, env, person, frames, spf, guess, share, fake, log):
        """Run the cutout command, keep status.json honest while it runs (progress, eta, etaGuess) and return the
        measured seconds per frame. A failure raises PipelineError with friendly copy; the raw output goes to the log."""
        self.proc = proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                            encoding='utf-8', errors='replace', env=env, creationflags=NO_WINDOW,
                                            **({} if os.name == 'nt' else {'start_new_session': True}))
        lines = queue.Queue()
        threading.Thread(target=lambda p=proc: [lines.put(l.rstrip()) for l in p.stdout], daemon=True).start()
        t0 = time.time()
        seen, tail, first = (0, t0), [], True            # (frames reported, when)
        last_progress, stall, stalled = t0, cut_stall_limit(spf), False       # the watchdog: a wedged cutout must not hold the queue
        while True:
            try:
                while True:
                    line = lines.get_nowait()
                    tail.append(line)
                    del tail[:-30]
                    if line.startswith('rvm_matte:'):
                        last_progress = time.time()
                    m = re.search(r'rvm_matte: (\d+) frames', line)
                    if m:
                        seen = (int(m.group(1)), time.time())
            except queue.Empty:
                pass
            if not stalled and proc.poll() is None and time.time() - last_progress > stall:
                stalled = True
                log('cutout stalled: no progress line for %d s, stopping it' % (time.time() - last_progress))
                kill_tree(proc)
            if proc.poll() is not None and lines.empty():
                time.sleep(0.2)
                if lines.empty():
                    break
                continue
            # between the real lines (one per 48 frames) estimate from the rate so far
            n_seen, t_seen = seen
            rate_now = (n_seen / (t_seen - t0)) if n_seen and t_seen > t0 else 1.0 / spf
            est = min(n_seen + 47, n_seen + (time.time() - t_seen) * rate_now, frames - 1)
            left = max(1.0, (frames - est) / rate_now)
            self._set(tid, 'cutting', share * est / frames, 'Cutting you out of the background, %s left' % left_text(left),
                      force=first, eta=int(round(left)), etaGuess=guess)
            first = False
            time.sleep(0.5)
        code = proc.wait()
        elapsed = time.time() - t0
        self.proc = None
        for l in tail:
            log('cut: ' + l)
        if code != 0 or not os.path.exists(person) or not (fake or any('rvm_matte: OK' in l for l in tail)):
            log('cutout failed: exit code %s' % code)
            if any('MODEL_MISSING' in l for l in tail):
                raise PipelineError(COPY_NO_MODEL)
            raise PipelineError(COPY_CUT_STOPPED)
        return elapsed / frames if frames else spf
