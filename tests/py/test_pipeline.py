"""ft.pipeline: the take pipeline end to end (the cutout is the fake one: FT_FAKE_MATTE=1), tiers, refusals, estimates."""
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

from conftest import X264, _make
from ft import paths, pipeline
from ft.paths import Workspace


@pytest.fixture(autouse=True)
def fake_env(tmp_path, monkeypatch):
    """Every test: the fake cutout, and a private user folder (machine.json must never touch the real one)."""
    monkeypatch.setenv('FT_FAKE_MATTE', '1')
    monkeypatch.delenv('FT_FAKE_MATTE_DELAY', raising=False)
    monkeypatch.setenv('FLOORED_HOME', str(tmp_path / 'home'))


@pytest.fixture
def made():
    pipes = []

    def make(ws, **kw):
        p = pipeline.Pipeline(ws, **kw)
        pipes.append(p)
        return p
    yield make
    for p in pipes:
        p.shutdown()


def add(pipe, src, filename=None):
    tid, dst = pipe.begin_upload(filename or os.path.basename(str(src)))
    shutil.copyfile(src, dst)
    pipe.finish_upload(tid)
    return tid


def wait(pipe, tid, timeout=120):
    deadline = time.time() + timeout
    st = {}
    while time.time() < deadline:
        st = pipeline.read_json(os.path.join(pipe.folder(tid), 'status.json')) or {}
        if st.get('stage') in ('ready', 'error'):
            return st
        time.sleep(0.05)
    raise AssertionError('timed out: %s' % st)


def run_take(pipe, src, filename=None, timeout=120):
    tid = add(pipe, src, filename)
    st = wait(pipe, tid, timeout)
    return tid, st, pipeline.read_json(os.path.join(pipe.folder(tid), 'take.json'))


def video_size(path, codec=None):
    cmd = ['ffprobe', '-v', 'error'] + (['-c:v', codec] if codec else []) + [
        '-count_frames', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,nb_read_frames', '-of', 'json',
        str(path)]
    s = json.loads(subprocess.run(cmd, capture_output=True, text=True, check=True).stdout)['streams'][0]
    return int(s['width']), int(s['height']), int(s['nb_read_frames'])


def test_tier1_end_to_end(ws, made, portrait_1080):
    pipe = made(ws)
    tid, st, take = run_take(pipe, portrait_1080)
    assert st['stage'] == 'ready', st
    d = pipe.folder(tid)
    assert take['tier'] == 1
    assert take['files'] == {'person': 'person.webm', 'preview': 'person.webm', 'shadow': 'shadow.webm', 'audio': 'audio.m4a'}
    assert take['out'] == {'w': 1080, 'h': 1920, 'fps': 30, 'fpsStr': '30', 'bitrate': take['out']['bitrate']}
    assert take['out']['bitrate'] == take['bitrate'] > 0                       # the upload's own: no minimum is added
    assert (take['w'], take['h'], take['fps'], take['frames']) == (1080, 1920, 30, 15)
    assert take['feet'] and take['k0'] and take['aoWidth'] and take['height'] > 150
    assert video_size(os.path.join(d, 'person.webm'), 'libvpx-vp9') == (1080, 1920, 15)
    for name in ('stage.mp4', 'shadow.webm', 'audio.m4a', 'poster.jpg', 'take.json', 'status.json', 'log.txt'):
        assert os.path.exists(os.path.join(d, name)), name
    assert not os.path.exists(os.path.join(d, 'person_proxy.webm'))
    assert video_size(os.path.join(d, 'poster.jpg'))[:2] == (360, 640)


def test_tier2_end_to_end(ws, made, hevc_4k):
    pipe = made(ws)
    tid, st, take = run_take(pipe, hevc_4k)
    assert st['stage'] == 'ready', st
    d = pipe.folder(tid)
    assert take['tier'] == 2
    assert take['files']['person'] == 'person.webm' and take['files']['preview'] == 'person_proxy.webm'
    assert take['out']['w'] == 2160 and take['out']['h'] == 3840 and take['out']['fps'] == 24
    n = take['frames']
    assert video_size(os.path.join(d, 'person.webm'), 'libvpx-vp9') == (2160, 3840, n)
    assert video_size(os.path.join(d, 'person_proxy.webm'), 'libvpx-vp9') == (1080, 1920, n)
    assert video_size(os.path.join(d, 'stage.mp4'))[:2] == (2160, 3840)
    assert 0 < take['feet']['x'] <= 1080 and 0 < take['feet']['y'] <= 1920       # measured on the 1080 proxy
    assert (take['w'], take['h']) == (1080, 1920)


def test_long_take_refused_fast(ws, made, clip_12s):
    pipe = made(ws)
    t0 = time.time()
    tid, st, take = run_take(pipe, clip_12s, timeout=10)
    assert time.time() - t0 < 10
    assert st['stage'] == 'error' and '10 seconds' in st['error']
    d = pipe.folder(tid)
    assert not os.path.exists(os.path.join(d, 'person.webm'))
    assert set(os.listdir(d)) <= {'log.txt', 'status.json', 'take.json'}          # no media is kept
    assert os.path.exists(os.path.join(d, 'log.txt'))


def test_no_video_stream_refused(ws, made, tmp_path):
    audio_only = tmp_path / 'sound.mp4'
    subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'lavfi', '-i', 'sine=d=1', '-c:a', 'aac', str(audio_only)],
                   check=True)
    pipe = made(ws)
    tid, st, _ = run_take(pipe, audio_only, timeout=20)
    assert st['stage'] == 'error' and 'video' in st['error'].lower()
    assert set(os.listdir(pipe.folder(tid))) <= {'log.txt', 'status.json', 'take.json'}


def test_unreadable_source_has_friendly_copy(ws, made, tmp_path):
    junk = tmp_path / 'broken.mp4'
    junk.write_bytes(b'this is not a video' * 100)
    pipe = made(ws)
    tid, st, _ = run_take(pipe, junk, timeout=20)
    assert st['stage'] == 'error' and st['error'].startswith("We couldn't open this video")
    assert 'ffmpeg' not in st['error'].lower() and 'Traceback' not in st['error']


def test_spaces_and_accents(tmp_path, made, portrait_1080):
    ws = Workspace(tmp_path / 'Área de Trabalho' / 'meu reel').ensure()
    pipe = made(ws)
    tid, st, take = run_take(pipe, portrait_1080, filename='vídeo final 1.mov')
    assert st['stage'] == 'ready', st
    assert take['name'] == 'vídeo final 1'
    assert os.path.exists(os.path.join(pipe.folder(tid), 'person.webm'))


def test_silent_take(ws, made, no_audio):
    pipe = made(ws)
    tid, st, take = run_take(pipe, no_audio)
    assert st['stage'] == 'ready', st
    assert take['files']['audio'] is None and take['hasAudio'] is False
    assert not os.path.exists(os.path.join(pipe.folder(tid), 'audio.m4a'))
    assert take['tier'] == 1 and take['out']['w'] == 1080


def test_eta_while_cutting(ws, made, portrait_1080, monkeypatch):
    monkeypatch.setenv('FT_FAKE_MATTE_DELAY', '2.5')                 # test only: the fake cutout takes a while
    pipe = made(ws)
    tid = add(pipe, portrait_1080)
    seen, stop = [], threading.Event()

    def poll():
        while not stop.is_set():
            st = pipeline.read_json(os.path.join(pipe.folder(tid), 'status.json')) or {}
            if st.get('stage') == 'cutting':
                seen.append(st)
            time.sleep(0.03)
    t = threading.Thread(target=poll, daemon=True)
    t.start()
    st = wait(pipe, tid)
    stop.set()
    t.join()
    assert st['stage'] == 'ready', st
    assert any(s.get('eta', 0) > 0 for s in seen), seen[:3]
    assert all(s.get('etaGuess') is True for s in seen if 'eta' in s)       # nothing measured yet on this machine
    assert 'eta' not in st


def _stand_in_cut(delay=0.0):
    """A stand-in for the real cutout (a command that prints the OK line), so the non-fake path can be tested."""
    script = ('import subprocess, sys, time\n'
              'src, dst = sys.argv[1], sys.argv[2]\n'
              'time.sleep(%s)\n'
              'r = subprocess.call(["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", "format=yuva420p", "-c:v", '
              '"libvpx-vp9", "-b:v", "1M", "-auto-alt-ref", "0", "-deadline", "realtime", "-cpu-used", "8", dst])\n'
              'print("rvm_matte: OK" if r == 0 else "rvm_matte: MISMATCH")\n'
              'sys.exit(r)\n' % delay)

    def make(src, dst, downsample=0.75, provider='auto'):
        return [sys.executable, '-c', script, os.path.abspath(src), os.path.abspath(dst)], dict(os.environ)
    return make


def test_matte_command_arguments():
    cmd, env = pipeline.matte_command('a.mp4', 'b.webm', 0.375, 'dml')
    assert cmd[cmd.index('--downsample') + 1] == '0.375' and cmd[cmd.index('--provider') + 1] == 'dml'
    cmd, _ = pipeline.matte_command('a.mp4', 'b.webm')
    assert cmd[cmd.index('--downsample') + 1] == '0.75' and cmd[cmd.index('--provider') + 1] == 'auto'


def test_real_cut_path_records_seconds_per_frame(ws, made, portrait_1080, monkeypatch):
    monkeypatch.delenv('FT_FAKE_MATTE')
    pipe = made(ws, matte_cmd=_stand_in_cut())
    _, st, take = run_take(pipe, portrait_1080)
    assert st['stage'] == 'ready', st
    machine = json.loads((paths.user_dir() / 'machine.json').read_text(encoding='utf-8'))
    spf = machine['secPerFrame']['cpu-1']
    assert 1.7 - 1e-6 < spf < 3.4                          # 0.5 * 3.4 (the default) + 0.5 * a fast stand-in
    # the next run starts from the measured value: no longer a guess
    pipe2 = made(ws, matte_cmd=_stand_in_cut(delay=2.5))
    tid = add(pipe2, portrait_1080)
    seen = []
    while True:
        s = pipeline.read_json(os.path.join(pipe2.folder(tid), 'status.json')) or {}
        if s.get('stage') == 'cutting':
            seen.append(s)
        if s.get('stage') in ('ready', 'error'):
            break
        time.sleep(0.03)
    assert any(x.get('eta') and x.get('etaGuess') is False for x in seen), seen[:2]


def test_fake_cut_never_records_timing(ws, made, portrait_1080):
    pipe = made(ws)
    run_take(pipe, portrait_1080)
    assert not (paths.user_dir() / 'machine.json').exists()


@pytest.mark.parametrize('lines,code,expect', [
    (['MODEL_MISSING /x/y.onnx'], 4, "The cutout tool isn't set up yet"),
    (['rvm_matte: MISMATCH 1080x1920'], 1, 'The cutout stopped before the end'),
    (['Traceback (most recent call last):', 'KeyError: boom'], 1, 'The cutout stopped before the end'),
])
def test_cut_failures_have_friendly_copy(ws, made, portrait_1080, monkeypatch, lines, code, expect):
    monkeypatch.delenv('FT_FAKE_MATTE')

    def failing(src, dst, downsample=0.75, provider='auto'):
        script = 'import sys\nprint(%r)\nsys.exit(%d)' % ('\n'.join(lines), code)
        return [sys.executable, '-c', script], dict(os.environ)
    pipe = made(ws, matte_cmd=failing)
    tid, st, _ = run_take(pipe, portrait_1080)
    assert st['stage'] == 'error' and st['error'].startswith(expect)
    assert 'MISMATCH' not in st['error'] and 'Traceback' not in st['error'] and 'KeyError' not in st['error']
    log = open(os.path.join(pipe.folder(tid), 'log.txt'), encoding='utf-8').read()
    assert lines[-1] in log                                         # the raw details are in the log


def _hanging_cut(src, dst, downsample=0.75, provider='auto'):
    """A cutout that starts, says nothing and never finishes (a wedged driver)."""
    return [sys.executable, '-c', 'import time; print("rvm_matte: starting", flush=True); time.sleep(120)'], dict(os.environ)


def test_stall_limit_scales_with_the_speed_and_has_a_floor():
    assert pipeline.cut_stall_limit(0.1) == 600                            # the floor: 10 minutes
    assert pipeline.cut_stall_limit(3.4) == pytest.approx(20 * 3.4 * 48)   # twenty progress intervals of 48 frames


def test_a_cutout_that_hangs_is_stopped_with_friendly_copy(ws, made, portrait_1080, monkeypatch):
    monkeypatch.delenv('FT_FAKE_MATTE')
    monkeypatch.setattr(pipeline, 'cut_stall_limit', lambda spf: 2.0)       # test only: the real floor is 10 minutes
    pipe = made(ws, matte_cmd=_hanging_cut)
    t0 = time.time()
    tid, st, _ = run_take(pipe, portrait_1080, timeout=60)
    assert time.time() - t0 < 40 and st['stage'] == 'error' and st['error'].startswith('The cutout stopped')
    log = open(os.path.join(pipe.folder(tid), 'log.txt'), encoding='utf-8').read()
    assert 'no progress' in log
    assert pipe.proc is None


def test_a_slow_cutout_that_keeps_reporting_is_not_stopped(ws, made, portrait_1080, monkeypatch):
    monkeypatch.delenv('FT_FAKE_MATTE')
    monkeypatch.setattr(pipeline, 'cut_stall_limit', lambda spf: 2.0)
    inner = _stand_in_cut()

    def chatty(src, dst, downsample=0.75, provider='auto'):
        cmd, env = inner(src, dst, downsample, provider)
        script = ('import time\nfor i in range(8):\n    print("rvm_matte: %d frames" % (i * 48), flush=True)\n'
                  '    time.sleep(0.7)\n') + cmd[2]
        return [cmd[0], '-c', script] + cmd[3:], env
    pipe = made(ws, matte_cmd=chatty)
    _, st, _ = run_take(pipe, portrait_1080, timeout=90)                    # 5.6 s of progress lines, longer than the limit
    assert st['stage'] == 'ready', st


def test_words_fn_is_used(ws, made, portrait_1080):
    result = {'transcript': 'Hi there.', 'language': 'en', 'words': [{'word': 'Hi', 'start': 0.1, 'end': 0.3}]}
    pipe = made(ws, words_fn=lambda path, log: result)
    _, st, take = run_take(pipe, portrait_1080)
    assert st['stage'] == 'ready'
    assert (take['transcript'], take['language'], take['words']) == ('Hi there.', 'en', result['words'])


def test_measure_json_kept_for_the_export(ws, made, portrait_1080):
    pipe = made(ws)
    tid, st, take = run_take(pipe, portrait_1080)
    meas = pipeline.read_json(os.path.join(pipe.folder(tid), 'measure.json'))
    assert meas['source']['w'] == 1080 and meas['source']['bitrate'] > 0


# --- the length guard: a clip with no stated duration, the grace, and refusing while another take is cutting ---------

def durationless_webm(tmp_path, seconds=12, fps=5):
    """What a MediaRecorder or screen recorder writes: a webm streamed to a non-seekable output, so no duration."""
    out = tmp_path / 'recording.webm'
    with open(out, 'wb') as f:
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-nostdin', '-f', 'lavfi', '-i',
                        'smptebars=s=108x192:r=%d:d=%s' % (fps, seconds), '-c:v', 'libvpx-vp9', '-deadline', 'realtime',
                        '-cpu-used', '8', '-b:v', '200k', '-f', 'webm', 'pipe:1'], stdout=f, check=True)
    return out


def test_durationless_container_is_measured_and_refused(ws, made, tmp_path):
    src = durationless_webm(tmp_path)
    shown = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(src)],
                           capture_output=True, text=True).stdout.strip()
    assert shown in ('', 'N/A'), 'the test clip must have no duration in its header: %r' % shown
    assert pipeline.packet_duration(src) > 11                       # the packets know how long it runs
    pipe = made(ws)
    t0 = time.time()
    tid, st, _ = run_take(pipe, src, timeout=15)
    assert time.time() - t0 < 15
    assert st['stage'] == 'error' and 'This clip is 12' in st['error'] and '10 seconds' in st['error'], st
    d = pipe.folder(tid)
    assert not os.path.exists(os.path.join(d, 'person.webm'))
    assert not os.path.exists(os.path.join(d, 'stage.mp4'))


def test_durationless_container_is_caught_after_the_probe_too(ws, made, tmp_path, monkeypatch):
    """If the quick packet check cannot tell (0.0) and a take reaches the worker anyway, the probe's frames/fps still do."""
    src = durationless_webm(tmp_path)
    monkeypatch.setattr(pipeline, 'packet_duration', lambda path: 0.0)
    pipe = made(ws)
    tid, dst = pipe.begin_upload('recording.webm')
    shutil.copyfile(src, dst)
    pipe.q.put(tid)                                                 # skip the upload-time check on purpose
    st = wait(pipe, tid, 30)
    assert st['stage'] == 'error' and '10 seconds' in st['error'], st
    assert not os.path.exists(os.path.join(pipe.folder(tid), 'person.webm'))
    assert not os.path.exists(os.path.join(pipe.folder(tid), 'stage.mp4'))


def test_probe_tolerates_missing_duration(tmp_path):
    info = pipeline.probe(durationless_webm(tmp_path, seconds=3))
    assert info['dur'] == pytest.approx(3.0, abs=0.3) and info['frames'] == 15


def test_grace_boundary(ws, made, tmp_path):
    ok = _make(tmp_path, 'ten_two.mp4', '108x192', 5, 10.2, 'libx264', X264, audio=False)
    over = _make(tmp_path, 'ten_three.mp4', '108x192', 10, 10.3, 'libx264', X264, audio=False)
    pipe = made(ws)
    _, st, take = run_take(pipe, ok, timeout=120)
    assert st['stage'] == 'ready', st                               # 10.2 s is inside the grace
    assert 'long' in [w['code'] for w in take['warnings']]
    tid, st, _ = run_take(pipe, over, timeout=15)
    assert st['stage'] == 'error' and st['error'] == ('This clip is 10.3 seconds long. Trim it to 10 seconds or less and '
                                                      'add it again.'), st
    assert not os.path.exists(os.path.join(pipe.folder(tid), 'person.webm'))


def test_refusal_does_not_wait_for_a_take_that_is_cutting(ws, made, portrait_1080, clip_12s, monkeypatch):
    monkeypatch.setenv('FT_FAKE_MATTE_DELAY', '20')                 # test only: the first take is busy for a while
    pipe = made(ws)
    first = add(pipe, portrait_1080)
    deadline = time.time() + 30
    while (pipeline.read_json(os.path.join(pipe.folder(first), 'status.json')) or {}).get('stage') != 'cutting':
        assert time.time() < deadline, 'the first take never started cutting'
        time.sleep(0.05)
    t0 = time.time()
    second = add(pipe, clip_12s)
    st = wait(pipe, second, 10)
    assert time.time() - t0 < 10
    assert st['stage'] == 'error' and '10 seconds' in st['error'], st
    assert (pipeline.read_json(os.path.join(pipe.folder(first), 'status.json')) or {}).get('stage') == 'cutting'
    assert pipe.q.qsize() == 0                                      # it never joined the queue


# --- a failed side step must not become a failed take --------------------------------------------------------------

def test_failed_sound_extraction_leaves_no_dangling_file(ws, made, portrait_1080, monkeypatch):
    real_run = pipeline.run

    def run(cmd, *a, **kw):
        if '-vn' in cmd:
            return 1, '', 'Simulated: no audio encoder'
        return real_run(cmd, *a, **kw)
    monkeypatch.setattr(pipeline, 'run', run)
    pipe = made(ws)
    tid, st, take = run_take(pipe, portrait_1080)
    assert st['stage'] == 'ready', st
    assert take['hasAudio'] is False and take['files']['audio'] is None
    assert not os.path.exists(os.path.join(pipe.folder(tid), 'audio.m4a'))
    assert 'Simulated: no audio encoder' in open(os.path.join(pipe.folder(tid), 'log.txt'), encoding='utf-8').read()


def test_failed_poster_is_only_logged(ws, made, portrait_1080, monkeypatch):
    real_run = pipeline.run

    def run(cmd, *a, **kw):
        if 'poster.jpg' in str(cmd[-1]):
            return 1, '', 'Simulated: poster failed'
        return real_run(cmd, *a, **kw)
    monkeypatch.setattr(pipeline, 'run', run)
    pipe = made(ws)
    tid, st, take = run_take(pipe, portrait_1080)
    assert st['stage'] == 'ready' and take['hasAudio'] is True
    assert 'Simulated: poster failed' in open(os.path.join(pipe.folder(tid), 'log.txt'), encoding='utf-8').read()


def test_unwritable_machine_json_does_not_fail_a_good_cut(ws, made, portrait_1080, monkeypatch):
    monkeypatch.delenv('FT_FAKE_MATTE')
    real_write = pipeline.write_json

    def write_json(path, data):
        if os.path.basename(str(path)) == 'machine.json':
            raise PermissionError(13, 'Simulated: read-only home')
        return real_write(path, data)
    monkeypatch.setattr(pipeline, 'write_json', write_json)
    pipe = made(ws, matte_cmd=_stand_in_cut())
    tid, st, take = run_take(pipe, portrait_1080)
    assert st['stage'] == 'ready', st
    assert take['feet'] and take['files']['person'] == 'person.webm'
    assert 'could not save the timing' in open(os.path.join(pipe.folder(tid), 'log.txt'), encoding='utf-8').read()
