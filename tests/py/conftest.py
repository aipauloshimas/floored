import http.client
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
APP = REPO / 'plugin' / 'skills' / 'floored' / 'app'
sys.path.insert(0, str(APP))


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _loopback():
    from ft import server                      # the server's own opener: no system or environment proxy
    return server.LOOPBACK


class Response:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    def json(self):
        return json.loads(self.body.decode('utf-8'))


class ServerHandle:
    def __init__(self, base, proc):
        self.base, self.proc = base, proc

    def request(self, path, method='GET', data=None, headers=None, timeout=30):
        if isinstance(data, (dict, list)):
            data = json.dumps(data).encode('utf-8')
            headers = dict({'Content-Type': 'application/json'}, **(headers or {}))
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers or {})
        try:
            with _loopback().open(req, timeout=timeout) as r:
                return Response(r.status, r.headers, r.read())
        except urllib.error.HTTPError as e:
            return Response(e.code, e.headers, e.read())

    def get(self, path, headers=None, timeout=30):
        return self.request(path, headers=headers, timeout=timeout)

    def get_json(self, path):
        return self.get(path).json()

    def post_json(self, path, obj):
        return self.request(path, 'POST', obj)


def kill_tree(proc):
    """Stop a server and everything it started (ffmpeg, npx, node...)."""
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/T', '/F', '/PID', str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


@pytest.fixture
def server_factory(tmp_path_factory):
    """server_factory(workspace_dir, extra_env=None, utf8=True) starts `floored.py serve` on a free port and returns
    a ServerHandle. The server's output goes to a log file (never a pipe nobody reads); utf8=False removes
    PYTHONUTF8 / PYTHONIOENCODING so Windows redirects output in the ANSI code page.

    Ready means GET /api/info answered 200: an open socket is not enough (the first connection can land before the
    server loop runs and be reset). A port that someone else took between free_port() and the server's bind makes the
    server exit with "cannot listen": the fixture then tries another port (up to 3 times)."""
    started = []

    def make(workspace, extra_env=None, utf8=True):
        env = dict(os.environ, PYTHONUNBUFFERED='1', FLOORED_HOME=str(tmp_path_factory.mktemp('ft-home')))
        if utf8:
            env['PYTHONUTF8'] = '1'
        else:
            env.pop('PYTHONUTF8', None)
            env.pop('PYTHONIOENCODING', None)
        env.update(extra_env or {})
        for attempt in range(3):
            port = free_port()
            log_path = tmp_path_factory.mktemp('ft-log') / 'server.log'
            log = open(log_path, 'wb')
            cmd = [sys.executable, str(APP / 'floored.py'), 'serve', '--workspace', str(workspace), '--port', str(port)]
            proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env,
                                    start_new_session=(os.name != 'nt'))
            started.append((proc, log))
            handle = ServerHandle('http://127.0.0.1:%d' % port, proc)
            handle.log_path = log_path
            deadline = time.time() + 30
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    if handle.get('/api/info', timeout=2).status == 200:
                        return handle
                except (OSError, http.client.HTTPException):
                    time.sleep(0.1)
            text = log_path.read_text(encoding='utf-8', errors='replace')
            if proc.poll() is not None and 'cannot listen' in text and attempt < 2:
                continue
            raise RuntimeError('server did not start: %s' % text)

    yield make
    for proc, log in started:
        kill_tree(proc)
        log.close()


# ------------------------------------------------------------------------------------------------ phone-footage clips
# Tiny synthetic clips (ffmpeg lavfi), generated once per session. All are 0.5 s except vfr (1 s) and clip_12s.

def _ffmpeg(*args):
    r = subprocess.run(['ffmpeg', '-y', '-v', 'error', '-nostdin', *map(str, args)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r


def _make(folder, name, size, rate, dur, vcodec, vextra=(), vf=None, audio=True):
    """One synthetic clip: SMPTE bars, plus a 440 Hz mono 44.1 kHz tone."""
    out = folder / name
    args = ['-f', 'lavfi', '-i', 'smptebars=s=%s:r=%s:d=%s' % (size, rate, dur)]
    if audio:
        args += ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100:duration=%s' % dur]
    if vf:
        args += ['-vf', vf]
    args += ['-c:v', vcodec, *vextra]
    if audio:
        args += ['-c:a', 'aac', '-ac', '1']
    _ffmpeg(*args, out)
    return out


X264 = ['-preset', 'ultrafast', '-pix_fmt', 'yuv420p']


@pytest.fixture(scope='session')
def clips(tmp_path_factory):
    return tmp_path_factory.mktemp('clips')


@pytest.fixture(scope='session')
def portrait_1080(clips):
    return _make(clips, 'portrait_1080.mp4', '1080x1920', 30, 0.5, 'libx264', X264)


@pytest.fixture(scope='session')
def landscape_1080(clips):
    """1920x1080, no rotation flag (also the stored picture of iphone_rot)."""
    return _make(clips, 'iphone_base.mp4', '1920x1080', 30, 0.5, 'libx264', X264)


@pytest.fixture(scope='session')
def iphone_rot(clips, landscape_1080):
    """A phone clip: stored 1920x1080, a display matrix of 90 degrees says it is shown as 1080x1920."""
    base = landscape_1080
    out = clips / 'iphone_rot.mp4'
    _ffmpeg('-display_rotation:v:0', 90, '-i', base, '-c', 'copy', out)
    return out


@pytest.fixture(scope='session')
def hevc_4k(clips):
    return _make(clips, 'hevc_4k.mp4', '2160x3840', 24, 0.25, 'libx265',
                 ['-preset', 'ultrafast', '-pix_fmt', 'yuv420p', '-tag:v', 'hvc1', '-x265-params', 'log-level=error'])


@pytest.fixture(scope='session')
def hlg_10bit(clips):
    return _make(clips, 'hlg_10bit.mp4', '360x640', 30, 0.5, 'libx265',
                 ['-preset', 'ultrafast', '-pix_fmt', 'yuv420p10le', '-tag:v', 'hvc1',
                  '-color_primaries', 'bt2020', '-color_trc', 'arib-std-b67', '-colorspace', 'bt2020nc',
                  '-x265-params', 'log-level=error:colorprim=bt2020:transfer=arib-std-b67:colormatrix=bt2020nc'])


@pytest.fixture(scope='session')
def vfr(clips):
    """60 fps source keeping 2 frames of every 4: timestamps step 1/60, 3/60, 1/60... so r_frame_rate says 60 and the
    average is 30 (what a phone does when it drops frames in low light)."""
    return _make(clips, 'vfr.mp4', '360x640', 60, 1, 'libx264', X264 + ['-fps_mode', 'vfr'],
                 vf="select='lt(mod(n,4),2)'", audio=False)


@pytest.fixture(scope='session')
def fps120(clips):
    return _make(clips, 'fps120.mp4', '360x640', 120, 0.5, 'libx264', X264)


@pytest.fixture(scope='session')
def tall_20_9(clips):
    return _make(clips, 'tall_20_9.mp4', '1080x2400', 30, 0.5, 'libx264', X264)


@pytest.fixture(scope='session')
def no_audio(clips):
    return _make(clips, 'no_audio.mp4', '360x640', 30, 0.5, 'libx264', X264, audio=False)


@pytest.fixture(scope='session')
def clip_12s(clips):
    return _make(clips, 'clip_12s.mp4', '180x320', 30, 12, 'libx264', X264)


# ---------------------------------------------------------------------------------------- synthetic person cutouts
# 1080x1920 VP9-alpha clips (30 frames at 24 fps): a white "person" (ellipse head and torso, two legs, two shoe blocks)
# on a transparent background. The sole midpoint of the two shoes is (540 + dx, 1700). Generated once per session.

PERSON_W, PERSON_H, PERSON_FRAMES, PERSON_FPS = 1080, 1920, 30, 24
PERSON_FEET = (540, 1700)
PERSON_TOP = 400                         # so the person is 1300 px tall


def _person_alpha(dx=0, arm=False, second=False, legs=True):
    a = np.zeros((PERSON_H, PERSON_W), np.uint8)
    yy, xx = np.ogrid[:PERSON_H, :PERSON_W]
    a[((xx - (540 + dx)) / 180.0) ** 2 + ((yy - 850) / 450.0) ** 2 <= 1] = 255        # head and torso
    if not legs:                                                                          # cut flat at the hips, as the
        a[1000:] = 0                                                                      # cutout does at a steep angle
        return a
    for cx in (480, 600):                                                                 # legs, then shoes
        a[1300:1700, cx + dx - 40:cx + dx + 40] = 255
        a[1671:1701, cx + dx - 40:cx + dx + 40] = 255
    if arm:
        a[800:861, 700:1080] = 255                                                        # reaches the right edge
    if second:
        a[900:1380, 40:240] = 255                                                         # about 30 % of the person's area
    return a


def _write_person(path, frame_fn):
    cmd = ['ffmpeg', '-y', '-v', 'error', '-nostdin', '-f', 'rawvideo', '-pix_fmt', 'rgba',
           '-s', '%dx%d' % (PERSON_W, PERSON_H), '-r', str(PERSON_FPS), '-i', '-', '-c:v', 'libvpx-vp9',
           '-pix_fmt', 'yuva420p', '-auto-alt-ref', '0', '-b:v', '0', '-crf', '30', '-deadline', 'realtime',
           '-cpu-used', '8', str(path)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    for i in range(PERSON_FRAMES):
        a = frame_fn(i)
        rgba = np.empty(a.shape + (4,), np.uint8)
        rgba[..., :3] = 255
        rgba[..., 3] = a
        p.stdin.write(rgba.tobytes())
    p.stdin.close()
    err = p.stderr.read()
    assert p.wait() == 0, err.decode('utf-8', 'replace')
    return path


@pytest.fixture(scope='session')
def person_clips(tmp_path_factory):
    return tmp_path_factory.mktemp('person_clips')


@pytest.fixture(scope='session')
def person_basic(person_clips):
    return _write_person(person_clips / 'basic.webm', lambda i: _person_alpha())


@pytest.fixture(scope='session')
def person_edge(person_clips):
    return _write_person(person_clips / 'edge.webm', lambda i: _person_alpha(arm=10 <= i <= 20))


@pytest.fixture(scope='session')
def person_moving(person_clips):
    """The feet slide 120 px to the right, evenly, over the whole clip."""
    return _write_person(person_clips / 'moving.webm',
                         lambda i: _person_alpha(dx=int(round(120.0 * i / (PERSON_FRAMES - 1)))))


@pytest.fixture(scope='session')
def person_step(person_clips):
    """The feet stand still, then step 120 px to the right for the last 20 % of the clip."""
    return _write_person(person_clips / 'step.webm',
                         lambda i: _person_alpha(dx=120 if i >= int(PERSON_FRAMES * 0.8) else 0))


@pytest.fixture(scope='session')
def person_glitch(person_clips):
    """Still feet; in two frames the shoe finder is fooled and the feet jump 120 px (a hand near the floor)."""
    return _write_person(person_clips / 'glitch.webm', lambda i: _person_alpha(dx=120 if i in (14, 15) else 0))


@pytest.fixture(scope='session')
def person_nolegs(person_clips):
    """The cutout lost the legs and feet: the silhouette ends flat at the hips."""
    return _write_person(person_clips / 'nolegs.webm', lambda i: _person_alpha(legs=False))


@pytest.fixture(scope='session')
def person_hand_low(person_clips):
    """Still feet; a hand hangs out to the side at hip height for the whole clip. It sits inside the old 260 px shoe
    band and ends one row above today's 140 px band (rows 1480-1559; the band starts at 1560), so it pins that value."""
    def frame(i):
        a = _person_alpha()
        a[1480:1560, 300:380] = 255                                                       # the hand, apart from the legs
        a[1150:1480, 330:360] = 255                                                       # its arm, joined to the body
        a[1150:1180, 330:420] = 255
        return a
    return _write_person(person_clips / 'hand_low.webm', frame)


@pytest.fixture(scope='session')
def person_two(person_clips):
    return _write_person(person_clips / 'two.webm', lambda i: _person_alpha(second=True))


@pytest.fixture(scope='session')
def person_empty(person_clips):
    return _write_person(person_clips / 'empty.webm', lambda i: np.zeros((PERSON_H, PERSON_W), np.uint8))


# ---------------------------------------------------------------------------------------------------------- workspace
@pytest.fixture
def ws(tmp_path):
    """A Workspace in a temp project folder, with its takes/ and exports/ folders made."""
    from ft.paths import Workspace
    return Workspace(tmp_path / 'proj').ensure()
