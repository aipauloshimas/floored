"""ft.matte: the vendored RVM cutout (4K downsample rule, providers, GPU parity, CLI contract)."""
import json
import os
import subprocess
import sys
import time

import numpy as np
import pytest

from ft import matte, paths
from ft.proc import tool

APP = paths.APP_DIR
SAMPLE = paths.SAMPLE_DIR


def _gpu_provider():
    """A non-CPU provider that this machine's onnxruntime really offers, else None."""
    import onnxruntime as ort
    have = ort.get_available_providers()
    for name, ep in (('dml', 'DmlExecutionProvider'), ('coreml', 'CoreMLExecutionProvider')):
        if ep in have:
            return name
    return None


GPU = _gpu_provider()
needs_gpu_provider = pytest.mark.skipif(
    GPU is None, reason='no GPU provider in this onnxruntime (needs onnxruntime-directml or the CoreML build)')
slow = pytest.mark.slow
needs_model = pytest.mark.skipif(not paths.rvm_model_path().is_file(), reason='RVM weights not installed')


def _ff(*args):
    r = subprocess.run([tool('ffmpeg'), '-y', '-v', 'error', '-nostdin', *map(str, args)], capture_output=True)
    assert r.returncode == 0, r.stderr.decode('utf-8', 'replace')


def _run(src, dst, *extra, env=None):
    t0 = time.time()
    r = subprocess.run([sys.executable, '-m', 'ft.matte', str(src), str(dst), *extra], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', cwd=str(APP), env=dict(os.environ, PYTHONUTF8='1', **(env or {})))
    return r, time.time() - t0


def _info(path, decode_vp9=False):
    dec = ['-c:v', 'libvpx-vp9'] if decode_vp9 else []
    r = subprocess.run([tool('ffprobe'), '-v', 'error', *dec, '-count_frames', '-select_streams', 'v:0', '-show_entries',
                        'stream=width,height,nb_read_frames', '-of', 'json', str(path)], capture_output=True, text=True)
    s = json.loads(r.stdout)['streams'][0]
    return int(s['width']), int(s['height']), int(s['nb_read_frames'])


def _alpha_planes(path, n=12):
    """First n frames of a VP9 alpha webm as float alpha arrays (0..1), at full size."""
    w, h, _ = _info(path, True)
    r = subprocess.run([tool('ffmpeg'), '-v', 'error', '-nostdin', '-c:v', 'libvpx-vp9', '-i', str(path), '-frames:v', str(n),
                        '-vf', 'alphaextract,format=gray', '-f', 'rawvideo', '-'], capture_output=True)
    assert r.returncode == 0, r.stderr
    a = np.frombuffer(r.stdout, np.uint8)
    assert a.size == n * w * h, (a.size, n, w, h)
    return a.reshape(n, h, w).astype(np.float32) / 255


@pytest.fixture(scope='module')
def clip_12(tmp_path_factory):
    """The first 0.5 s of the sample take: 12 frames at 24 fps, 1080x1920."""
    out = tmp_path_factory.mktemp('matte') / 'clip12.mp4'
    _ff('-i', SAMPLE / 'source.mp4', '-frames:v', 12, '-an', '-c:v', 'libx264', '-crf', 12, '-pix_fmt', 'yuv420p', out)
    assert _info(out)[2] == 12
    return out


# ------------------------------------------------------------------------------------------------------------ fast
def test_downsample_for():
    assert matte.downsample_for(1920) == 0.75
    assert matte.downsample_for(3840) == 0.375


def test_providers_cpu_and_fallback(monkeypatch, capsys):
    monkeypatch.setattr(matte, '_available', lambda: ['CPUExecutionProvider'])
    assert matte.providers('cpu') == ['CPUExecutionProvider']
    # asked for a provider this onnxruntime lacks: CPU, and it says so on stderr
    assert matte.providers('dml') == ['CPUExecutionProvider']
    assert 'dml' in capsys.readouterr().err
    monkeypatch.setattr(matte, '_available', lambda: ['DmlExecutionProvider', 'CPUExecutionProvider'])
    assert matte.providers('dml') == ['DmlExecutionProvider', 'CPUExecutionProvider']
    monkeypatch.setattr(matte, '_available', lambda: ['CoreMLExecutionProvider', 'CPUExecutionProvider'])
    assert matte.providers('coreml') == ['CoreMLExecutionProvider', 'CPUExecutionProvider']


def test_providers_auto_reads_machine_json(tmp_path, monkeypatch):
    monkeypatch.setenv('FLOORED_HOME', str(tmp_path))
    monkeypatch.setattr(matte, '_available', lambda: ['DmlExecutionProvider', 'CPUExecutionProvider'])
    assert matte.providers('auto') == ['CPUExecutionProvider']                      # no machine.json
    (tmp_path / 'machine.json').write_text('{ not json', encoding='utf-8')
    assert matte.providers('auto') == ['CPUExecutionProvider']                      # corrupt
    (tmp_path / 'machine.json').write_text('{"matteProvider": "dml"}', encoding='utf-8')
    assert matte.providers('auto') == ['DmlExecutionProvider', 'CPUExecutionProvider']
    (tmp_path / 'machine.json').write_text('{"matteProvider": "cpu"}', encoding='utf-8')
    assert matte.providers('auto') == ['CPUExecutionProvider']
    (tmp_path / 'machine.json').write_text('[1, 2]', encoding='utf-8')
    assert matte.providers('auto') == ['CPUExecutionProvider']                      # wrong shape


def test_missing_model(tmp_path):
    r, _ = _run(tmp_path / 'nope.mp4', tmp_path / 'out.webm', env={'FLOORED_RVM_MODEL': str(tmp_path / 'none.onnx')})
    assert r.returncode == 4, r.stderr
    assert 'MODEL_MISSING' in r.stdout + r.stderr
    assert str(tmp_path / 'none.onnx') in r.stdout + r.stderr


def test_model_flag_overrides(tmp_path):
    r, _ = _run(tmp_path / 'nope.mp4', tmp_path / 'out.webm', '--model', str(tmp_path / 'x.onnx'))
    assert r.returncode == 4 and 'MODEL_MISSING' in r.stdout + r.stderr


def test_worst_diff_share():
    a = np.zeros((2, 4, 4), np.float32)
    b = a.copy()
    b[1, 0, :2] = 10 / 255          # 2 of 16 pixels on frame 1 differ by more than 4/255
    b[0, 0, 0] = 4 / 255            # exactly 4/255: not more than
    assert matte._worst_diff_share(a, b) == pytest.approx(2 / 16)
    assert matte._worst_diff_share(a, a) == 0.0


def test_parity_refuses_an_unavailable_provider(monkeypatch, tmp_path):
    monkeypatch.setattr(matte, '_available', lambda: ['CPUExecutionProvider'])
    # must not run (no clip, no model needed): CPU against CPU would report a pass for nothing
    res = matte.parity(tmp_path / 'none.mp4', 'dml', model=tmp_path / 'none.onnx')
    assert res['ok'] is False and res['worst'] == 1.0 and 'dml' in res['reason']


def test_pipeline_matte_command_is_absolute_and_importable(tmp_path, monkeypatch):
    from ft.pipeline import matte_command
    monkeypatch.chdir(tmp_path)
    cmd, env = matte_command(os.path.join('floored', 'takes', 't1', 'source.mp4'),
                             os.path.join('floored', 'takes', 't1', 'person.webm'))
    assert cmd[1:3] == ['-m', 'ft.matte']
    assert os.path.isabs(cmd[3]) and os.path.isabs(cmd[4])
    assert cmd[3] == str(tmp_path / 'floored' / 'takes' / 't1' / 'source.mp4')
    # no cwd needed: the child imports ft through PYTHONPATH
    r = subprocess.run([cmd[0], '-c', 'import ft.matte'], cwd=str(tmp_path), env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


# ------------------------------------------------------------------------------------------------------------ slow
@slow
@needs_model
def test_sample_12_frames(tmp_path, clip_12):
    out = tmp_path / 'p.webm'
    r, secs = _run(clip_12, out, '--downsample', '0.75')
    print('sample 12 frames 1080p: %.1f s' % secs)
    assert r.returncode == 0 and 'rvm_matte: OK' in r.stdout, r.stdout + r.stderr
    assert _info(out, True) == (1080, 1920, 12)
    mine, shipped = _alpha_planes(out), _alpha_planes(SAMPLE / 'person.webm')
    assert abs(float(mine.mean()) - float(shipped.mean())) <= 0.02


@slow
@needs_model
def test_4k_12_frames(tmp_path, clip_12):
    big = tmp_path / 'clip12_4k.mp4'
    _ff('-i', clip_12, '-vf', 'scale=2160:3840:flags=lanczos', '-c:v', 'libx264', '-crf', 12, '-pix_fmt', 'yuv420p', big)
    out = tmp_path / 'p4k.webm'
    r, secs = _run(big, out, '--downsample', '0.375')
    print('4K 12 frames @0.375: %.1f s' % secs)
    assert r.returncode == 0 and 'rvm_matte: OK' in r.stdout, r.stdout + r.stderr
    assert _info(out, True) == (2160, 3840, 12)


@slow
@needs_model
@needs_gpu_provider
def test_gpu_parity(clip_12):
    # Product behaviour, not a hardware property: whether this card matches the processor depends on the machine (the doctor
    # then keeps the processor). What must hold everywhere: a well-formed answer, and "ok" meaning exactly "within the threshold".
    res = matte.parity(clip_12, GPU)
    print('gpu parity worst: %.4f (threshold %s)' % (res['worst'], matte.PARITY_WORST))
    assert set(res) == {'ok', 'worst'} and isinstance(res['ok'], bool)
    assert 0 <= res['worst'] <= 1
    assert res['ok'] == (res['worst'] <= matte.PARITY_WORST)


def _fake_ort(with_telemetry_switch):
    import types
    calls = []
    ort = types.ModuleType('onnxruntime')
    ort.SessionOptions = type('SessionOptions', (), {})
    ort.ExecutionMode = type('ExecutionMode', (), {'ORT_SEQUENTIAL': 1})
    ort.InferenceSession = lambda model, options, providers=None: ('session', str(model))
    if with_telemetry_switch:
        ort.disable_telemetry_events = lambda: calls.append('off')
    return ort, calls


def test_onnxruntime_telemetry_is_turned_off_once(monkeypatch):
    """The official Windows wheels emit telemetry events: nothing leaves the computer, so they are disabled."""
    ort, calls = _fake_ort(True)
    monkeypatch.setitem(sys.modules, 'onnxruntime', ort)
    monkeypatch.setattr(matte, '_telemetry_off', False, raising=False)
    matte._session('m.onnx', [matte.CPU_EP])
    matte._session('m.onnx', [matte.CPU_EP])
    assert calls == ['off']


def test_a_build_without_the_telemetry_switch_still_loads(monkeypatch):
    ort, _ = _fake_ort(False)
    monkeypatch.setitem(sys.modules, 'onnxruntime', ort)
    monkeypatch.setattr(matte, '_telemetry_off', False, raising=False)
    assert matte._session('m.onnx', [matte.CPU_EP]) == ('session', 'm.onnx')
