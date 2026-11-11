"""The doctor: dependency check and guided install (Task 19). Nothing here downloads from the internet: the weights come
from a local http.server (a bad file, or a copy of the lead's own file) and installs are only run in the slow test."""
import argparse
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from ft import doctor, paths

APP = Path(__file__).resolve().parents[2] / 'plugin' / 'skills' / 'floored' / 'app'
LOCAL_RVM = Path.home() / '.cache' / 'rvm' / 'rvm_mobilenetv3_fp32.onnx'      # read only: copied into a temp folder
needs_local_rvm = pytest.mark.skipif(not LOCAL_RVM.is_file(), reason="the RVM weights are not at ~/.cache/rvm")
slow = pytest.mark.slow
WINGET_FLAGS = '--source winget --accept-source-agreements --accept-package-agreements --disable-interactivity'
JARGON = re.compile(r'rvm|onnx|directml|coreml|mib|k0|matte|\bvenv\b|zscale|libvpx|vp9|x264', re.I)


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    """Nothing reads or writes the real ~/.floored, ~/.cache/rvm or renderer folder."""
    monkeypatch.setenv('FLOORED_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('FLOORED_RVM_MODEL', str(tmp_path / 'models' / 'rvm.onnx'))
    monkeypatch.setenv('FLOORED_RENDERER_DIR', str(tmp_path / 'renderer'))
    monkeypatch.delenv('FLOORED_RVM_URL', raising=False)
    no_pins = tmp_path / 'no-pins.txt'
    no_pins.write_text('# no pinned downloads here: the manual answers are tested in this file (test_doctor_tools.py has the pins)\n')
    monkeypatch.setenv('FLOORED_TOOLS_FILE', str(no_pins))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def file_server(tmp_path):
    """(folder, base url): files put in the folder are served on 127.0.0.1 at a free port."""
    root = tmp_path / 'www'
    root.mkdir()
    handler = lambda *a, **k: Quiet(*a, directory=str(root), **k)           # noqa: E731
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield root, 'http://127.0.0.1:%d/' % srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def platform(monkeypatch, name, tools=('winget', 'brew')):
    """Pretend to be on `name`, with only the package managers in `tools` installed."""
    monkeypatch.setattr(sys, 'platform', name)
    monkeypatch.setattr(doctor, 'which', lambda prog, path=None: ('/x/' + prog) if prog in tools else None)


# -- manual items: the command for this computer ------------------------------------------------------------------------
def test_missing_ffmpeg_gives_os_command(monkeypatch):
    monkeypatch.setattr(doctor, 'find_program', lambda name: None)
    platform(monkeypatch, 'win32')
    item = doctor.check_ffmpeg()
    assert item['ok'] is False and item['how'] == 'manual' and item['id'] == 'ffmpeg'
    assert item['command'] == 'winget install --id Gyan.FFmpeg -e ' + WINGET_FLAGS
    platform(monkeypatch, 'darwin')
    assert doctor.check_ffmpeg()['command'] == 'brew install ffmpeg-full'
    platform(monkeypatch, 'win32', tools=())                         # no winget: the official page
    assert doctor.check_ffmpeg()['command'].startswith('https://')
    platform(monkeypatch, 'darwin', tools=())
    assert doctor.check_ffmpeg()['command'].startswith('https://')


@pytest.mark.parametrize('item_id,win,mac', [
    ('python', 'winget install --id Python.Python.3.12 -e ' + WINGET_FLAGS, 'brew install python@3.12'),
    ('node', 'winget install --id OpenJS.NodeJS.LTS -e ' + WINGET_FLAGS, 'brew install node'),
    ('browser', 'winget install --id Google.Chrome -e ' + WINGET_FLAGS, 'brew install --cask google-chrome'),
    ('ffmpeg', 'winget install --id Gyan.FFmpeg -e ' + WINGET_FLAGS, 'brew install ffmpeg-full'),
])
def test_install_commands(monkeypatch, item_id, win, mac):
    platform(monkeypatch, 'win32')
    assert doctor.install_command(item_id) == win
    platform(monkeypatch, 'darwin')
    assert doctor.install_command(item_id) == mac


def test_old_python_not_ok(monkeypatch):
    monkeypatch.setattr(doctor, '_pythons', lambda: iter([('/usr/bin/python3', (3, 8, 10))]))
    platform(monkeypatch, 'win32')
    item = doctor.check_python()
    assert item['ok'] is False and item['found'] == 'Python 3.8.10' and item['need'] == 'Python 3.10 or newer'
    assert item['command'] == 'winget install --id Python.Python.3.12 -e ' + WINGET_FLAGS and '3.8.10' in item['note']
    monkeypatch.setattr(doctor, '_pythons', lambda: iter([('/usr/bin/python3', (3, 8, 10)), ('/opt/py312', (3, 12, 1))]))
    assert doctor.check_python()['ok'] is True                      # a newer one further along is found


FILTERS = ' ... scale            V->V       Scale the input video size.\n T.C zscale           V->V       Apply resizing, colorspace and bit depth conversions.\n'
ENCODERS = ' V....D libx264              libx264 H.264 (codec h264)\n V....D libvpx-vp9           libvpx VP9 (codec vp9)\n'


def fake_ffmpeg(monkeypatch, filters=FILTERS, encoders=ENCODERS):
    monkeypatch.setattr(doctor, 'find_program', lambda name: {'path': '/x/' + name, 'via': 'path', 'stale': None})

    def capture(cmd, timeout=60, env=None):
        if '-version' in cmd:
            return 0, 'ffmpeg version 8.1-full_build-www.gyan.dev Copyright (c) 2000-2026'
        return 0, filters if '-filters' in cmd else encoders
    monkeypatch.setattr(doctor, '_capture', capture)


def test_ffmpeg_without_zscale_flagged(monkeypatch):
    platform(monkeypatch, 'darwin')
    fake_ffmpeg(monkeypatch, filters=' ... scale            V->V       Scale the input video size.\n')
    item = doctor.check_ffmpeg()
    assert item['ok'] is False and "can't convert HDR video" in item['note'] and item['command'] == 'brew install ffmpeg-full'
    assert not JARGON.search(item['note']), item
    assert item['found'] == 'ffmpeg 8.1-full_build-www.gyan.dev'


def test_mac_slim_ffmpeg_on_path_uses_the_full_build(tmp_path, monkeypatch):
    """Homebrew's plain ffmpeg (no zscale) is on PATH; the keg-only ffmpeg-full is found, recorded and used."""
    platform(monkeypatch, 'darwin')
    keg = tmp_path / 'ffmpeg-full' / 'bin'
    keg.mkdir(parents=True)
    for name in ('ffmpeg', 'ffprobe'):
        (keg / name).write_text('')
    monkeypatch.setattr(doctor, 'FULL_FFMPEG_DIRS', [str(tmp_path / 'none'), str(keg)])
    monkeypatch.setattr(doctor, 'find_program', lambda name: {'path': '/usr/bin/' + name, 'via': 'path', 'stale': None})
    full = str(keg / 'ffmpeg')

    def capture(cmd, timeout=60, env=None):
        if '-version' in cmd:
            return 0, 'ffmpeg version %s Copyright (c) 2000-2026' % ('9.0.2-full' if cmd[0] == full else '9.0.2')
        if '-filters' in cmd:
            return 0, FILTERS if cmd[0] == full else ' ... scale            V->V       Scale the input video size.\n'
        return 0, ENCODERS
    monkeypatch.setattr(doctor, '_capture', capture)
    item = doctor.check_ffmpeg()
    assert item['ok'] is True and item['found'] == 'ffmpeg 9.0.2-full', item
    tools = doctor.recorded_tools()
    assert tools['ffmpeg'] == full and tools['ffprobe'] == str(keg / 'ffprobe')
    monkeypatch.setattr(doctor, 'FULL_FFMPEG_DIRS', [str(tmp_path / 'none')])     # no full build: still flagged
    item = doctor.check_ffmpeg()
    assert item['ok'] is False and item['command'] == 'brew install ffmpeg-full'


def test_ffmpeg_without_vp9_or_x264_flagged(monkeypatch):
    platform(monkeypatch, 'win32')
    fake_ffmpeg(monkeypatch, encoders=' V....D libx264 libx264 H.264\n')
    item = doctor.check_ffmpeg()
    assert item['ok'] is False and "can't write the cutout video" in item['note'] and 'final video' not in item['note']
    assert not JARGON.search(item['note']), item


def test_ffmpeg_complete_is_ok(monkeypatch):
    platform(monkeypatch, 'win32')
    fake_ffmpeg(monkeypatch)
    item = doctor.check_ffmpeg()
    assert item['ok'] is True and item['command'] == '' and item['note'] == ''


def test_node_too_old(monkeypatch):
    platform(monkeypatch, 'win32')
    monkeypatch.setattr(doctor, 'find_program', lambda name: {'path': '/x/' + name, 'via': 'path', 'stale': None})
    monkeypatch.setattr(doctor, '_capture', lambda cmd, timeout=60, env=None: (0, 'v20.11.0\n'))
    item = doctor.check_node()
    assert item['ok'] is False and item['found'] == 'Node.js 20.11.0' and 'winget install --id OpenJS.NodeJS.LTS -e ' + WINGET_FLAGS == item['command']
    monkeypatch.setattr(doctor, '_capture', lambda cmd, timeout=60, env=None: (0, 'v22.14.0\n'))
    assert doctor.check_node()['ok'] is True


# -- finding programs the PATH does not know yet --------------------------------------------------------------------------
def winget_ffmpeg(tmp_path, monkeypatch):
    local = tmp_path / 'local'
    bin_dir = local / 'Microsoft' / 'WinGet' / 'Packages' / 'Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe' / 'ffmpeg-8.1-full_build' / 'bin'
    bin_dir.mkdir(parents=True)
    exe = bin_dir / 'ffmpeg.exe'
    exe.write_bytes(b'')
    empty = tmp_path / 'emptybin'
    empty.mkdir()
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setenv('LOCALAPPDATA', str(local))
    monkeypatch.setenv('PATH', str(empty))
    monkeypatch.setattr(doctor, 'which', lambda name, path=None: None)   # the PATH is empty (and shutil.which's Windows branch needs Windows)
    for var in ('ProgramFiles', 'ProgramW6432'):
        monkeypatch.delenv(var, raising=False)
    return exe


def test_tool_in_winget_folder_recorded(monkeypatch, tmp_path):
    exe = winget_ffmpeg(tmp_path, monkeypatch)
    hit = doctor.find_program('ffmpeg')
    assert hit['via'] == 'search' and os.path.samefile(hit['path'], str(exe))
    cfg = json.loads((tmp_path / 'home' / 'config.json').read_text(encoding='utf-8'))
    assert os.path.samefile(cfg['tools']['ffmpeg'], str(exe))
    assert os.path.isabs(cfg['tools']['ffmpeg'])
    again = doctor.find_program('ffmpeg')                              # the recorded path is used from now on
    assert again['via'] == 'config'


def test_stale_recorded_path_is_replaced(monkeypatch, tmp_path):
    exe = winget_ffmpeg(tmp_path, monkeypatch)
    doctor.record_tool('ffmpeg', str(tmp_path / 'gone' / 'ffmpeg.exe'))
    hit = doctor.find_program('ffmpeg')
    assert hit['stale'] == str(tmp_path / 'gone' / 'ffmpeg.exe') and os.path.samefile(hit['path'], str(exe))
    assert os.path.samefile(doctor.recorded_tools()['ffmpeg'], str(exe))
    # and the report says so
    monkeypatch.setattr(doctor, '_capture', lambda cmd, timeout=60, env=None: (0, 'ffmpeg version 8.1' if '-version' in cmd else (FILTERS if '-filters' in cmd else ENCODERS)))
    monkeypatch.setattr(doctor, 'find_program', lambda name: {'path': '/x/' + name, 'via': 'search', 'stale': '/old/' + name})
    assert 'saved location' in doctor.check_ffmpeg()['note']


def test_stale_path_with_nothing_found_is_forgotten(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'platform', 'win32')
    empty = tmp_path / 'emptybin'
    empty.mkdir()
    monkeypatch.setenv('PATH', str(empty))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'nolocal'))
    monkeypatch.setattr(doctor, 'which', lambda name, path=None: None)
    for var in ('ProgramFiles', 'ProgramW6432'):
        monkeypatch.delenv(var, raising=False)
    doctor.record_tool('ffmpeg', str(tmp_path / 'gone.exe'))
    doctor.record_tool('node', str(tmp_path / 'gone2.exe'))
    assert doctor.find_program('ffmpeg') is None
    assert 'ffmpeg' not in doctor.recorded_tools() and 'node' in doctor.recorded_tools()


def test_proc_tool_reads_what_the_doctor_recorded(monkeypatch, tmp_path):
    from ft import proc
    exe = winget_ffmpeg(tmp_path, monkeypatch)
    doctor.find_program('ffmpeg')
    assert os.path.samefile(proc.tool('ffmpeg'), str(exe))


# -- the report ---------------------------------------------------------------------------------------------------------
def item(item_id, ok, mb, how='auto'):
    return {'id': item_id, 'ok': ok, 'found': None, 'need': '', 'mb': mb, 'how': how, 'command': '', 'note': ''}


def test_summary_sums_downloads():
    items = [item('python', True, 27, 'manual'), item('venv', False, 12), item('packages', False, 37), item('rvm-model', False, 15),
             item('renderer', False, 399), item('words', False, 208), item('gpu', False, 0)]
    total, summary = doctor.summarize(items)
    assert total == 463
    assert summary.startswith('Setup needs 4 downloads, about 463 MB in total: ')
    assert '\n' not in summary and 'the video maker (399 MB)' in summary and 'Optional' in summary and '208 MB' in summary.split('Optional')[1]
    total, summary = doctor.summarize([item('python', True, 27, 'manual'), item('words', False, 208)])
    assert total == 0 and summary.startswith('Everything floored needs is installed.')
    total, summary = doctor.summarize([item('renderer', False, 399)])
    assert summary.startswith('Setup needs 1 download, about 399 MB in total:')


def test_report_shape_order_and_plain_copy():
    report = doctor.build_report()
    assert list(report) == ['ok', 'items', 'downloadMb', 'summary']
    assert [i['id'] for i in report['items']] == ['python', 'ffmpeg', 'node', 'browser', 'venv', 'packages', 'rvm-model', 'renderer', 'words', 'gpu']
    for i in report['items']:
        assert list(i) == ['id', 'ok', 'found', 'need', 'mb', 'how', 'command', 'note'] + (['minutes'] if i['id'] in ('renderer', 'words') else [])
        assert i['how'] in ('auto', 'manual') and isinstance(i['mb'], int)
        assert not JARGON.search(i['note']), i
        assert not JARGON.search(i['need']), i
    assert not JARGON.search(report['summary']) and '\n' not in report['summary']
    by_id = {i['id']: i for i in report['items']}
    assert by_id['venv']['ok'] is False and by_id['packages']['ok'] is False and by_id['renderer']['ok'] is False   # empty temp home
    assert [i['how'] for i in report['items'] if i['how'] == 'manual'] == ['manual'] * 4
    assert report['ok'] is False and report['downloadMb'] >= 399
    assert report['ok'] == all(i['ok'] for i in report['items'] if i['id'] not in ('words', 'gpu'))


def test_plain_report_makes_no_network_connection(monkeypatch):
    """No network before consent: not even a HEAD for the model's size."""
    import socket

    def refuse(*a, **k):
        raise AssertionError('the plain report opened a connection')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)
    monkeypatch.setenv('FLOORED_RVM_URL', 'http://127.0.0.1:9/rvm.onnx')
    assert doctor.build_report()['items']
    assert doctor.main(args(json=True)) in (0, 1)              # what `doctor --json` runs
    assert not hasattr(doctor, 'head_size_mb')


def test_slow_steps_carry_their_minutes():
    """SKILL.md quotes these instead of guessing: the video maker is the long step (12 minutes measured), the speech reader about 1."""
    by_id = {i['id']: i for i in doctor.build_report()['items']}
    assert by_id['renderer']['minutes'] == 12 and by_id['words']['minutes'] == 1
    assert all('minutes' not in i for k, i in by_id.items() if k not in ('renderer', 'words'))


def test_renderer_install_says_it_is_slow_before_npm_and_waits_long_enough(monkeypatch):
    from ft import export
    events = []
    monkeypatch.setattr(doctor, '_export_or_none', lambda: export)
    monkeypatch.setattr(doctor, '_node_env', lambda: ('npm-exe', {}))
    monkeypatch.setattr(doctor, 'renderer_version', lambda: None)
    monkeypatch.setattr(doctor, '_stream', lambda cmd, label, env=None, timeout=None: events.append(('run', cmd[0], timeout)))
    with pytest.raises(doctor.DoctorError):                  # the fake npm installs nothing: the check after it fails
        doctor.install_renderer(lambda text: events.append(('log', text)))
    assert events[0][0] == 'log' and 'usually 10-15 minutes' in events[0][1] and 'prints little' in events[0][1]
    assert events[1] == ('run', 'npm-exe', 2700)


def test_report_survives_without_the_packages_module_state(monkeypatch):
    """The packages item looks inside floored's own environment, not at the Python that happens to run the doctor."""
    assert doctor.check_venv()['ok'] is False
    assert doctor.check_packages()['ok'] is False and doctor.check_packages()['found'] is None


def test_renderer_helpers_agree_with_export(monkeypatch, tmp_path):
    from ft import export
    assert doctor.HYPERFRAMES_VERSION == export.HYPERFRAMES_VERSION
    monkeypatch.setattr(doctor, '_export_or_none', lambda: None)         # the no-packages fallback
    assert doctor.renderer_dir() == export.renderer_dir()
    monkeypatch.delenv('FLOORED_RENDERER_DIR')
    assert doctor.renderer_dir() == export.renderer_dir()


# -- the cutout model ---------------------------------------------------------------------------------------------------
def test_rvm_hash_mismatch_deletes(tmp_path, file_server, monkeypatch):
    root, url = file_server
    (root / 'rvm.onnx').write_bytes(b'this is not the model' * 5000)
    monkeypatch.setenv('FLOORED_RVM_URL', url + 'rvm.onnx')
    target = paths.rvm_model_path()
    result = doctor.install('rvm-model')
    assert result['ok'] is False and "didn't download correctly" in result['message']
    assert not target.exists() and not target.with_name(target.name + '.part').exists()
    assert not JARGON.search(result['message'])


def test_rvm_never_overwrites_an_existing_file(tmp_path, file_server, monkeypatch):
    root, url = file_server
    (root / 'rvm.onnx').write_bytes(b'x' * 100)
    monkeypatch.setenv('FLOORED_RVM_URL', url + 'rvm.onnx')
    target = paths.rvm_model_path()
    target.parent.mkdir(parents=True)
    target.write_bytes(b'someone elses file')
    result = doctor.install('rvm-model')
    assert result['ok'] is False and 'won\'t overwrite' in result['message']
    assert target.read_bytes() == b'someone elses file' and not target.with_name(target.name + '.part').exists()
    item = doctor.check_rvm()
    assert item['ok'] is False and item['how'] == 'manual' and 'overwrite' in item['note']


def test_rvm_unreachable_server_is_a_plain_error(monkeypatch):
    monkeypatch.setenv('FLOORED_RVM_URL', 'http://127.0.0.1:9/none.onnx')
    result = doctor.install('rvm-model')
    assert result['ok'] is False and 'internet' in result['message']
    assert not paths.rvm_model_path().exists() and not paths.rvm_model_path().with_name('rvm.onnx.part').exists()


@needs_local_rvm
def test_rvm_good_download_is_kept(tmp_path, file_server, monkeypatch):
    root, url = file_server
    shutil.copyfile(str(LOCAL_RVM), str(root / 'rvm.onnx'))
    assert hashlib.sha256((root / 'rvm.onnx').read_bytes()).hexdigest() == doctor.RVM_SHA256
    monkeypatch.setenv('FLOORED_RVM_URL', url + 'rvm.onnx')
    target = paths.rvm_model_path()
    assert doctor.check_rvm()['ok'] is False
    result = doctor.install('rvm-model')
    assert result['ok'] is True, result
    assert target.is_file() and doctor.sha256_file(target) == doctor.RVM_SHA256
    assert not target.with_name(target.name + '.part').exists()
    assert doctor.check_rvm()['ok'] is True
    assert doctor.install('rvm-model')['ok'] is True                   # already there: nothing to do


# -- the command line ---------------------------------------------------------------------------------------------------
def test_serve_without_packages_exit_5(tmp_path):
    env = dict(os.environ, FLOORED_HOME=str(tmp_path / 'home'), PYTHONUTF8='1')
    r = subprocess.run([sys.executable, '-S', str(APP / 'floored.py'), 'serve', '--workspace', str(tmp_path)],
                       env=env, capture_output=True, text=True, timeout=60)           # -S: no site-packages, so no numpy
    assert r.returncode == 5, r.stdout + r.stderr
    assert "floored isn't set up yet. Ask Claude to run the setup." in r.stderr


def test_doctor_runs_without_the_packages(tmp_path):
    env = dict(os.environ, FLOORED_HOME=str(tmp_path / 'home'), PYTHONUTF8='1', FLOORED_RENDERER_DIR=str(tmp_path / 'r'),
               FLOORED_RVM_MODEL=str(tmp_path / 'm' / 'rvm.onnx'))
    r = subprocess.run([sys.executable, '-S', str(APP / 'floored.py'), 'doctor', '--json'], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 1, r.stdout + r.stderr                          # not set up: exit 1 and still a full report
    report = json.loads(r.stdout)
    assert [i['id'] for i in report['items']][:3] == ['python', 'ffmpeg', 'node'] and report['ok'] is False


def args(**kw):
    return argparse.Namespace(**dict({'json': False, 'install': None, 'gpu_check': False}, **kw))


def test_cli_install_of_a_manual_item_prints_the_command(capsys, monkeypatch):
    platform(monkeypatch, 'win32')
    assert doctor.main(args(install='ffmpeg')) == 2
    out = json.loads(capsys.readouterr().out)
    assert out['ok'] is False and 'winget install --id Gyan.FFmpeg -e ' + WINGET_FLAGS in out['message'] and 'code' not in out
    assert doctor.main(args(install='bogus')) == 2
    assert json.loads(capsys.readouterr().out)['ok'] is False


def test_cli_json_report(capsys, monkeypatch):
    from ft import cli
    fake = {'ok': True, 'items': [], 'downloadMb': 0, 'summary': 'Everything floored needs is installed.'}
    monkeypatch.setattr(doctor, 'build_report', lambda: fake)
    assert cli.main(['doctor', '--json']) == 0
    assert json.loads(capsys.readouterr().out) == fake
    fake = dict(fake, ok=False)
    assert cli.main(['doctor']) == 1
    assert 'Everything floored needs' in capsys.readouterr().out


def test_cli_parses_install_and_gpu_flags(monkeypatch, capsys):
    from ft import cli
    seen = []
    monkeypatch.setattr(doctor, 'main', lambda a: seen.append((a.install, a.gpu_check, a.json)) or 0)
    assert cli.main(['doctor', '--install', 'renderer']) == 0
    assert cli.main(['doctor', '--gpu-check']) == 0
    assert seen == [('renderer', False, False), (None, True, False)]


def test_run_in_venv_hands_over_and_can_be_switched_off(monkeypatch, tmp_path):
    script = tmp_path / 'echo7.py'
    script.write_text('import sys; sys.exit(7 if sys.argv[1:] == ["a", "b"] else 1)\n')
    monkeypatch.delenv('FLOORED_NO_VENV', raising=False)             # the dev shell may set it; this test sets it itself
    assert doctor.run_in_venv(['a', 'b'], str(script)) is None            # no venv in the temp home: stay here
    monkeypatch.setattr(doctor, 'venv_python', lambda: Path(sys.executable))
    assert doctor.run_in_venv(['a', 'b'], str(script)) == 7
    monkeypatch.setenv('FLOORED_NO_VENV', '1')
    assert doctor.run_in_venv(['a', 'b'], str(script)) is None
    monkeypatch.delenv('FLOORED_NO_VENV')
    monkeypatch.setattr(doctor, 'venv_dir', lambda: Path(sys.prefix))     # already inside it
    assert doctor.run_in_venv(['a', 'b'], str(script)) is None


# -- the graphics-card check --------------------------------------------------------------------------------------------
@pytest.mark.parametrize('plat,provider', [('win32', 'dml'), ('darwin', 'coreml')])
def test_gpu_check_records_the_provider(monkeypatch, plat, provider):
    from ft import matte
    monkeypatch.setattr(sys, 'platform', plat)
    paths.rvm_model_path().parent.mkdir(parents=True)
    paths.rvm_model_path().write_bytes(b'x')
    calls = []

    def parity(src, prov, frames=12, model=None):
        calls.append((Path(src).name, prov, frames))
        return {'ok': True, 'worst': 0.0}
    monkeypatch.setattr(matte, 'parity', parity)
    result = doctor.install('gpu')
    assert result['ok'] is True and calls == [('source.mp4', provider, 12)]
    assert json.loads((paths.user_dir() / 'machine.json').read_text(encoding='utf-8'))['matteProvider'] == provider
    assert matte._recorded_provider() == provider
    assert doctor.check_gpu()['ok'] is True


def test_gpu_check_failed_parity_stays_on_cpu(monkeypatch):
    from ft import matte
    monkeypatch.setattr(sys, 'platform', 'win32')
    paths.rvm_model_path().parent.mkdir(parents=True)
    paths.rvm_model_path().write_bytes(b'x')
    (paths.user_dir()).mkdir(parents=True)
    (paths.user_dir() / 'machine.json').write_text(json.dumps({'other': 1, 'matteProvider': 'dml'}), encoding='utf-8')
    monkeypatch.setattr(matte, 'parity', lambda *a, **k: {'ok': False, 'worst': 0.02})
    result = doctor.install('gpu')
    assert result['ok'] is True and 'processor' in result['message'] and not JARGON.search(result['message'])
    machine = json.loads((paths.user_dir() / 'machine.json').read_text(encoding='utf-8'))
    assert machine['matteProvider'] == 'cpu' and machine['other'] == 1
    item = doctor.check_gpu()
    assert item['ok'] is False and 'processor' in item['note']


def test_gpu_check_needs_the_model_first(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    result = doctor.install('gpu')
    assert result['ok'] is False and 'model' in result['message']
    assert not (paths.user_dir() / 'machine.json').exists()


# -- a fresh computer ---------------------------------------------------------------------------------------------------
@slow
@needs_local_rvm
def test_fresh_home_install(tmp_path, file_server):
    """FLOORED_HOME=tmp: venv, packages, model, renderer -> the doctor is ok except the optional items. Real pip and npm
    installs (their normal caches), the weights served from a local copy, HyperFrames' Chrome from its default cache."""
    root, url = file_server
    shutil.copyfile(str(LOCAL_RVM), str(root / 'rvm.onnx'))
    home = tmp_path / 'fresh'
    env = dict(os.environ, FLOORED_HOME=str(home), FLOORED_RVM_MODEL=str(tmp_path / 'models' / 'rvm.onnx'),
               FLOORED_RVM_URL=url + 'rvm.onnx', PYTHONUTF8='1')
    env.pop('FLOORED_RENDERER_DIR', None)
    env.pop('FLOORED_NO_VENV', None)

    def doctor_cmd(*extra, timeout=1800):
        t0 = time.time()
        r = subprocess.run([sys.executable, str(APP / 'floored.py'), 'doctor', *extra], env=env, capture_output=True, text=True,
                           timeout=timeout, creationflags=0x08000000 if os.name == 'nt' else 0)
        print('doctor %s: %.0f s, exit %s' % (' '.join(extra), time.time() - t0, r.returncode))
        return r

    before = json.loads(doctor_cmd('--json', timeout=300).stdout)
    assert before['ok'] is False and before['downloadMb'] > 400
    print(before['summary'])
    for step in ('venv', 'packages', 'rvm-model', 'renderer'):
        r = doctor_cmd('--install', step)
        assert r.returncode == 0, '%s: %s\n%s' % (step, r.stdout, r.stderr[-3000:])
        assert json.loads(r.stdout.strip().splitlines()[-1])['ok'] is True
    after = doctor_cmd('--json', timeout=300)
    report = json.loads(after.stdout)
    bad = [i['id'] for i in report['items'] if not i['ok'] and i['id'] not in ('words', 'gpu')]
    assert after.returncode == 0 and report['ok'] is True and bad == [], (bad, report)
    sizes = {name: sum(f.stat().st_size for f in (home / name).rglob('*') if f.is_file()) // 1_000_000 for name in ('venv', 'renderer')}
    print('on disk (MB):', sizes)
    gpu = doctor_cmd('--gpu-check', timeout=1200)
    print('gpu-check:', gpu.stdout.strip(), gpu.stderr.strip()[-300:])
    assert gpu.returncode == 0
    machine = json.loads((home / 'machine.json').read_text(encoding='utf-8'))
    assert machine['matteProvider'] in ('dml', 'coreml', 'cpu')
    print('machine.json:', machine)


def test_a_blocked_cutout_model_item_is_not_a_download():
    target = paths.rvm_model_path()
    target.parent.mkdir(parents=True)
    target.write_bytes(b'someone else made this file')                                  # a different file is already at the target
    blocked = doctor.check_rvm()
    assert blocked['how'] == 'manual' and blocked['ok'] is False and blocked['mb'] == 0
    total, summary = doctor.summarize([item('venv', False, 12), blocked])
    assert total == 12 and summary.startswith('Setup needs 1 download, about 12 MB in total:') and 'cutout model' not in summary
    total, summary = doctor.summarize([blocked])
    assert total == 0 and summary.startswith('Setup needs nothing to download')


def test_a_missing_manual_program_still_counts_as_a_download(monkeypatch):
    platform(monkeypatch, 'win32')
    monkeypatch.setattr(doctor, 'find_program', lambda name: None)
    missing = doctor.check_ffmpeg()
    assert missing['ok'] is False and missing['how'] == 'manual' and missing['mb'] == doctor.SIZES_MB['ffmpeg'] > 0
    total, summary = doctor.summarize([item('python', True, 27, 'manual'), missing])
    assert total == doctor.SIZES_MB['ffmpeg']
    assert summary.startswith('Setup needs 1 download, about %d MB in total:' % total) and 'ffmpeg' in summary.lower()


# -- fix round 1 -------------------------------------------------------------------------------------------------------
def test_requirements_files_resolve_inside_the_plugin():
    plugin = paths.SKILL_DIR.parents[1]
    for name in ('requirements.txt', 'requirements-words.txt'):
        found = doctor.requirements_file(name).resolve()
        assert plugin in found.parents and found.is_file(), found


def test_requirements_file_missing_is_a_plain_error(monkeypatch, tmp_path):
    monkeypatch.setattr(paths, 'APP_DIR', tmp_path)                                    # a shallow path: no IndexError
    with pytest.raises(doctor.DoctorError):
        doctor.requirements_file('requirements.txt')


def test_python_folders_sort_by_version_number(monkeypatch, tmp_path):
    local = tmp_path / 'local'
    for name in ('Python39', 'Python313', 'Python310', 'Python312'):
        (local / 'Programs' / 'Python' / name).mkdir(parents=True)
    monkeypatch.setattr(doctor, '_win', lambda: True)
    monkeypatch.setenv('LOCALAPPDATA', str(local))
    monkeypatch.setenv('ProgramFiles', str(tmp_path / 'pf'))
    monkeypatch.setenv('ProgramW6432', str(tmp_path / 'pf'))
    names = [os.path.basename(d) for d in doctor.search_dirs() if os.path.basename(d).startswith('Python3')]
    assert names == ['Python313', 'Python312', 'Python310', 'Python39']


def _recorded_tools(tmp_path, names):
    config = {}
    for name in names:
        folder = tmp_path / (name + 'bin')
        folder.mkdir(exist_ok=True)
        exe = folder / name
        exe.write_bytes(b'x')
        config[name] = str(exe)
    paths.user_dir().mkdir(parents=True, exist_ok=True)
    (paths.user_dir() / 'config.json').write_text(json.dumps({'tools': config}), encoding='utf-8')
    return {name: os.path.dirname(path) for name, path in config.items()}


def test_renderer_env_puts_the_recorded_tool_folders_first(monkeypatch, tmp_path):
    from ft import export
    folders = _recorded_tools(tmp_path, ['node', 'ffmpeg'])
    monkeypatch.setenv('PATH', str(tmp_path / 'other'))
    parts = export.renderer_env()['PATH'].split(os.pathsep)
    assert parts == [folders['node'], folders['ffmpeg'], str(tmp_path / 'other')]


def test_renderer_env_skips_a_tool_that_is_missing(monkeypatch, tmp_path):
    from ft import export
    monkeypatch.setenv('PATH', str(tmp_path / 'empty'))
    assert export.renderer_env()['PATH'] == str(tmp_path / 'empty')                  # nothing recorded, nothing on PATH: untouched
    folders = _recorded_tools(tmp_path, ['node'])
    assert export.renderer_env()['PATH'].split(os.pathsep) == [folders['node'], str(tmp_path / 'empty')]


def test_install_renderer_wants_the_add_ons_before_any_download(monkeypatch):
    monkeypatch.setattr(doctor, '_export_or_none', lambda: None)
    called = []
    monkeypatch.setattr(doctor, '_stream', lambda *a, **k: called.append(a))
    monkeypatch.setattr(doctor, '_node_env', lambda: called.append('node') or ('npm', {}))
    with pytest.raises(doctor.DoctorError, match='add-ons first'):
        doctor.install_renderer()
    assert called == []


def test_gpu_check_survives_an_exception_in_the_parity_run(monkeypatch):
    from ft import matte
    monkeypatch.setattr(sys, 'platform', 'win32')
    paths.rvm_model_path().parent.mkdir(parents=True)
    paths.rvm_model_path().write_bytes(b'x')

    def boom(*a, **k):
        raise RuntimeError('driver crashed')
    monkeypatch.setattr(matte, 'parity', boom)
    result = doctor.install('gpu')
    assert result['ok'] is True and 'processor' in result['message'] and 'Traceback' not in result['message']
    assert not JARGON.search(result['message']) and 'driver crashed' not in result['message']
    machine = json.loads((paths.user_dir() / 'machine.json').read_text(encoding='utf-8'))
    assert machine['matteProvider'] == 'cpu'


def test_the_ready_message_reads_right_for_every_step(monkeypatch):
    """One line the creator may be shown: "The Python add-ons are ready.", never "add-ons is"."""
    steps = ('venv', 'packages', 'rvm-model', 'renderer', 'words')
    for item_id in steps:
        monkeypatch.setitem(doctor.INSTALLERS, item_id, lambda log: None)
    assert [doctor.install(i)['message'] for i in steps] == [
        'The Python environment is ready.', 'The Python add-ons are ready.', 'The cutout model is ready.',
        'The video maker is ready.', 'The speech reader is ready.']
