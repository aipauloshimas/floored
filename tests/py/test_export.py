"""ft.export: the MP4 at the take's own quality, from the locally installed pinned HyperFrames (never npx).

Fast tests: the helpers (bitrate flag, out/files, the post-render check, the speed update) and the missing-renderer error.
Slow tests (`pytest -m slow tests/py/test_export.py`) render for real: the sample (1080), a native 4K take, with the network
cut, in a folder with spaces and accents, and a take without sound. They need the renderer installed in the user folder
(`npm install --prefix ~/.floored/renderer hyperframes@0.9.22`) and its Chrome (`hyperframes browser ensure`).
"""
import json
import os
import shutil
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

import pytest

import imgcmp
from conftest import APP, REPO

from ft import export, paths

sys.path.insert(0, str(REPO / 'dev' / 'bench'))
import make  # noqa: E402

SAMPLE = APP / 'sample'
INSTANTS = [0.6, 2.0, 4.6]
RENDER_WAIT = 30 * 60
EVENTS = [{'t': 0.5, 'kind': 'whoosh', 'gain': 1.0}, {'t': 2.0, 'kind': 'hit', 'gain': 1.0}]
WALL = {}                                   # test name -> seconds of wall time (printed at the end of a slow run)


def _ff(*args):
    r = subprocess.run(['ffmpeg', '-y', '-v', 'error', '-nostdin', *map(str, args)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r


def _probe(path, entries, stream='v:0'):
    r = subprocess.run(['ffprobe', '-v', 'error', '-select_streams', stream, '-show_entries', entries, '-of', 'json', str(path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def settings(sound=None):
    s = make.make_settings('original', make.PHRASE, 'FREE', 'IN CLAUDE CODE', 'speech', [])
    if sound is not None:
        s['sound'] = sound
    return s


def run_export(srv, take_id, st=None, events=None, wait=RENDER_WAIT):
    r = srv.post_json('/api/export', {'takeId': take_id, 'settings': st or settings(), 'events': EVENTS if events is None else events})
    assert r.status == 200, r.body
    eid = r.json()['id']
    end = time.time() + wait
    status = {}
    while time.time() < end:
        status = srv.get_json('/api/exports/' + eid)
        if status['stage'] in ('done', 'error'):
            return status
        time.sleep(2)
    raise AssertionError('export did not finish: %s' % status)


def export_log(srv_workspace, status):
    return (Path(srv_workspace) / 'floored' / 'exports' / status['id'] / 'export.log').read_text(encoding='utf-8', errors='replace')


def renderer_env():
    return {'FLOORED_RENDERER_DIR': str(export.renderer_dir())}


def lufs(path):
    return export.loudness(str(path))


def gray(png):
    out = Path(str(png)[:-4] + '-gray.png')
    _ff('-i', png, '-vf', 'format=gray', out)
    return out


def frame_at(video, t, png):
    _ff('-ss', '%.3f' % t, '-i', video, '-frames:v', 1, png)
    return Path(png)


@pytest.fixture(scope='module')
def work(tmp_path_factory):
    return tmp_path_factory.mktemp('ftx')


def make_take(project, tid, mutate=None, drop=()):
    """A copy of the sample take in <project>/floored/takes/<tid>/ (its media are copied, read-only sample stays clean)."""
    ws = paths.Workspace(project).ensure()
    d = ws.takes / tid
    d.mkdir(parents=True, exist_ok=True)
    for n in os.listdir(SAMPLE):
        if n not in drop and n != 'source.mp4':
            shutil.copyfile(SAMPLE / n, d / n)
    take = json.loads((SAMPLE / 'take.json').read_text(encoding='utf-8'))
    take['id'] = tid
    if mutate:
        mutate(take, d)
    (d / 'take.json').write_text(json.dumps(take, indent=1), encoding='utf-8')
    return d


# ================================================================================================== fast: the helpers
def test_abr_bitrate_is_floor_plus_margin():
    assert export.abr_bitrate(5_371_982) == 8_400_000      # max(5.37, 8) Mbps x 1.05
    assert export.abr_bitrate(0) == 8_400_000
    assert export.abr_bitrate(8_000_000) == 8_400_000
    assert export.abr_bitrate(20_000_000) == 21_000_000    # exactly (no float creep to 21_000_001)
    assert export.abr_bitrate(11_400_000) == 11_970_000


OUT1 = {'w': 1080, 'h': 1920, 'fps': 24.0, 'fpsStr': '24', 'bitrate': 5_371_982}
OUT4 = {'w': 2160, 'h': 3840, 'fps': 23.976, 'fpsStr': '24000/1001', 'bitrate': 30_000_000}


def _flag(cmd, name):
    return cmd[cmd.index(name) + 1]


def test_render_cmd_is_a_near_lossless_crf_render_never_a_bitrate():
    c1 = export.render_cmd(['hf'], 'comp', 'render.mp4', OUT1)
    assert c1[:3] == ['hf', 'render', 'comp'] and _flag(c1, '-o') == 'render.mp4'
    assert _flag(c1, '--crf') == '8' and _flag(c1, '--fps') == '24' and _flag(c1, '--player-ready-timeout') == '120000'
    assert '--video-bitrate' not in c1 and '--resolution' not in c1
    c4 = export.render_cmd(['hf'], 'comp', 'render.mp4', OUT4)
    assert _flag(c4, '--fps') == '24000/1001' and _flag(c4, '--resolution') == 'portrait-4k' and _flag(c4, '--crf') == '8'


def test_encode_cmd_is_constant_quality_with_the_colour_tags_hyperframes_wrote():
    c = export.encode_cmd('render.mp4', 'video.mp4')
    assert os.path.basename(c[0]).lower().startswith('ffmpeg') and _flag(c, '-i') == 'render.mp4' and c[-1] == 'video.mp4'
    assert (_flag(c, '-c:v'), _flag(c, '-preset'), _flag(c, '-crf'), _flag(c, '-pix_fmt')) == ('libx264', 'slow', '14', 'yuv420p')
    assert '-b:v' not in c and '-an' in c and _flag(c, '-movflags') == '+faststart' and _flag(c, '-fps_mode') == 'passthrough'
    assert _flag(c, '-x264-params') == 'colorprim=bt709:transfer=bt709:colormatrix=bt709'


def _tags(path):
    code, out, err = export.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                 'stream=color_range,color_space,color_transfer,color_primaries', '-of', 'json', str(path)])
    assert code == 0, err
    return json.loads(out)['streams'][0]


def test_both_encodes_write_the_bt709_tags_into_the_stream_from_an_untagged_source(tmp_path):
    """ffmpeg 8.1 ignores -color_primaries / -color_trc as output options: only x264's own params tag the H.264 stream, so
    prove it on a source with no tags at all, for the CRF encode and for the two-pass floor encode."""
    src = tmp_path / 'src.mp4'
    _ff('-f', 'lavfi', '-i', 'testsrc2=s=128x224:r=24', '-frames:v', 12, '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', src)
    assert _tags(src).get('color_primaries') in (None, 'unknown')                         # really untagged
    want = {'color_range': 'tv', 'color_space': 'bt709', 'color_transfer': 'bt709', 'color_primaries': 'bt709'}
    crf = tmp_path / 'crf.mp4'
    r = subprocess.run(export.encode_cmd(str(src), str(crf)), capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-500:]
    assert {k: _tags(crf).get(k) for k in want} == want
    abr = tmp_path / 'abr.mp4'
    first, second = export.abr_cmds(str(src), str(abr), 8_000_000, 'x264pass')
    for cmd in (first, second):
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path)
        assert r.returncode == 0, r.stderr[-500:]
    assert {k: _tags(abr).get(k) for k in want} == want


def test_abr_cmds_are_two_passes_from_the_same_intermediate_at_the_floor():
    first, second = export.abr_cmds('render.mp4', 'video.mp4', 5_371_982, 'x264pass')
    for c, n in ((first, '1'), (second, '2')):
        assert _flag(c, '-i') == 'render.mp4' and _flag(c, '-b:v') == '8400000' and _flag(c, '-pass') == n
        assert _flag(c, '-passlogfile') == 'x264pass' and _flag(c, '-preset') == 'slow' and '-crf' not in c
        assert _flag(c, '-colorspace') == 'bt709'
    assert first[-3:] == ['-f', 'null', os.devnull] and second[-1] == 'video.mp4' and _flag(second, '-movflags') == '+faststart'
    assert _flag(export.abr_cmds('r', 'v', 40_000_000, 'p')[0], '-b:v') == '42000000'


class _Spy:
    """An Exporter whose commands are recorded, not run: _stream writes the destination file, probe_output answers from a script."""

    def __init__(self, tmp_path, monkeypatch, bitrates, fail_on=None):
        self.cmds, self.d = [], tmp_path
        self.exp = export.Exporter(None, tmp_path / 'exports')
        self.job = {'dir': str(tmp_path), 'id': 'x'}
        self.bitrates = list(bitrates)
        (tmp_path / 'render.mp4').write_bytes(b'0' * 2000)
        spy = self

        def stream(job, cmd, on_line, timeout, cwd=None, env=None):
            spy.cmds.append((cmd, cwd))
            if fail_on is not None and len(spy.cmds) == fail_on:
                return 1, ['boom']
            if cmd[-1] != os.devnull:
                Path(cmd[-1]).write_bytes(b'1' * 1000)
            else:                                                       # pass 1 leaves its stats files
                (tmp_path / 'x264pass-0.log').write_text('stats')
                (tmp_path / 'x264pass-0.log.mbtree').write_text('stats')
            return 0, []
        monkeypatch.setattr(self.exp, '_stream', stream)
        monkeypatch.setattr(export, 'probe_bitrate', lambda path: spy.bitrates.pop(0))

    def encode(self, out=OUT1):
        return self.exp._encode(self.job, str(self.d / 'render.mp4'), str(self.d / 'video.mp4'), out, 121, 1)

    def log(self):
        return (self.d / 'export.log').read_text(encoding='utf-8')


def test_encode_stays_at_crf_when_it_clears_the_floor(tmp_path, monkeypatch):
    spy = _Spy(tmp_path, monkeypatch, [20_000_000])
    info = spy.encode()
    assert len(spy.cmds) == 1 and _flag(spy.cmds[0][0], '-crf') == '14'
    assert info['floorReencode'] is False and info['crfBitrate'] == 20_000_000 and info['bitrate'] == 20_000_000
    log = spy.log()
    assert 'crf 14 slow gives 20.00 Mbps' in log and 'floor re-encode: not needed' in log


def test_encode_falls_back_to_two_pass_when_the_crf_result_is_under_the_floor(tmp_path, monkeypatch):
    spy = _Spy(tmp_path, monkeypatch, [6_360_000, 8_390_000])          # a flat look: crf gives 6.36 Mbps, the floor is 8
    info = spy.encode()
    kinds = [('crf' if '-crf' in c else 'pass' + _flag(c, '-pass')) for c, _ in spy.cmds]
    assert kinds == ['crf', 'pass1', 'pass2']
    assert all(_flag(c, '-i') == str(tmp_path / 'render.mp4') for c, _ in spy.cmds)             # always from the same intermediate
    assert all(cwd == str(tmp_path) for c, cwd in spy.cmds[1:])                                 # the pass log is a plain relative name
    assert info['floorReencode'] is True and info['crfBitrate'] == 6_360_000 and info['bitrate'] == 8_390_000
    assert info['abrBitrate'] == 8_400_000
    assert not [n for n in os.listdir(tmp_path) if n.startswith('x264pass')]                    # stats files removed
    log = spy.log()
    assert 'floor re-encode: ran' in log and 'two-pass at 8.40 Mbps' in log and 'gives 8.39 Mbps' in log


def test_the_floor_is_the_takes_own_bitrate_when_it_is_above_8_mbps(tmp_path, monkeypatch):
    spy = _Spy(tmp_path, monkeypatch, [25_000_000, 31_400_000])
    info = spy.encode(OUT4)                                           # a 30 Mbps take: 25 Mbps at crf is not enough
    assert info['floorReencode'] is True and info['floorMbps'] == 30.0
    assert _flag(spy.cmds[1][0], '-b:v') == '31500000'


def test_a_failed_encode_keeps_the_intermediate_and_the_log_says_where(tmp_path, monkeypatch):
    spy = _Spy(tmp_path, monkeypatch, [], fail_on=1)
    with pytest.raises(export.ExportError) as e:
        spy.encode()
    assert "couldn't be encoded" in str(e.value) and 'boom' in str(e.value)
    spy.exp._note_kept(spy.job)                                       # what the worker does after any failure
    assert (tmp_path / 'render.mp4').exists() and 'kept the intermediate at %s' % (tmp_path / 'render.mp4') in spy.log()


def test_a_failed_second_pass_still_removes_the_two_pass_logs(tmp_path, monkeypatch):
    spy = _Spy(tmp_path, monkeypatch, [6_360_000], fail_on=3)         # crf ok but under the floor, pass 1 ok, pass 2 fails
    with pytest.raises(export.ExportError):
        spy.encode()
    assert len(spy.cmds) == 3
    assert not [n for n in os.listdir(tmp_path) if n.startswith('x264pass')]


def test_nothing_is_said_about_the_intermediate_once_it_is_gone(tmp_path, monkeypatch):
    spy = _Spy(tmp_path, monkeypatch, [])
    (tmp_path / 'render.mp4').unlink()
    spy.exp._note_kept(spy.job)
    assert not (tmp_path / 'export.log').exists()


def test_out_and_files_come_from_the_take_with_fallbacks():
    take = json.loads((SAMPLE / 'take.json').read_text(encoding='utf-8'))
    assert export.out_spec(take) == {'w': 1080, 'h': 1920, 'fps': 24.0, 'fpsStr': '24', 'bitrate': take['out']['bitrate']}
    assert export.take_files(take) == {'person': 'person.webm', 'shadow': 'shadow.webm', 'audio': 'audio.m4a'}
    k4 = dict(take, out={'w': 2160, 'h': 3840, 'fps': 29.97, 'fpsStr': '30000/1001', 'bitrate': 40_000_000},
              files={'person': 'p.webm', 'preview': 'q.webm', 'shadow': 's.webm', 'audio': None})
    assert export.out_spec(k4)['h'] == 3840 and export.out_spec(k4)['fpsStr'] == '30000/1001'
    assert export.take_files(k4) == {'person': 'p.webm', 'shadow': 's.webm', 'audio': None}
    old = {'w': 1080, 'h': 1920, 'fps': 30, 'bitrate': 9_000_000, 'hasAudio': False}        # a take from before `out`/`files`
    assert export.out_spec(old)['fpsStr'] == '30' and export.take_files(old)['audio'] is None


def test_renderer_bin_is_local_and_never_npx(tmp_path, monkeypatch):
    monkeypatch.setenv('FLOORED_RENDERER_DIR', str(tmp_path / 'nope'))
    with pytest.raises(export.ExportError) as e:
        export.renderer_bin()
    assert str(e.value) == "The video maker isn't installed yet. Ask Claude to finish the setup."
    monkeypatch.delenv('FLOORED_RENDERER_DIR')
    monkeypatch.setenv('FLOORED_HOME', str(tmp_path / 'home'))
    bindir = tmp_path / 'home' / 'renderer' / 'node_modules' / '.bin'
    bindir.mkdir(parents=True)
    exe = bindir / ('hyperframes.cmd' if os.name == 'nt' else 'hyperframes')
    exe.write_text('x')
    assert export.renderer_bin() == [str(exe)]


def test_renderer_env_has_the_telemetry_opt_out(monkeypatch):
    monkeypatch.delenv('HYPERFRAMES_NO_TELEMETRY', raising=False)
    env = export.renderer_env()
    assert env['HYPERFRAMES_NO_TELEMETRY'] == '1' and env['DO_NOT_TRACK'] == '1' and env['HYPERFRAMES_NO_UPDATE_CHECK'] == '1'


def _clip(path, size='1080x1920', rate='24', n=24, bitrate='12M', audio=None, audio_args=()):
    args = ['-f', 'lavfi', '-i', 'testsrc2=s=%s:r=%s' % (size, rate), '-frames:v', n]
    if audio:
        args = ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=%s' % audio] + args
    args += ['-c:v', 'libx264', '-b:v', bitrate, '-minrate', bitrate, '-maxrate', bitrate, '-bufsize', '4M', '-nal-hrd', 'cbr',
             '-preset', 'ultrafast', '-pix_fmt', 'yuv420p']
    if audio:
        args += ['-c:a', 'aac'] + list(audio_args)
    _ff(*args, path)
    return path


def test_check_output_passes_a_file_that_matches(tmp_path):
    f = _clip(tmp_path / 'ok.mp4')
    out = {'w': 1080, 'h': 1920, 'fps': 24, 'fpsStr': '24', 'bitrate': 5_000_000}
    problems, numbers = export.check_output(str(f), out, 24, False)
    assert problems == []
    assert numbers['frames'] == 24 and numbers['frameRate'] == '24' and numbers['videoBitrate'] >= 0.98 * 8e6


def test_check_output_names_every_shortfall(tmp_path):
    f = _clip(tmp_path / 'small.mp4', size='540x960', rate='25', n=20, bitrate='2M')
    out = {'w': 1080, 'h': 1920, 'fps': 24, 'fpsStr': '24', 'bitrate': 5_000_000}
    problems, _ = export.check_output(str(f), out, 24, False)
    text = ' | '.join(problems)
    assert 'size 540x960' in text and 'frame rate 25' in text and '20 frames' in text
    assert 'bitrate' not in text                                               # the video bitrate is never a problem
    ntsc = {'w': 540, 'h': 960, 'fps': 23.976, 'fpsStr': '24000/1001', 'bitrate': 1_000_000}
    f2 = _clip(tmp_path / 'ntsc.mp4', size='540x960', rate='24000/1001', n=10, bitrate='9M')
    assert export.check_output(str(f2), ntsc, 10, False)[0] == []              # compared as rationals, not floats


def test_a_file_under_the_floor_is_not_a_problem(tmp_path):
    f = _clip(tmp_path / 'thin.mp4', n=24, bitrate='2M')
    out = {'w': 1080, 'h': 1920, 'fps': 24, 'fpsStr': '24', 'bitrate': 30_000_000}
    problems, numbers = export.check_output(str(f), out, 24, False)
    assert problems == [] and numbers['videoBitrate'] < 0.98 * 30e6


def test_check_output_checks_the_loudness_only_when_the_voice_is_in(tmp_path):
    f = _clip(tmp_path / 'tone.mp4', n=48, audio=2)                            # a 440 Hz tone, nowhere near -14 LUFS
    out = {'w': 1080, 'h': 1920, 'fps': 24, 'fpsStr': '24', 'bitrate': 1}
    assert export.check_output(str(f), out, 48, False)[0] == []
    assert any('loudness' in p for p in export.check_output(str(f), out, 48, True)[0])


def test_check_output_numbers_carry_what_details_needs(tmp_path):
    """details is built from these numbers, so the file is decoded once, not twice."""
    f = _clip(tmp_path / 'ok.mp4', n=24)
    out = {'w': 1080, 'h': 1920, 'fps': 24, 'fpsStr': '24', 'bitrate': 5_000_000}
    numbers = export.check_output(str(f), out, 24, False)[1]
    assert numbers['fps'] == 24.0 and numbers['codec'] == 'h264' and abs(numbers['duration'] - 1.0) < 0.01


def test_check_output_wants_an_aac_48k_audio_stream_when_sound_is_in(tmp_path):
    out = {'w': 1080, 'h': 1920, 'fps': 24, 'fpsStr': '24', 'bitrate': 1}
    good = _clip(tmp_path / 'good.mp4', n=48, audio=2)
    assert export.check_output(str(good), out, 48, False, expect_audio=True)[0] == []
    silent = _clip(tmp_path / 'silent.mp4', n=48)
    problems = export.check_output(str(silent), out, 48, False, expect_audio=True)[0]
    assert any('no audio stream' in p for p in problems), problems
    assert export.check_output(str(silent), out, 48, False)[0] == []           # a silent take stays valid
    slow = _clip(tmp_path / 'slow.mp4', n=48, audio=2, audio_args=('-ar', '44100'))
    problems = export.check_output(str(slow), out, 48, False, expect_audio=True)[0]
    assert any('aac at 44100 Hz' in p and '48000' in p for p in problems), problems


def test_render_timeout_grows_with_the_take(tmp_path, monkeypatch):
    """10 s at 60 fps in 4K = 600 frames x 2.7 s = 1620 s: more than the old fixed 25 minutes."""
    monkeypatch.setenv('FLOORED_HOME', str(tmp_path / 'h'))
    assert export.render_timeout(600, 2) >= 1620 * export.TIMEOUT_MARGIN
    assert export.render_timeout(121, 1) == export.RENDER_TIMEOUT                # a short take keeps the floor
    export.record_render_speed(2, 9.0)                                           # a slow PC: stored 5.85 s/frame
    assert export.render_timeout(600, 2) >= 600 * 5.85 * export.TIMEOUT_MARGIN
    (tmp_path / 'h' / 'machine.json').write_text('{"renderSecPerFrame": 0.1}')     # junk or a faster PC never lowers it
    assert export.render_timeout(600, 2) >= 1620 * export.TIMEOUT_MARGIN


def test_record_render_speed_averages_and_survives_a_read_only_home(tmp_path, monkeypatch):
    monkeypatch.setenv('FLOORED_HOME', str(tmp_path / 'h'))
    assert export.record_render_speed(1, 2.3) == 1.8                           # 0.5 * 1.3 (the guess) + 0.5 * 2.3
    assert export.record_render_speed(1, 1.0) == 1.4
    assert export.record_render_speed(2, 4.7) == 3.7
    machine = json.loads((tmp_path / 'h' / 'machine.json').read_text(encoding='utf-8'))
    assert machine['renderSecPerFrame'] == {'1': 1.4, '2': 3.7}
    (tmp_path / 'h' / 'machine.json').write_text(json.dumps({'secPerFrame': {'cpu-1': 3.1}, 'renderSecPerFrame': 'junk'}))
    assert export.record_render_speed(1, 1.0) == 1.15                          # garbage ignored, the other keys kept
    assert json.loads((tmp_path / 'h' / 'machine.json').read_text())['secPerFrame'] == {'cpu-1': 3.1}
    blocker = tmp_path / 'file'
    blocker.write_text('x')
    monkeypatch.setenv('FLOORED_HOME', str(blocker / 'sub'))                # cannot be created: OSError inside
    assert export.record_render_speed(1, 1.0) is None


def test_renderer_missing(tmp_path, server_factory):
    srv = server_factory(tmp_path, extra_env={'FLOORED_RENDERER_DIR': str(tmp_path / 'no-renderer')})
    r = srv.post_json('/api/export', {'takeId': 'sample', 'settings': settings(), 'events': []})
    assert r.status == 503
    assert r.json()['error'] == "The video maker isn't installed yet. Ask Claude to finish the setup."
    assert not any(paths.Workspace(tmp_path).exports.iterdir())                 # nothing was started


# ================================================================================================== slow: real renders
_sample = {}


def sample_export(server_factory, work):
    """The sample take exported once for the whole module: (status, export.log text)."""
    if 'status' not in _sample:
        project = work / 'sample-proj'
        srv = server_factory(project, extra_env=renderer_env())
        t0 = time.time()
        st = run_export(srv, 'sample')
        WALL['sample export'] = round(time.time() - t0, 1)
        _sample.update(status=st, log=export_log(project, st), project=project)
    return _sample['status'], _sample['log']


@pytest.mark.slow
def test_sample_original(server_factory, work):
    st, log = sample_export(server_factory, work)
    assert st['stage'] == 'done', (st, log[-1500:])
    f = st['path']
    got = export.probe_output(f)
    assert (got['width'], got['height']) == (1080, 1920)
    assert got['rate'] == Fraction(24) and got['frames'] == 121
    assert got['bitrate'] >= 8_000_000, got['bitrate']
    assert got['codec'] == 'h264'
    assert [(a['codec'], a['rate']) for a in got['audio']] == [('aac', 48000)]
    i, peak = lufs(f)
    assert abs(i - -14.0) <= 1.0, i
    assert peak <= -1.0 + 0.05, peak
    d = st['details']
    assert d['tier'] == 1 and d['notes'] == [], d
    print('sample export: %s' % json.dumps({k: d[k] for k in ('width', 'height', 'fps', 'videoBitrate', 'lufs', 'truePeak', 'timings')}))


@pytest.mark.slow
def test_a_take_with_a_high_bitrate_still_exports(server_factory, work):
    """A take recorded at about 30 Mbps: the floor is 30 Mbps and the encoder cannot reach it on a flat picture, but the
    export is never refused over its video bitrate."""
    project = work / 'hi-bitrate-proj'

    def mutate(take, d):
        take['bitrate'] = 30_000_000
        take['out'] = dict(take.get('out') or {}, bitrate=30_000_000)

    make_take(project, 'hi', mutate)
    srv = server_factory(project, extra_env=renderer_env())
    t0 = time.time()
    st = run_export(srv, 'hi')
    WALL['30 Mbps export'] = round(time.time() - t0, 1)
    log = export_log(project, st)
    assert 'floor 30.00 Mbps' in log, log[-1500:]                      # the take's bitrate really raised the floor
    assert 'floor re-encode: ran' in log, log[-1500:]
    assert st['stage'] == 'done', (st, log[-1500:])
    assert 'CHECK FAILED' not in log and 'wanted at least' not in log
    assert os.path.exists(st['path'])
    got = export.probe_output(st['path'])
    assert got['frames'] == 121 and got['rate'] == Fraction(24) and got['codec'] == 'h264'
    if got['bitrate'] < 30e6:                                           # under the floor: the number reaches the log, as a note
        assert 'note: video bitrate' in log and 'is under the 30.00 Mbps floor' in log


@pytest.fixture(scope='module')
def tier2_take(work):
    """A copy of the sample take whose cutout was upscaled to 2160x3840 (lanczos, VP9 alpha, CRF 18, as in Task 2)."""
    project = work / 'k4-proj'

    def mutate(take, d):
        big = d / 'person_4k.webm'
        _ff('-c:v', 'libvpx-vp9', '-i', SAMPLE / 'person.webm',
            '-vf', 'scale=2160:3840:flags=lanczos,format=yuva420p', '-c:v', 'libvpx-vp9', '-crf', '18',
            '-b:v', 0, '-auto-alt-ref', 0, '-deadline', 'good', '-cpu-used', 4, '-row-mt', 1, big)
        os.replace(big, d / 'person.webm')
        shutil.copyfile(SAMPLE / 'person.webm', d / 'person_proxy.webm')            # the studio's 1080 proxy: must stay unused
        take['tier'] = 2
        take['out'] = {'w': 2160, 'h': 3840, 'fps': 24, 'fpsStr': '24', 'bitrate': 20_000_000}
        take['files'] = {'person': 'person.webm', 'preview': 'person_proxy.webm', 'shadow': 'shadow.webm', 'audio': 'audio.m4a'}

    make_take(project, 'k4', mutate)
    return project


@pytest.mark.slow
def test_tier2(server_factory, work, tier2_take):
    ref, ref_log = sample_export(server_factory, work)
    assert ref['stage'] == 'done', ref_log[-1500:]
    srv = server_factory(tier2_take, extra_env=renderer_env())
    t0 = time.time()
    st = run_export(srv, 'k4')
    WALL['4k export'] = round(time.time() - t0, 1)
    log = export_log(tier2_take, st)
    assert st['stage'] == 'done', (st, log[-1500:])
    assert '--resolution portrait-4k' in log and '--crf 8' in log and '--video-bitrate' not in log
    assert 'floor re-encode:' in log and 'encode: crf 14 slow' in log
    got = export.probe_output(st['path'])
    assert (got['width'], got['height']) == (2160, 3840) and got['frames'] == 121 and got['rate'] == Fraction(24)
    assert got['bitrate'] >= 0.98 * 20e6, got['bitrate']
    i, _ = lufs(st['path'])
    assert abs(i - -14.0) <= 1.0, i
    scores, full = [], []
    for t in INSTANTS:
        a = frame_at(ref['path'], t, work / ('t1-%.1f.png' % t))
        b = imgcmp.downscale(frame_at(st['path'], t, work / ('t2-%.1f.png' % t)), work / ('t2d-%.1f.png' % t), 1080, 1920)
        scores.append(round(imgcmp.ssim(gray(a), gray(b)), 4))             # luma, as in Task 2's gate (chroma is 4:2:0 at each size)
        full.append(round(imgcmp.ssim(a, b), 4))
    print('4k vs 1080 SSIM at %s: luma %s, all planes %s; 4k details %s' % (INSTANTS, scores, full, json.dumps(st['details']['timings'])))
    assert min(scores) >= 0.97, scores


@pytest.mark.slow
def test_offline(tmp_path, server_factory, monkeypatch):
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:9')
    monkeypatch.setenv('HTTPS_PROXY', 'http://127.0.0.1:9')
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:9')
    monkeypatch.setenv('https_proxy', 'http://127.0.0.1:9')
    monkeypatch.setenv('NO_PROXY', '127.0.0.1,localhost')
    srv = server_factory(tmp_path, extra_env=renderer_env())
    t0 = time.time()
    st = run_export(srv, 'sample', events=[])
    WALL['offline export'] = round(time.time() - t0, 1)
    assert st['stage'] == 'done', (st, export_log(tmp_path, st)[-1500:])
    assert '--resolution' not in export_log(tmp_path, st)


@pytest.mark.slow
def test_spaces_and_accents(tmp_path, server_factory):
    project = tmp_path / 'Área de Trabalho' / 'meu reel'
    srv = server_factory(project, extra_env=dict(renderer_env(), FT_REVEAL_STUB='1'))
    t0 = time.time()
    st = run_export(srv, 'sample', events=[])
    WALL['accents export'] = round(time.time() - t0, 1)
    assert st['stage'] == 'done', (st, export_log(project, st)[-1500:])
    assert 'Área de Trabalho' in st['path'] and os.path.getsize(st['path']) > 100_000
    r = srv.post_json('/api/reveal', {'path': st['path']})
    assert r.status == 200, r.body
    assert export.probe_output(st['path'])['frames'] == 121


@pytest.mark.slow
def test_silent_take(tmp_path, server_factory):
    def mutate(take, d):
        take['hasAudio'] = False
        take['files']['audio'] = None

    make_take(tmp_path, 'quiet', mutate, drop=('audio.m4a',))
    srv = server_factory(tmp_path, extra_env=renderer_env())
    t0 = time.time()
    on = run_export(srv, 'quiet', settings({'voice': True, 'sfx': True}))
    WALL['silent take, sfx on'] = round(time.time() - t0, 1)
    assert on['stage'] == 'done', (on, export_log(tmp_path, on)[-1500:])
    got = export.probe_output(on['path'])
    assert [a['rate'] for a in got['audio']] == [48000]
    i, peak = lufs(on['path'])
    assert peak <= -1.0 + 0.05, peak
    t0 = time.time()
    off = run_export(srv, 'quiet', settings({'voice': True, 'sfx': False}))
    WALL['silent take, sfx off'] = round(time.time() - t0, 1)
    assert off['stage'] == 'done', (off, export_log(tmp_path, off)[-1500:])
    assert export.probe_output(off['path'])['audio'] == []
    assert off['details']['audio'] is None


# ================================================================================================== fast: a fake renderer
def fake_renderer(root, clip):
    """A renderer whose `render` copies `clip` to -o and records its arguments and the telemetry variables."""
    bindir = Path(root) / 'node_modules' / '.bin'
    bindir.mkdir(parents=True)
    script = Path(root) / 'fake.py'
    lines = ["import json, os, shutil, sys",
             "a = sys.argv[1:]",
             "o = a[a.index('-o') + 1]",
             "keys = ('HYPERFRAMES_NO_TELEMETRY', 'DO_NOT_TRACK', 'HYPERFRAMES_NO_UPDATE_CHECK')",
             "open(o + '.args.json', 'w').write(json.dumps({'args': a, 'env': {k: os.environ.get(k) for k in keys}}))",
             "shutil.copyfile(%r, o)" % str(clip)]
    script.write_text(chr(10).join(lines) + chr(10), encoding='utf-8')
    if os.name == 'nt':
        (bindir / 'hyperframes.cmd').write_text('@"%s" "%s" %%*' % (sys.executable, script) + chr(13) + chr(10))
    else:
        exe = bindir / 'hyperframes'
        exe.write_text('#!/bin/sh' + chr(10) + 'exec "%s" "%s" "$@"' % (sys.executable, script) + chr(10))
        exe.chmod(0o755)
    return Path(root)


def test_a_shortfall_ends_in_error_and_the_numbers_go_to_the_log(tmp_path, server_factory):
    """The renderer hands back a half-size file: the exporter must stop, say so in plain words, and log the numbers."""
    clip = _clip(tmp_path / 'half.mp4', size='540x960', n=121)
    root = fake_renderer(tmp_path / 'fake-renderer', clip)
    project = tmp_path / 'proj'
    srv = server_factory(project, extra_env={'FLOORED_RENDERER_DIR': str(root)})
    st = run_export(srv, 'sample', events=[], wait=120)
    assert st['stage'] == 'error', st
    assert st['error'] == ("The export didn't come out at your take's quality, so we stopped. Try again, and if it keeps "
                           "happening, ask Claude for help.")
    assert 'file' not in st or not st.get('file')
    log = export_log(project, st)
    assert 'CHECK FAILED' in log and 'size 540x960, wanted 1080x1920' in log and '"width": 540' in log
    kept = Path(project) / 'floored' / 'exports' / st['id'] / 'render.mp4'
    assert kept.exists() and 'kept the intermediate at %s' % kept in log          # one line for every failure that leaves it


def test_a_file_under_the_floor_ends_done_with_one_note_in_the_log(tmp_path, server_factory):
    """The take's floor is more than raw 1080x1920 video holds, so the finished file is under it on any machine: the export
    still ends done, and the log carries one note with both numbers, never a failure."""
    clip = _clip(tmp_path / 'any.mp4', n=121)
    root = fake_renderer(tmp_path / 'fake-renderer', clip)
    project = tmp_path / 'proj'

    def mutate(take, d):
        take['bitrate'] = 800_000_000
        take['out'] = dict(take.get('out') or {}, bitrate=800_000_000)

    make_take(project, 'heavy', mutate)
    srv = server_factory(project, extra_env={'FLOORED_RENDERER_DIR': str(root)})
    st = run_export(srv, 'heavy', events=[], wait=300)
    log = export_log(project, st)
    assert st['stage'] == 'done', (st, log[-1500:])
    assert 'floor re-encode: ran' in log and 'CHECK FAILED' not in log and 'wanted at least' not in log
    notes = [line for line in log.splitlines() if '  note: ' in line]
    assert len(notes) == 1 and 'is under the 800.00 Mbps floor' in notes[0] and 'the file is kept' in notes[0], log[-1500:]


def test_render_command_line_tier1_and_tier2(tmp_path, server_factory):
    clip = _clip(tmp_path / 'any.mp4', n=121)
    root = fake_renderer(tmp_path / 'fake-renderer', clip)
    project = tmp_path / 'proj'

    def mutate(take, d):
        take['tier'] = 2
        take['out'] = {'w': 2160, 'h': 3840, 'fps': 23.976, 'fpsStr': '24000/1001', 'bitrate': 30_000_000}
        take['files'] = {'person': 'big.webm', 'preview': 'person.webm', 'shadow': 'shadow.webm', 'audio': 'audio.m4a'}
        shutil.copyfile(SAMPLE / 'person.webm', d / 'big.webm')

    make_take(project, 'k4', mutate)
    srv = server_factory(project, extra_env={'FLOORED_RENDERER_DIR': str(root)})
    for tid, want in (('sample', ['--fps', '24', '--crf', '8']),
                      ('k4', ['--fps', '24000/1001', '--crf', '8', '--resolution', 'portrait-4k'])):
        st = run_export(srv, tid, events=[], wait=120)
        rec = json.loads(next((Path(project) / 'floored' / 'exports' / st['id']).glob('render.mp4.args.json')).read_text())
        args = rec['args']
        assert args[0] == 'render', args
        for flag, value in zip(want[::2], want[1::2]):
            assert args[args.index(flag) + 1] == value, (flag, args)
        assert ('--resolution' in args) == (tid == 'k4') and '--video-bitrate' not in args
        assert rec['env'] == {'HYPERFRAMES_NO_TELEMETRY': '1', 'DO_NOT_TRACK': '1', 'HYPERFRAMES_NO_UPDATE_CHECK': '1'}
        assert st['stage'] == ('error' if tid == 'k4' else 'done')       # the fake's 1080 clip is right for the sample, short of the 4K take
    comp = Path(project) / 'floored' / 'exports'
    k4 = sorted(comp.iterdir())[-1]
    assert (k4 / 'assets' / 'person.webm').stat().st_size == (SAMPLE / 'person.webm').stat().st_size    # files.person was copied
    assert (k4 / 'assets' / 'engine' / 'fonts' / 'inter.woff2').exists()


# ================================================================================================== dev/bench/export_table.py
def test_export_table_skips_work_files_and_reads_any_fps_text(tmp_path):
    import export_table as et
    folder = tmp_path / 'exports' / '20261109-101010-abcd'
    folder.mkdir(parents=True)
    (folder / 'job.json').write_text('{}')
    for n in ('video.mp4', 'render.mp4', 'Sample take - floored.mp4', 'stray.mp4'):
        (folder / n).write_bytes(b'x')
    loose = tmp_path / 'loose'
    loose.mkdir()
    for n in ('video.mp4', 'render.mp4', 'sketch.mp4'):
        (loose / n).write_bytes(b'x')
    assert [os.path.basename(f) for f in et.find_mp4s(folder)] == ['Sample take - floored.mp4']      # only the named final export
    assert [os.path.basename(f) for f in et.find_mp4s(loose)] == ['sketch.mp4']                         # a loose folder: all but work files
    take = tmp_path / 'take.json'
    take.write_text(json.dumps({'id': 't', 'w': 1080, 'h': 1920, 'fps': '23.976', 'frames': 10, 'bitrate': 1}))      # no out.fpsStr, fps a string
    assert et.expected_from_json(str(take))['rate'] == Fraction(24000, 1001)
    assert et.rate_of(24) == 24 and et.rate_of('30000/1001') == Fraction(30000, 1001) and et.rate_of('junk') == 0


# ================================================================================================== final review: fixes A
def _silent_aac(path, seconds=3, level_db=None, blip=False):
    """An AAC track: digital silence, a very quiet tone (level_db), or silence with a single click (blip)."""
    if blip:
        src = ['-f', 'lavfi', '-i', "aevalsrc='if(eq(n,24000),0.01,0)':s=48000:c=stereo:d=%s" % seconds]
    elif level_db is not None:
        src = ['-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=%s' % seconds, '-af', 'volume=%gdB' % level_db]
    else:
        src = ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo', '-t', seconds]
    _ff(*src, '-c:a', 'aac', path)
    return path


@pytest.fixture
def stale_path(tmp_path, monkeypatch):
    """The state right after `winget install ffmpeg`: the doctor recorded ffmpeg and ffprobe in config.json, but this
    process's PATH doesn't have them. Returns the recorded paths."""
    ff, fp = shutil.which('ffmpeg'), shutil.which('ffprobe')
    home = tmp_path / 'home'
    home.mkdir()
    (home / 'config.json').write_text(json.dumps({'tools': {'ffmpeg': ff, 'ffprobe': fp}}), encoding='utf-8')
    monkeypatch.setenv('FLOORED_HOME', str(home))
    return {'ffmpeg': ff, 'ffprobe': fp}


def test_the_ffmpeg_commands_use_the_recorded_paths(stale_path):
    assert export._x264_head('in.mp4')[0] == stale_path['ffmpeg']
    assert export.encode_cmd('in.mp4', 'out.mp4')[0] == stale_path['ffmpeg']
    first, second = export.abr_cmds('in.mp4', 'out.mp4', 8_000_000, 'p')
    assert first[0] == stale_path['ffmpeg'] and second[0] == stale_path['ffmpeg']


def test_every_export_helper_runs_ffmpeg_and_ffprobe_from_config_json_when_path_has_neither(tmp_path, stale_path, monkeypatch):
    clip = _clip(tmp_path / 'c.mp4', n=24, audio=1)
    voice = _silent_aac(tmp_path / 'v.m4a', level_db=-20)
    sfx_wav = tmp_path / 'sfx.wav'
    from ft import sfx
    sfx.write_wav(str(sfx_wav), sfx.synth(EVENTS, 1.0, export.SR), export.SR)
    monkeypatch.setenv('PATH', '')
    assert export.probe_output(str(clip))['frames'] == 24
    assert export.probe_video(str(clip))['frames'] == 24
    assert export.probe_bitrate(str(clip)) > 1_000_000
    assert export.volume_peak_db(str(clip)) is not None
    assert export.loudness(str(clip))[0] is not None
    exp = export.Exporter(None, tmp_path / 'exports')
    job = {'dir': str(tmp_path), 'id': 'x'}
    info = exp._mix(job, str(clip), str(voice), str(sfx_wav), str(tmp_path / 'final.mp4'), 1.0)
    assert info['voice'] is True and (tmp_path / 'final.mp4').exists()
    assert exp._mix(job, str(clip), None, None, str(tmp_path / 'silent.mp4'), 1.0) is None


@pytest.mark.parametrize('kind', ['digital silence', 'a whisper at -70 dB', 'a single click'])
def test_a_take_whose_sound_is_effectively_silent_exports_with_the_defaults(tmp_path, kind):
    """Digital silence is common (clips made without sound, some screen recorders): the voice counts as absent, the effects
    get their alone gain, and the result is not held to -14 LUFS."""
    clip = _clip(tmp_path / 'c.mp4', n=72)
    voice = _silent_aac(tmp_path / 'v.m4a', **{'digital silence': {}, 'a whisper at -70 dB': {'level_db': -70},
                                              'a single click': {'blip': True}}[kind])
    from ft import sfx
    sfx_wav = tmp_path / 'sfx.wav'
    sfx.write_wav(str(sfx_wav), sfx.synth(EVENTS, 3.0, export.SR), export.SR)
    exp = export.Exporter(None, tmp_path / 'exports')
    final = tmp_path / 'final.mp4'
    info = exp._mix({'dir': str(tmp_path), 'id': 'x'}, str(clip), str(voice), str(sfx_wav), str(final), 3.0)
    assert info['voice'] is False and info['sfx'] is True, info
    assert info['sfxGainDb'] == -3.0, info                                  # the effects-alone gain
    out = {'w': 1080, 'h': 1920, 'fps': 24, 'fpsStr': '24', 'bitrate': 5_000_000}
    problems, numbers = export.check_output(str(final), out, 72, bool(info['voice']), expect_audio=True)
    assert problems == [], problems
    assert numbers['lufs'] is None and [a['rate'] for a in numbers['audio']] == [48000]
    lufs_now, peak = export.loudness(str(final))
    assert lufs_now > -45, 'the effects must be audible'
    assert peak <= -1.0 + 0.05, peak


def test_a_silent_voice_without_effects_gives_a_silent_track_that_still_passes(tmp_path):
    clip = _clip(tmp_path / 'c.mp4', n=72)
    voice = _silent_aac(tmp_path / 'v.m4a')
    exp = export.Exporter(None, tmp_path / 'exports')
    info = exp._mix({'dir': str(tmp_path), 'id': 'x'}, str(clip), str(voice), None, str(tmp_path / 'final.mp4'), 3.0)
    assert info['voice'] is False
    out = {'w': 1080, 'h': 1920, 'fps': 24, 'fpsStr': '24', 'bitrate': 5_000_000}
    assert export.check_output(str(tmp_path / 'final.mp4'), out, 72, False, expect_audio=True)[0] == []


def test_a_real_voice_is_still_held_to_minus_14(tmp_path):
    clip = _clip(tmp_path / 'c.mp4', n=72)
    voice = _silent_aac(tmp_path / 'v.m4a', level_db=-20)
    exp = export.Exporter(None, tmp_path / 'exports')
    info = exp._mix({'dir': str(tmp_path), 'id': 'x'}, str(clip), str(voice), None, str(tmp_path / 'final.mp4'), 3.0)
    assert info['voice'] is True
    assert abs(export.loudness(str(tmp_path / 'final.mp4'))[0] - -14.0) <= 1.0


# -- M2: timeouts ---------------------------------------------------------------------------------------------------
def test_a_hung_helper_becomes_an_export_error_with_friendly_copy(tmp_path, monkeypatch):
    seen = []

    def hang(cmd, timeout=None, env=None):
        seen.append(timeout)
        raise subprocess.TimeoutExpired(cmd, timeout)
    monkeypatch.setattr(export, 'run', hang)
    for call in (lambda: export.probe_output('x.mp4'), lambda: export.probe_video('x.mp4'), lambda: export.probe_bitrate('x.mp4'),
                 lambda: export.volume_peak_db('x.mp4'), lambda: export.loudness('x.mp4')):
        with pytest.raises(export.ExportError) as e:
            call()
        assert str(e.value) == export.HELPER_TIMEOUT_COPY and 'timed out after' in e.value.detail
    exp = export.Exporter(None, tmp_path / 'exports')
    job = {'dir': str(tmp_path), 'id': 'x'}
    with pytest.raises(export.ExportError) as e:
        exp._mix(job, 'v.mp4', None, None, 'f.mp4', 1.0)
    assert str(e.value) == export.HELPER_TIMEOUT_COPY
    assert len(seen) == 6 and all(isinstance(t, (int, float)) and t >= 600 for t in seen), seen


def test_the_worker_logs_the_numbers_of_a_timeout(tmp_path, monkeypatch):
    exp = export.Exporter(None, tmp_path / 'exports')
    job = {'dir': str(tmp_path), 'id': 'x', 'stage': 'writing', 'progress': 0, 'message': ''}

    def boom(j):
        raise export.ExportError(export.HELPER_TIMEOUT_COPY, 500, detail='ffprobe timed out after 600 s: ffprobe -v error x.mp4')
    monkeypatch.setattr(exp, '_run', boom)
    exp.jobs['x'] = job
    exp.q.put('x')
    deadline = time.time() + 10
    while job['stage'] != 'error' and time.time() < deadline:
        time.sleep(0.05)
    log = (tmp_path / 'export.log').read_text(encoding='utf-8')
    assert job['stage'] == 'error' and job['error'] == export.HELPER_TIMEOUT_COPY
    assert 'ffprobe timed out after 600 s' in log


# -- M13: POSIX process group ---------------------------------------------------------------------------------------
def test_on_posix_the_render_gets_its_own_session_and_a_timeout_kills_the_group(tmp_path, monkeypatch):
    monkeypatch.setattr(export, 'IS_NT', False)
    seen = {}

    class FakeProc:
        pid = 4321
        stdout = iter([])

        def __init__(self, cmd, **kw):
            seen['kw'] = kw

        def wait(self):
            return 0

        def poll(self):
            return None

        def kill(self):
            seen['plain_kill'] = True
    monkeypatch.setattr(export.subprocess, 'Popen', FakeProc)
    exp = export.Exporter(None, tmp_path / 'exports')
    exp._stream({'dir': str(tmp_path)}, ['x'], lambda line: None, 5)
    assert seen['kw'].get('start_new_session') is True
    killed = []
    monkeypatch.setattr(export.os, 'getpgid', lambda pid: pid + 1, raising=False)
    monkeypatch.setattr(export.os, 'killpg', lambda pg, sig: killed.append((pg, sig)), raising=False)
    exp.proc = FakeProc('x')
    exp._kill_tree()
    assert killed and killed[0][0] == 4322 and 'plain_kill' not in seen


def test_on_windows_the_render_keeps_the_tree_kill(tmp_path, monkeypatch):
    monkeypatch.setattr(export, 'IS_NT', True)
    seen = {}

    class FakeProc:
        pid = 77
        stdout = iter([])

        def __init__(self, cmd, **kw):
            seen['kw'] = kw

        def wait(self):
            return 0

        def poll(self):
            return None
    monkeypatch.setattr(export.subprocess, 'Popen', FakeProc)
    calls = []
    monkeypatch.setattr(export.subprocess, 'run', lambda cmd, **kw: calls.append(cmd))
    exp = export.Exporter(None, tmp_path / 'exports')
    exp._stream({'dir': str(tmp_path)}, ['x'], lambda line: None, 5)
    assert 'start_new_session' not in seen['kw']
    exp.proc = FakeProc('x')
    exp._kill_tree()
    assert calls == [['taskkill', '/F', '/T', '/PID', '77']]


# -- M14: the bitrate after an encode pass comes from the packets, not a full decode ----------------------------------
def test_encode_probes_the_bitrate_from_packets_not_with_a_full_decode(tmp_path, monkeypatch):
    spy = _Spy(tmp_path, monkeypatch, [6_360_000, 8_390_000])
    monkeypatch.setattr(export, 'probe_output', lambda path: pytest.fail('a full decode inside _encode'))
    info = spy.encode()
    assert info['bitrate'] == 8_390_000


def test_probe_bitrate_agrees_with_the_full_probe_and_does_not_decode(tmp_path, monkeypatch):
    clip = _clip(tmp_path / 'c.mp4', n=48, bitrate='9M')
    assert abs(export.probe_bitrate(str(clip)) - export.probe_output(str(clip))['bitrate']) < 5000
    cmds = []
    real = export.run
    monkeypatch.setattr(export, 'run', lambda cmd, **kw: (cmds.append(cmd), real(cmd, **kw))[1])
    export.probe_bitrate(str(clip))
    assert cmds and '-count_frames' not in cmds[0]


# -- D24: the work files go once the check has passed -----------------------------------------------------------------
def test_a_passed_export_keeps_only_what_is_needed(tmp_path, server_factory):
    clip = _clip(tmp_path / 'any.mp4', n=121)
    root = fake_renderer(tmp_path / 'fake-renderer', clip)
    project = tmp_path / 'proj'
    srv = server_factory(project, extra_env={'FLOORED_RENDERER_DIR': str(root)})
    st = run_export(srv, 'sample', events=EVENTS, wait=180)
    assert st['stage'] == 'done', (st, export_log(project, st)[-1500:])
    folder = Path(project) / 'floored' / 'exports' / st['id']
    names = sorted(os.listdir(folder))
    assert 'video.mp4' not in names and 'premix.wav' not in names and 'sfx.wav' not in names
    assert 'assets' not in names and 'render.mp4' not in names and not [n for n in names if n.startswith('x264pass')]
    for keep in ('index.html', 'job.json', 'status.json', 'export.log', os.path.basename(st['path'])):
        assert keep in names, names
    assert os.path.isfile(st['path'])
    again = srv.get_json('/api/exports/' + st['id'])                    # the studio's list and the reveal route still work
    assert again['stage'] == 'done' and again['path'] == st['path']
    r = srv.post_json('/api/reveal', {'path': st['path']})
    assert r.status == 200, r.body


def test_a_failed_export_keeps_its_work_files_for_the_log(tmp_path, server_factory):
    clip = _clip(tmp_path / 'half.mp4', size='540x960', n=121)
    root = fake_renderer(tmp_path / 'fake-renderer', clip)
    project = tmp_path / 'proj'
    srv = server_factory(project, extra_env={'FLOORED_RENDERER_DIR': str(root)})
    st = run_export(srv, 'sample', events=EVENTS, wait=120)
    assert st['stage'] == 'error'
    folder = Path(project) / 'floored' / 'exports' / st['id']
    assert (folder / 'assets').is_dir() and (folder / 'video.mp4').exists()
