"""The take's sound (audio.m4a) starts where the take's first picture frame starts, whatever the two tracks' start
times in the file are (finding F-10). A click at a known time of the sound's own track shows where the sound lands."""
import os
import shutil
import subprocess

import numpy as np
import pytest

from conftest import X264, _ffmpeg
from ft import pipeline
from ft.paths import Workspace
from test_pipeline import fake_env, made, run_take  # noqa: F401  (the autouse fake_env and the helpers)

RATE = 44100
CLICK = "aevalsrc='if(between(t,1,1.01),0.8*sin(2*PI*1000*t),0)':s=44100:d=2"


def clip(folder, name, video_offset=0.0, audio_offset=0.0, size='1080x1920'):
    """A 2 s 1080x1920 H.264 + AAC clip; the sound is silent except a click at 1.000 s of its own track."""
    out = folder / name
    _ffmpeg('-f', 'lavfi', '-itsoffset', video_offset, '-i', "smptebars=s=%s:r=30:d=2,drawbox=x=0:y=0:w=iw:h=ih:color=red:t=fill:enable='eq(n,0)'" % size,
            '-f', 'lavfi', '-itsoffset', audio_offset, '-i', CLICK,
            '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', *X264, '-c:a', 'aac', '-ac', '1', out)
    return out


def starts(path):
    out = {}
    for kind in ('v', 'a'):
        r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', kind + ':0', '-show_entries', 'stream=start_time',
                            '-of', 'csv=p=0', str(path)], capture_output=True, text=True, check=True)
        out[kind] = float(r.stdout.strip().splitlines()[0])
    return out


def click_time(path):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path), '-vn', '-ac', '1', '-ar', str(RATE),
                        '-f', 'f32le', '-'], capture_output=True, check=True)
    x = np.frombuffer(r.stdout, dtype=np.float32)
    hit = np.nonzero(np.abs(x) > 0.3)[0]
    assert len(hit), 'no click in the sound'
    return hit[0] / RATE


def packets(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'a:0', '-count_packets', '-show_entries',
                        'stream=nb_read_packets', '-of', 'csv=p=0', str(path)], capture_output=True, text=True, check=True)
    return int(r.stdout.strip().splitlines()[0])


def frames(path):
    r = subprocess.run(['ffprobe', '-v', 'error', '-count_frames', '-select_streams', 'v:0', '-show_entries',
                        'stream=nb_read_frames', '-of', 'csv=p=0', str(path)], capture_output=True, text=True, check=True)
    return int(r.stdout.strip().splitlines()[0])


def first_frame_is_red(path):
    r = subprocess.run(['ffmpeg', '-v', 'error', '-nostdin', '-i', str(path), '-frames:v', '1', '-vf', 'crop=iw:ih/8,scale=8:8,format=rgb24',
                        '-f', 'rawvideo', '-'], capture_output=True, check=True)
    px = np.frombuffer(r.stdout, dtype=np.uint8).reshape(-1, 3)
    return px[:, 0].mean() > 200 and px[:, 2].mean() < 80


def take_sound(ws, made, src):
    pipe = made(ws)
    tid, st, take = run_take(pipe, src)
    assert st['stage'] == 'ready', st
    d = pipe.folder(tid)
    return d, take


def check_stage(d, src):
    stage = os.path.join(d, 'stage.mp4')
    s = starts(stage)
    assert s['v'] == pytest.approx(0.0, abs=0.001) and s['a'] == pytest.approx(0.0, abs=0.03)
    assert frames(stage) == frames(src)                              # exactly the source's picture frames
    assert first_frame_is_red(stage)                                 # and its first frame: no lead-in
    ref = d + '/ref_copy.m4a'
    _ffmpeg('-i', stage, '-vn', '-c:a', 'copy', ref)
    assert open(os.path.join(d, 'audio.m4a'), 'rb').read() == open(ref, 'rb').read()       # audio.m4a: the plain copy


def test_sound_late_is_filled_with_silence(ws, made, tmp_path):
    src = clip(tmp_path, 'late.mp4', audio_offset=0.376)              # 1080x1920 H.264: it would be a plain copy
    assert starts(src)['a'] - starts(src)['v'] == pytest.approx(0.376, abs=0.03)
    d, _ = take_sound(ws, made, src)
    assert open(os.path.join(d, 'stage.mp4'), 'rb').read() != open(src, 'rb').read()          # converted, not copied
    check_stage(d, src)
    assert click_time(os.path.join(d, 'audio.m4a')) == pytest.approx(1.376, abs=0.015)
    assert 'the sound started 0.3' in open(os.path.join(d, 'log.txt'), encoding='utf-8').read()


def test_sound_late_on_the_conversion_path(ws, made, tmp_path):
    src = clip(tmp_path, 'late720.mp4', audio_offset=0.376, size='1280x720')
    d, _ = take_sound(ws, made, src)
    check_stage(d, src)
    assert click_time(os.path.join(d, 'audio.m4a')) == pytest.approx(1.376, abs=0.015)


def test_sound_early_is_cut_at_its_start(ws, made, tmp_path):
    src = clip(tmp_path, 'early.mp4', video_offset=0.25)
    assert starts(src)['a'] - starts(src)['v'] == pytest.approx(-0.25, abs=0.03)
    d, _ = take_sound(ws, made, src)
    check_stage(d, src)
    # the click is at 1.000 s of the file's timeline; the muxer put the first picture frame at 0.266 s, not 0.250
    assert click_time(os.path.join(d, 'audio.m4a')) == pytest.approx(1.0 - starts(src)['v'], abs=0.015)


def test_sound_early_on_the_conversion_path(ws, made, tmp_path):
    src = clip(tmp_path, 'early720.mp4', video_offset=0.25, size='1280x720')
    d, _ = take_sound(ws, made, src)
    check_stage(d, src)
    assert click_time(os.path.join(d, 'audio.m4a')) == pytest.approx(1.0 - starts(src)['v'], abs=0.015)


def test_both_tracks_start_late_by_different_amounts(ws, made, tmp_path):
    src = clip(tmp_path, 'diff.mp4', video_offset=1.0, audio_offset=0.5)
    d, _ = take_sound(ws, made, src)
    check_stage(d, src)
    assert click_time(os.path.join(d, 'audio.m4a')) == pytest.approx(1.0 - (starts(src)['v'] - 0.5), abs=0.015)
    assert click_time(os.path.join(d, 'audio.m4a')) == pytest.approx(0.5, abs=0.02)          # moved by -0.5 s


def test_both_tracks_start_late_together_stays_a_plain_copy(ws, made, tmp_path):
    src = clip(tmp_path, 'both.mp4', video_offset=0.5, audio_offset=0.5)
    s = starts(src)
    assert abs(s['a'] - s['v']) <= 0.030 and s['v'] > 0.4      # an AAC frame of encoder priming shows in a's start
    d, _ = take_sound(ws, made, src)
    out = os.path.join(d, 'audio.m4a')
    assert click_time(out) == pytest.approx(1.0, abs=0.03)      # not shifted; the copy keeps its own 23 ms of priming
    assert open(os.path.join(d, 'stage.mp4'), 'rb').read() == open(src, 'rb').read()         # unchanged: a byte copy
    ref = tmp_path / 'ref.m4a'
    _ffmpeg('-i', os.path.join(d, 'stage.mp4'), '-vn', '-c:a', 'copy', ref)
    assert packets(out) == packets(ref)
    assert open(out, 'rb').read() == open(ref, 'rb').read()


def test_sound_at_zero_is_byte_for_byte_the_old_copy(ws, made, tmp_path):
    src = clip(tmp_path, 'zero.mp4')
    d, _ = take_sound(ws, made, src)
    out = os.path.join(d, 'audio.m4a')
    assert open(os.path.join(d, 'stage.mp4'), 'rb').read() == open(src, 'rb').read()
    ref = tmp_path / 'ref.m4a'
    _ffmpeg('-i', os.path.join(d, 'stage.mp4'), '-vn', '-c:a', 'copy', ref)
    assert open(out, 'rb').read() == open(ref, 'rb').read()
    assert click_time(out) == pytest.approx(1.0, abs=0.015)
