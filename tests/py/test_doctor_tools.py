"""The doctor downloads floored's own Node.js, ffmpeg and Python from the pinned files in app/tools.txt (T1).
Nothing here touches the internet: small fake archives in the layout of the host that runs the tests are served from a local
http.server, and the installed fake programs are really started."""
import argparse
import ast
import hashlib
import http.server
import json
import os
import re
import shutil
import socket
import sys
import tarfile
import threading
import zipfile
from pathlib import Path

import pytest

from ft import doctor, paths

APP = Path(__file__).resolve().parents[2] / 'plugin' / 'skills' / 'floored' / 'app'
REAL_PINS = APP / 'tools.txt'


def _host_key():
    import platform
    machine = platform.machine().lower()
    if sys.platform == 'win32':
        return 'win-x64' if machine in ('amd64', 'x86_64') else None
    if sys.platform == 'darwin':
        return {'arm64': 'darwin-arm64', 'x86_64': 'darwin-x64'}.get(machine)
    return None


KEY = _host_key()                                  # worked out here, not by the code under test
WIN = sys.platform == 'win32'
needs_pin = pytest.mark.skipif(KEY is None, reason='this computer has no pinned downloads')
windows_only = pytest.mark.skipif(not WIN, reason='the Windows archive layout')
mac_only = pytest.mark.skipif(not (KEY or '').startswith('darwin'), reason='the Mac archive layout')
JARGON = re.compile(r'rvm|onnx|directml|coreml|mib|k0|matte|\bvenv\b|zscale|libvpx|vp9|x264', re.I)
OWN_FOLDER = "floored downloads its own copy into its own folder; nothing else on your computer changes."
KEEP_YOURS = "floored downloads its own copy into its own folder and leaves yours alone."


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setenv('FLOORED_HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('FLOORED_RVM_MODEL', str(tmp_path / 'models' / 'rvm.onnx'))
    monkeypatch.setenv('FLOORED_RENDERER_DIR', str(tmp_path / 'renderer'))
    monkeypatch.delenv('FLOORED_RVM_URL', raising=False)
    empty = tmp_path / 'empty-tools.txt'
    empty.write_text('# no pins\n', encoding='utf-8')
    monkeypatch.setenv('FLOORED_TOOLS_FILE', str(empty))


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def file_server(tmp_path):
    root = tmp_path / 'www'
    root.mkdir()
    handler = lambda *a, **k: Quiet(*a, directory=str(root), **k)           # noqa: E731
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield root, 'http://127.0.0.1:%d/' % srv.server_address[1]
    srv.shutdown()
    srv.server_close()


# -- building fake archives ---------------------------------------------------------------------------------------------
def make_zip(path, files):
    with zipfile.ZipFile(str(path), 'w', zipfile.ZIP_STORED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path


def make_targz(path, files, links=None):
    """files: {name: bytes} (every file executable); links: {name: target} symbolic links."""
    import io
    with tarfile.open(str(path), 'w:gz') as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), 0o755
            t.addfile(info, io.BytesIO(data))
        for name, target in (links or {}).items():
            info = tarfile.TarInfo(name)
            info.type, info.linkname = tarfile.SYMTYPE, target
            t.addfile(info)
    return path


def sh(text):
    return ('#!/bin/sh\n' + text + '\n').encode()


def cmd(text):
    return ('@echo off\r\n' + text + '\r\n').encode()


def node_archive(tmp_path, version='v22.23.4', filler=0):
    extra = {'node-v0/filler.bin': os.urandom(filler)} if filler else {}
    if WIN:
        return make_zip(tmp_path / 'node.zip', dict({'node-v0/node.cmd': cmd('echo ' + version), 'node-v0/npm.cmd': cmd('echo 10.9.0')}, **extra))
    return make_targz(tmp_path / 'node.tar.gz', dict({'node-v0/bin/node': sh('echo ' + version), 'node-v0/bin/npm': sh('echo 10.9.0')}, **extra))


def python_archive(tmp_path):
    """Windows: a real, small python.exe (the base install's, with its DLLs and a ._pth file that points at the standard library)
    so the downloaded Python is started for real. Elsewhere: a shell script that answers like Python 3.12.16."""
    if not WIN:
        return make_targz(tmp_path / 'python.tar.gz', {'python/bin/python3': sh('echo 3 12 16')})
    base = Path(sys.base_prefix)
    files = {}
    for name in ('python.exe', 'python3.dll', 'python%d%d.dll' % sys.version_info[:2], 'vcruntime140.dll', 'vcruntime140_1.dll'):
        if (base / name).is_file():
            files['python/' + name] = (base / name).read_bytes()
    files['python/python._pth'] = ('%s\n%s\n' % (base / 'Lib', base / 'DLLs')).encode()
    return make_targz(tmp_path / 'python.tar.gz', files)


FAKE_FFMPEG_WIN = cmd('if "%1"=="-version" echo ffmpeg version 9.0.2-test Copyright\r\n'
                      'if "%2"=="-filters" echo  T.C zscale  Apply resizing\r\n'
                      'if "%2"=="-encoders" echo  V....D libx264  H.264\r\n'
                      'if "%2"=="-encoders" echo  V....D libvpx-vp9  VP9')
FAKE_FFMPEG_SH = sh('case "$1$2" in\n-version*) echo ffmpeg version 9.0.2-test Copyright;;\n'
                    '-hide_banner-filters) echo " T.C zscale  Apply resizing";;\n'
                    '-hide_banner-encoders) echo " V....D libx264  H.264"; echo " V....D libvpx-vp9  VP9";;\nesac')


def ffmpeg_zip_windows(tmp_path):
    return make_zip(tmp_path / 'ffmpeg.zip', {
        'ffmpeg-v0/bin/ffmpeg.cmd': FAKE_FFMPEG_WIN, 'ffmpeg-v0/bin/ffprobe.cmd': cmd('echo ffprobe version 9.0.2'),
        'ffmpeg-v0/bin/avcodec-0.dll': b'dll', 'ffmpeg-v0/doc/readme.txt': b'not a program', 'ffmpeg-v0/LICENSE': b'x'})


def write_pins(tmp_path, monkeypatch, lines):
    f = tmp_path / 'tools-under-test.txt'
    f.write_text('# test pins\n\n' + '\n'.join(lines) + '\n', encoding='utf-8')
    monkeypatch.setenv('FLOORED_TOOLS_FILE', str(f))


def serve(file_server, archive, name=None):
    """Copy an archive into the served folder; returns (pin fields: bytes, sha256, url)."""
    root, url = file_server
    name = name or archive.name
    shutil.copyfile(str(archive), str(root / name))
    data = archive.read_bytes()
    return len(data), hashlib.sha256(data).hexdigest(), url + name


def pin(tool, size, sha, url, key=None):
    return '%s %s %d %s %s' % (tool, key or KEY, size, sha, url)


def tools_dir():
    return paths.user_dir() / 'tools'


def no_leftovers():
    folder = tools_dir()
    return not folder.exists() or not [p for p in folder.iterdir() if p.name.endswith(('.part', '.new'))]


# -- the pins ----------------------------------------------------------------------------------------------------------
def test_pins_reader_skips_comments_and_blank_lines_and_follows_the_environment_variable(tmp_path, monkeypatch):
    write_pins(tmp_path, monkeypatch, [pin('node', 123, 'a' * 64, 'https://example.test/n.zip', 'win-x64'),
                                       pin('ffprobe', 9, 'b' * 64, 'https://example.test/p.zip', 'darwin-arm64'), 'broken line'])
    pins = doctor.read_pins()
    assert pins[('node', 'win-x64')] == {'bytes': 123, 'sha256': 'a' * 64, 'url': 'https://example.test/n.zip'}
    assert set(pins) == {('node', 'win-x64'), ('ffprobe', 'darwin-arm64')}
    monkeypatch.delenv('FLOORED_TOOLS_FILE')
    assert doctor.tools_file() == paths.APP_DIR / 'tools.txt' and ('python', 'win-x64') in doctor.read_pins()


@pytest.mark.parametrize('plat,machine,key', [('win32', 'AMD64', 'win-x64'), ('win32', 'x86_64', 'win-x64'), ('win32', 'ARM64', None),
                                              ('darwin', 'arm64', 'darwin-arm64'), ('darwin', 'x86_64', 'darwin-x64'),
                                              ('linux', 'x86_64', None)])
def test_system_key(monkeypatch, plat, machine, key):
    import platform
    monkeypatch.setattr(sys, 'platform', plat)
    monkeypatch.setattr(platform, 'machine', lambda: machine)
    assert doctor.system_key() == key


def test_the_real_pins_file_is_well_formed():
    rows = []
    for line in REAL_PINS.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        fields = line.split()
        assert len(fields) == 5, line
        tool, system, size, sha, url = fields
        assert re.fullmatch(r'[0-9a-f]{64}', sha), line
        assert size.isdigit() and int(size) > 1_000_000, line
        assert url.startswith('https://'), line
        rows.append((tool, system))
    assert len(rows) == len(set(rows)) == 11
    want = {('python', s) for s in ('win-x64', 'darwin-arm64', 'darwin-x64')} | {('node', s) for s in ('win-x64', 'darwin-arm64', 'darwin-x64')}
    want |= {('ffmpeg', s) for s in ('win-x64', 'darwin-arm64', 'darwin-x64')} | {('ffprobe', s) for s in ('darwin-arm64', 'darwin-x64')}
    assert set(rows) == want


# -- Node.js: a real local download, unpack and run ------------------------------------------------------------------------
@needs_pin
def test_a_good_node_download_installs_records_and_turns_the_report_ok(tmp_path, monkeypatch, file_server):
    size, sha, url = serve(file_server, node_archive(tmp_path))
    write_pins(tmp_path, monkeypatch, [pin('node', size, sha, url)])
    result = doctor.install('node')
    assert result == {'id': 'node', 'ok': True, 'message': 'Node.js is ready.', 'code': 0}, result
    own = tools_dir() / 'node'
    exe = own / ('node.cmd' if WIN else 'bin/node')
    assert exe.is_file() and (own / ('npm.cmd' if WIN else 'bin/npm')).is_file()
    assert not (own / 'node-v0').exists() and no_leftovers()                      # the top folder is dropped
    recorded = doctor.recorded_tools()
    assert os.path.samefile(recorded['node'], str(exe)) and os.path.dirname(recorded['npm']) == os.path.dirname(recorded['node'])
    assert doctor.node_version(recorded['node']) == (22, 23, 4)                   # the unpacked program really starts
    item = doctor.check_node()
    assert item['ok'] is True and item['found'] == 'Node.js 22.23.4' and item['note'] == ''


@needs_pin
def test_node_progress_lines_come_about_every_5_mb(tmp_path, monkeypatch, file_server):
    size, sha, url = serve(file_server, node_archive(tmp_path, filler=12_000_000))
    write_pins(tmp_path, monkeypatch, [pin('node', size, sha, url)])
    lines = []
    result = doctor.install('node', log=lines.append)
    assert result['ok'] is True, result
    assert lines and all(re.fullmatch(r'Node\.js: \d+ of \d+ MB', l) for l in lines), lines
    assert 1 <= len(lines) <= 4


@needs_pin
def test_a_wrong_sha256_installs_nothing_and_says_so_plainly(tmp_path, monkeypatch, file_server):
    size, sha, url = serve(file_server, node_archive(tmp_path))
    write_pins(tmp_path, monkeypatch, [pin('node', size, '0' * 64, url)])
    result = doctor.install('node')
    assert result['ok'] is False and "didn't download correctly" in result['message'] and 'Node.js' in result['message']
    assert not JARGON.search(result['message']) and 'sha' not in result['message'].lower()
    assert not (tools_dir() / 'node').exists() and no_leftovers() and doctor.recorded_tools() == {}


@needs_pin
def test_a_wrong_byte_count_installs_nothing_either(tmp_path, monkeypatch, file_server):
    size, sha, url = serve(file_server, node_archive(tmp_path))
    write_pins(tmp_path, monkeypatch, [pin('node', size + 1, sha, url)])
    result = doctor.install('node')
    assert result['ok'] is False and "didn't download correctly" in result['message']
    assert not (tools_dir() / 'node').exists() and no_leftovers()


@needs_pin
def test_a_404_names_the_page_to_install_it_yourself(tmp_path, monkeypatch, file_server):
    root, url = file_server
    write_pins(tmp_path, monkeypatch, [pin('node', 1000, 'a' * 64, url + 'gone.zip')])
    result = doctor.install('node')
    assert result['ok'] is False and doctor.MANUAL['node']['page'] in result['message'] and 'moved' in result['message']
    assert 'update floored' in result['message'].lower() and no_leftovers()


@needs_pin
def test_an_unreachable_server_is_the_internet_sentence(tmp_path, monkeypatch):
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]                                                     # a port nobody listens on
    write_pins(tmp_path, monkeypatch, [pin('node', 1000, 'a' * 64, 'http://127.0.0.1:%d/n.zip' % port)])
    result = doctor.install('node')
    assert result['ok'] is False and result['message'].startswith("Couldn't download Node.js (")
    assert result['message'].endswith('Check the internet connection and try again.') and no_leftovers()


@needs_pin
def test_an_old_node_on_the_path_loses_to_floreds_own_after_the_install(tmp_path, monkeypatch, file_server):
    old = tmp_path / 'oldbin'
    old.mkdir()
    if WIN:
        (old / 'node.cmd').write_bytes(cmd('echo v18.0.0'))
        (old / 'npm.cmd').write_bytes(cmd('echo 9.0.0'))
    else:
        for name, text in (('node', 'echo v18.0.0'), ('npm', 'echo 9.0.0')):
            (old / name).write_bytes(sh(text))
            (old / name).chmod(0o755)
    monkeypatch.setenv('PATH', str(old) + os.pathsep + os.environ['PATH'])
    before = doctor.check_node()
    assert before['ok'] is False and before['found'] == 'Node.js 18.0.0'
    size, sha, url = serve(file_server, node_archive(tmp_path))
    write_pins(tmp_path, monkeypatch, [pin('node', size, sha, url)])
    assert doctor.install('node')['ok'] is True
    hit = doctor.find_program('node')
    assert hit['via'] == 'config'
    assert os.path.normcase(str(tools_dir())) in os.path.normcase(hit['path'])
    after = doctor.check_node()
    assert after['ok'] is True and after['found'] == 'Node.js 22.23.4'


@needs_pin
def test_an_install_replaces_a_leftover_of_an_earlier_failed_run(tmp_path, monkeypatch, file_server):
    (tools_dir() / 'node.new').mkdir(parents=True)
    (tools_dir() / 'node.new' / 'half-unpacked').write_text('x')
    (tools_dir() / 'node').mkdir()
    (tools_dir() / 'node' / 'old-file').write_text('x')
    (tools_dir() / 'node.part').write_bytes(b'half')
    size, sha, url = serve(file_server, node_archive(tmp_path))
    write_pins(tmp_path, monkeypatch, [pin('node', size, sha, url)])
    assert doctor.install('node')['ok'] is True
    assert not (tools_dir() / 'node' / 'old-file').exists() and no_leftovers()


# -- ffmpeg ---------------------------------------------------------------------------------------------------------------
@needs_pin
@windows_only
def test_ffmpeg_windows_layout_puts_the_files_of_bin_flat_and_they_run(tmp_path, monkeypatch, file_server):
    size, sha, url = serve(file_server, ffmpeg_zip_windows(tmp_path))
    write_pins(tmp_path, monkeypatch, [pin('ffmpeg', size, sha, url)])
    result = doctor.install('ffmpeg')
    assert result['ok'] is True, result
    own = tools_dir() / 'ffmpeg'
    assert sorted(p.name for p in own.iterdir()) == ['avcodec-0.dll', 'ffmpeg.cmd', 'ffprobe.cmd']
    recorded = doctor.recorded_tools()
    assert os.path.samefile(recorded['ffmpeg'], str(own / 'ffmpeg.cmd')) and os.path.samefile(recorded['ffprobe'], str(own / 'ffprobe.cmd'))
    assert doctor.ffmpeg_features(recorded['ffmpeg']) == {'version': '9.0.2-test', 'missing': []}   # really started
    item = doctor.check_ffmpeg()
    assert item['ok'] is True and item['found'] == 'ffmpeg 9.0.2-test'
    assert no_leftovers()


@needs_pin
@mac_only
def test_ffmpeg_mac_layout_two_zips_both_made_executable(tmp_path, monkeypatch, file_server):
    z1 = make_zip(tmp_path / 'ffmpeg.zip', {'ffmpeg': FAKE_FFMPEG_SH})
    z2 = make_zip(tmp_path / 'ffprobe.zip', {'ffprobe': sh('echo ffprobe version 9.0.2')})
    a, b = serve(file_server, z1), serve(file_server, z2)
    write_pins(tmp_path, monkeypatch, [pin('ffmpeg', *a), pin('ffprobe', *b)])
    assert doctor.install('ffmpeg')['ok'] is True
    own = tools_dir() / 'ffmpeg'
    assert sorted(p.name for p in own.iterdir()) == ['ffmpeg', 'ffprobe']
    assert all(os.access(str(own / n), os.X_OK) and (own / n).stat().st_mode & 0o777 == 0o755 for n in ('ffmpeg', 'ffprobe'))
    assert doctor.ffmpeg_features(str(own / 'ffmpeg'))['missing'] == [] and doctor.check_ffmpeg()['ok'] is True


@needs_pin
def test_an_ffmpeg_without_the_needed_parts_is_not_kept_as_a_success(tmp_path, monkeypatch, file_server):
    """The archive unpacks and starts, but it can't convert HDR video, so the install says it failed."""
    if WIN:
        weak = make_zip(tmp_path / 'weak.zip', {'f/bin/ffmpeg.cmd': cmd('if "%1"=="-version" echo ffmpeg version 1'), 'f/bin/ffprobe.cmd': cmd('echo p')})
        size, sha, url = serve(file_server, weak)
        write_pins(tmp_path, monkeypatch, [pin('ffmpeg', size, sha, url)])
    else:
        a = serve(file_server, make_zip(tmp_path / 'ffmpeg.zip', {'ffmpeg': sh('echo ffmpeg version 1')}))
        b = serve(file_server, make_zip(tmp_path / 'ffprobe.zip', {'ffprobe': sh('echo p')}))
        write_pins(tmp_path, monkeypatch, [pin('ffmpeg', *a), pin('ffprobe', *b)])
    result = doctor.install('ffmpeg')
    assert result['ok'] is False and 'ffmpeg' in result['message'] and not JARGON.search(result['message'])
    assert 'ffmpeg' not in doctor.recorded_tools()


# -- Python -----------------------------------------------------------------------------------------------------------------
@needs_pin
def test_python_is_downloaded_unpacked_started_and_found_right_after_this_interpreter(tmp_path, monkeypatch, file_server):
    size, sha, url = serve(file_server, python_archive(tmp_path))
    write_pins(tmp_path, monkeypatch, [pin('python', size, sha, url)])
    result = doctor.install('python')
    assert result['ok'] is True and result['message'] == 'Python is ready.', result
    exe = tools_dir() / 'python' / ('python.exe' if WIN else 'bin/python3')
    assert exe.is_file() and not (tools_dir() / 'python' / 'python').exists() and no_leftovers()   # the archive's top folder is dropped
    found = list(doctor._pythons())
    assert found[0][0] == sys.executable
    assert os.path.samefile(found[1][0], str(exe)) and found[1][1] >= doctor.MIN_PYTHON            # started for real


@needs_pin
def test_python_that_does_not_run_is_a_plain_failure(tmp_path, monkeypatch, file_server):
    if WIN:
        bad = make_targz(tmp_path / 'bad.tar.gz', {'python/python.exe': b'this is not a program'})
    else:
        bad = make_targz(tmp_path / 'bad.tar.gz', {'python/bin/python3': sh('echo 2 7 18')})
    size, sha, url = serve(file_server, bad)
    write_pins(tmp_path, monkeypatch, [pin('python', size, sha, url)])
    result = doctor.install('python')
    assert result['ok'] is False and 'Python' in result['message'] and 'Traceback' not in result['message']


# -- finding: floored's own folders come first ---------------------------------------------------------------------------------
def test_search_dirs_lists_floreds_own_folders_first(monkeypatch):
    own = tools_dir()
    dirs = [os.path.normcase(d) for d in doctor.search_dirs()]
    first = dirs[:5]
    for sub in ('node', 'ffmpeg', 'python'):
        assert os.path.normcase(str(own / sub)) in first, (sub, first)


# -- the report ---------------------------------------------------------------------------------------------------------------
def fake_pin_for(tmp_path, monkeypatch, key=None):
    write_pins(tmp_path, monkeypatch, [pin('python', 47_438_699, 'a' * 64, 'https://example.test/py.tar.gz'),
                                       pin('node', 35_604_229, 'b' * 64, 'https://example.test/node.zip'),
                                       pin('ffmpeg', 99_899_672, 'c' * 64, 'https://example.test/ffmpeg.zip')])


def only_nothing_found(monkeypatch):
    monkeypatch.setattr(doctor, 'find_program', lambda name: None)
    monkeypatch.setattr(doctor, '_pythons', lambda: iter([]))


@needs_pin
def test_a_missing_node_with_a_pin_is_an_automatic_download(tmp_path, monkeypatch):
    fake_pin_for(tmp_path, monkeypatch)
    only_nothing_found(monkeypatch)
    item = doctor.check_node()
    assert item == {'id': 'node', 'ok': False, 'found': None, 'need': 'Node.js 22 or newer', 'mb': 36, 'how': 'auto',
                    'command': 'download https://example.test/node.zip',
                    'note': "Node.js isn't installed. " + OWN_FOLDER}, item
    assert not JARGON.search(item['note'])


@needs_pin
def test_python_and_ffmpeg_missing_with_pins_say_auto_with_the_pinned_size(tmp_path, monkeypatch):
    fake_pin_for(tmp_path, monkeypatch)
    only_nothing_found(monkeypatch)
    py, ff = doctor.check_python(), doctor.check_ffmpeg()
    assert (py['how'], py['mb'], py['command']) == ('auto', 47, 'download https://example.test/py.tar.gz') and py['note'].endswith(OWN_FOLDER)
    assert (ff['how'], ff['mb'], ff['command']) == ('auto', 100, 'download https://example.test/ffmpeg.zip') and ff['note'].endswith(OWN_FOLDER)
    total, summary = doctor.summarize([py, ff, doctor.check_node()])
    assert total == 47 + 100 + 36 and 'Python (47 MB)' in summary


@needs_pin
def test_an_older_program_that_was_found_is_left_alone(tmp_path, monkeypatch):
    fake_pin_for(tmp_path, monkeypatch)
    monkeypatch.setattr(doctor, '_pythons', lambda: iter([('/usr/bin/python3', (3, 8, 10))]))
    item = doctor.check_python()
    assert item['how'] == 'auto' and item['found'] == 'Python 3.8.10' and '3.8.10' in item['note'] and item['note'].endswith(KEEP_YOURS)
    monkeypatch.setattr(doctor, 'find_program', lambda name: {'path': '/x/' + name, 'via': 'path', 'stale': None})
    monkeypatch.setattr(doctor, '_capture', lambda c, timeout=60, env=None: (0, 'v20.11.0\n'))
    node = doctor.check_node()
    assert node['how'] == 'auto' and node['found'] == 'Node.js 20.11.0' and node['note'].endswith(KEEP_YOURS)


@needs_pin
def test_an_incomplete_ffmpeg_is_left_alone_and_a_good_program_stays_manual_ok(tmp_path, monkeypatch):
    fake_pin_for(tmp_path, monkeypatch)
    monkeypatch.setattr(doctor, 'find_program', lambda name: {'path': '/x/' + name, 'via': 'path', 'stale': None})
    monkeypatch.setattr(doctor, '_capture', lambda c, timeout=60, env=None: (0, 'ffmpeg version 8.1' if '-version' in c else ''))
    item = doctor.check_ffmpeg()
    assert item['how'] == 'auto' and item['note'].endswith(KEEP_YOURS) and 'convert HDR video' in item['note']
    monkeypatch.setattr(doctor, '_capture', lambda c, timeout=60, env=None: (0, 'v22.14.0\n'))
    ok = doctor.check_node()
    assert ok['ok'] is True and ok['how'] == 'manual' and ok['command'] == '' and ok['note'] == ''


def test_a_mac_ffmpeg_download_counts_ffmpeg_and_ffprobe(tmp_path, monkeypatch):
    write_pins(tmp_path, monkeypatch, [pin('ffmpeg', 28_395_699, 'a' * 64, 'https://example.test/ffmpeg.zip', 'darwin-arm64'),
                                       pin('ffprobe', 28_317_701, 'b' * 64, 'https://example.test/ffprobe.zip', 'darwin-arm64')])
    monkeypatch.setattr(doctor, 'system_key', lambda: 'darwin-arm64')
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(doctor, 'find_program', lambda name: None)
    item = doctor.check_ffmpeg()
    assert item['how'] == 'auto' and item['mb'] == 57 and item['command'] == 'download https://example.test/ffmpeg.zip'


def test_a_system_without_a_pin_keeps_the_manual_answer(tmp_path, monkeypatch):
    write_pins(tmp_path, monkeypatch, [pin('node', 1, 'a' * 64, 'https://example.test/n.zip', 'win-x64')])    # none for this system
    monkeypatch.setattr(doctor, 'system_key', lambda: None)
    only_nothing_found(monkeypatch)
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(doctor, 'which', lambda prog, path=None: ('/x/' + prog) if prog == 'winget' else None)
    item = doctor.check_node()
    assert item['how'] == 'manual' and item['mb'] == doctor.SIZES_MB['node'] and item['note'] == "Node.js isn't installed."
    assert item['command'] == WINGET_NODE
    result = doctor.install('node')
    assert result['ok'] is False and result['code'] == 2 and WINGET_NODE in result['message']


WINGET_FLAGS = '--source winget --accept-source-agreements --accept-package-agreements --disable-interactivity'
WINGET_NODE = 'winget install --id OpenJS.NodeJS.LTS -e ' + WINGET_FLAGS


def test_the_windows_winget_command_carries_the_flags_a_fresh_pc_needs(monkeypatch):
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(doctor, 'which', lambda prog, path=None: ('/x/' + prog) if prog == 'winget' else None)
    for item_id, winget_id in (('python', 'Python.Python.3.12'), ('node', 'OpenJS.NodeJS.LTS'), ('ffmpeg', 'Gyan.FFmpeg'), ('browser', 'Google.Chrome')):
        assert doctor.install_command(item_id) == 'winget install --id %s -e %s' % (winget_id, WINGET_FLAGS)


@needs_pin
def test_the_cli_install_prints_one_json_line_and_exit_0(tmp_path, monkeypatch, file_server, capsys):
    size, sha, url = serve(file_server, node_archive(tmp_path))
    write_pins(tmp_path, monkeypatch, [pin('node', size, sha, url)])
    code = doctor.main(argparse.Namespace(json=False, install='node', gpu_check=False))
    out = capsys.readouterr().out.strip().splitlines()
    assert code == 0 and len(out) == 1 and json.loads(out[0]) == {'id': 'node', 'ok': True, 'message': 'Node.js is ready.'}


def test_the_plain_report_with_the_real_pins_makes_no_network_connection(monkeypatch):
    monkeypatch.delenv('FLOORED_TOOLS_FILE')

    def refuse(*a, **k):
        raise AssertionError('the plain report opened a connection')
    monkeypatch.setattr(socket.socket, 'connect', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)
    assert doctor.build_report()['items'] and doctor.main(argparse.Namespace(json=True, install=None, gpu_check=False)) in (0, 1)


# -- old Pythons -------------------------------------------------------------------------------------------------------------
def test_doctor_py_uses_no_syntax_newer_than_python_3_7():
    """doctor.py is what starts on a Mac whose only Python is old: no match, no walrus, no `X | None`, no dict `|`."""
    source = (APP / 'ft' / 'doctor.py').read_text(encoding='utf-8')
    tree = ast.parse(source, feature_version=(3, 7))                                  # rejects the walrus, positional-only, match
    for node in ast.walk(tree):
        assert not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.BitOr), 'a `|` expression at line %s' % node.lineno
    assert not re.search(r':\s*[A-Za-z_\[\], ]+\s*\|\s*None', source)
    assert 'removeprefix' not in source and 'removesuffix' not in source
