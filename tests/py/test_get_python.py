"""get-python.ps1 (Windows) and get-python.sh (Mac): find a Python 3.10+, or download floored's own.

Each script is run for real through subprocess, with FLOORED_HOME and FLOORED_TOOLS_FILE pointing at temp files and a
local HTTP server standing in for the download address. The script of the other system is skipped.
"""
import hashlib
import http.server
import io
import os
import re
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[2] / 'plugin' / 'skills' / 'floored' / 'app'
WIN = sys.platform == 'win32'
MAC = sys.platform == 'darwin'
ARCHIVE = 'python.tar.gz'

SENT_DOWNLOAD = "Couldn't download Python ("
SENT_MISMATCH = "The Python download didn't match the expected file, so it was thrown away. Try again."
SENT_NO_LINE = "This computer's system has no Python download in floored's list."


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture
def file_server(tmp_path):
    root = tmp_path / 'www'
    root.mkdir()
    handler = lambda *a, **k: Quiet(*a, directory=str(root), **k)           # noqa: E731
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield root, 'http://127.0.0.1:%d/' % srv.server_address[1]
    srv.shutdown()
    srv.server_close()


def system_name():
    """The pin name the script will look for on this host."""
    if WIN:
        return 'win-x64'
    import platform
    return 'darwin-arm64' if platform.machine() == 'arm64' else 'darwin-x64'


def fake_archive():
    """A .tar.gz holding python/ with something that really runs and answers like a Python 3.10+."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        if WIN:
            exe = Path(sys.executable)
            tar.add(str(exe), arcname='python/python.exe')
            cfg = 'home = %s\ninclude-system-site-packages = false\nversion = %d.%d.%d\n' % (
                Path(sys.base_prefix), *sys.version_info[:3])
            data = cfg.encode()
            info = tarfile.TarInfo('python/pyvenv.cfg')
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        else:
            script = ('#!/bin/sh\nexec "%s" "$@"\n' % sys.executable).encode()
            info = tarfile.TarInfo('python/bin/python3')
            info.size = len(script)
            info.mode = 0o755
            tar.addfile(info, io.BytesIO(script))
    return buf.getvalue()


def pins(tmp_path, url, data, size=None, sha=None):
    """A pins file with a python line for both Mac systems and for Windows, all pointing at `url`."""
    size = len(data) if size is None else size
    sha = hashlib.sha256(data).hexdigest() if sha is None else sha
    lines = ['# test pins']
    for system in ('win-x64', 'darwin-arm64', 'darwin-x64'):
        lines.append('python  %s  %d  %s  %s' % (system, size, sha, url))
    lines.append('node  win-x64  1  ' + '0' * 64 + '  http://127.0.0.1:9/node.zip')
    f = tmp_path / 'tools-test.txt'
    f.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return f


def run(args, tmp_path, tools_file=None, env_over=None, home=None):
    home = home or (tmp_path / 'home')
    env = dict(os.environ)
    env['FLOORED_HOME'] = str(home)
    if tools_file is not None:
        env['FLOORED_TOOLS_FILE'] = str(tools_file)
    if env_over:
        env.update(env_over)
    if WIN:
        ps = os.path.join(os.environ['SystemRoot'], 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
        cmd = [ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(APP / 'get-python.ps1')] + args
    else:
        cmd = ['sh', str(APP / 'get-python.sh')] + args
    return subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env, timeout=120), home


def own_python(home):
    return home / 'tools' / 'python' / ('python.exe' if WIN else 'bin/python3')


def one_line(proc):
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, 'stdout was: %r' % proc.stdout
    return lines[0]


def is_py310(path):
    return subprocess.run([path, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'],
                          timeout=60).returncode == 0


needs_host = pytest.mark.skipif(not (WIN or MAC), reason="the script of this system only runs on Windows or a Mac")


def same_path(a, b):
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


# -- the scripts exist, and stay plain --------------------------------------------------------------------------------
def test_both_scripts_exist_beside_floored_py():
    assert (APP / 'get-python.ps1').is_file()
    assert (APP / 'get-python.sh').is_file()


def test_the_scripts_hold_no_modern_only_syntax():
    ps = (APP / 'get-python.ps1').read_text(encoding='utf-8')
    for bad in ('&&', '??', '$IsWindows', '?.'):
        assert bad not in ps, bad
    sh = (APP / 'get-python.sh').read_text(encoding='utf-8')
    assert sh.startswith('#!/bin/sh')
    assert '[[' not in sh and 'local ' not in sh


def test_the_scripts_hold_no_person_or_user_path():
    for name in ('get-python.ps1', 'get-python.sh'):
        text = (APP / name).read_text(encoding='utf-8')
        assert not re.search(r'[A-Za-z]:[\\/]+Users', text)
        assert not re.search(r'[\w.]+@[\w-]+\.[a-z]{2,}', text)


# -- find ----------------------------------------------------------------------------------------------------------------
@needs_host
def test_find_prints_one_line_with_a_python_310_or_newer(tmp_path):
    proc, _ = run([], tmp_path)
    assert proc.returncode == 0, proc.stderr
    line = one_line(proc)
    assert line.startswith('FLOORED_PYTHON=')
    path = line[len('FLOORED_PYTHON='):]
    assert os.path.isabs(path) and os.path.isfile(path)
    assert is_py310(path)


@pytest.mark.skipif(not WIN, reason="Windows script")
def test_find_with_nothing_to_find_says_no_python(tmp_path):
    empty = tmp_path / 'emptylocal'
    empty.mkdir()
    system32 = os.path.join(os.environ['SystemRoot'], 'System32')
    proc, _ = run([], tmp_path, env_over={'PATH': system32, 'LOCALAPPDATA': str(empty)})
    assert proc.returncode == 3, proc.stderr
    assert one_line(proc) == 'NO_PYTHON'


@pytest.mark.skipif(not MAC, reason="Mac script")
def test_find_with_nothing_to_find_says_no_python_mac(tmp_path):
    # PATH holds only a folder with no python; the fixed Homebrew and framework paths are checked by name in the script
    empty = tmp_path / 'emptybin'
    empty.mkdir()
    proc, _ = run([], tmp_path, env_over={'PATH': '/bin:/usr/bin:' + str(empty)})
    if proc.returncode == 0:
        pytest.skip("this Mac has a real Python in a fixed place")
    assert proc.returncode == 3, proc.stderr
    assert one_line(proc) == 'NO_PYTHON'


# -- install -------------------------------------------------------------------------------------------------------------
@needs_host
def test_install_with_a_good_archive_then_find_returns_it_first(tmp_path, file_server):
    root, base = file_server
    data = fake_archive()
    (root / ARCHIVE).write_bytes(data)
    tools = pins(tmp_path, base + ARCHIVE, data)
    proc, home = run(['--install'], tmp_path, tools)
    assert proc.returncode == 0, proc.stderr
    line = one_line(proc)
    assert line.startswith('FLOORED_PYTHON=')
    path = line[len('FLOORED_PYTHON='):]
    assert own_python(home).is_file()
    assert same_path(path, str(own_python(home)))
    assert not (home / 'tools' / 'python.part').exists()
    assert not (home / 'tools' / 'python.new').exists()
    again, _ = run([], tmp_path, tools)
    assert again.returncode == 0, again.stderr
    assert same_path(one_line(again)[len('FLOORED_PYTHON='):], str(own_python(home)))


@needs_host
def test_install_twice_does_not_download_again(tmp_path, file_server):
    root, base = file_server
    data = fake_archive()
    (root / ARCHIVE).write_bytes(data)
    tools = pins(tmp_path, base + ARCHIVE, data)
    first, home = run(['--install'], tmp_path, tools)
    assert first.returncode == 0, first.stderr
    (root / ARCHIVE).unlink()                      # a second download would now fail with 404
    second, _ = run(['--install'], tmp_path, tools)
    assert second.returncode == 0, second.stderr
    assert one_line(second) == one_line(first)


@needs_host
def test_install_replaces_a_broken_leftover(tmp_path, file_server):
    root, base = file_server
    data = fake_archive()
    (root / ARCHIVE).write_bytes(data)
    tools = pins(tmp_path, base + ARCHIVE, data)
    home = tmp_path / 'home'
    broken = home / 'tools' / 'python'
    broken.mkdir(parents=True)
    (broken / 'junk.txt').write_text('half an install')
    proc, _ = run(['--install'], tmp_path, tools, home=home)
    assert proc.returncode == 0, proc.stderr
    assert own_python(home).is_file()
    assert not (broken / 'junk.txt').exists()


def assert_clean_failure(proc, home, sentence):
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert proc.stdout.strip() == ''
    assert sentence in proc.stderr
    assert not (home / 'tools' / 'python').exists()
    assert not (home / 'tools' / 'python.part').exists()
    assert not (home / 'tools' / 'python.new').exists()


@needs_host
def test_install_with_a_wrong_sha256_is_thrown_away(tmp_path, file_server):
    root, base = file_server
    data = fake_archive()
    (root / ARCHIVE).write_bytes(data)
    tools = pins(tmp_path, base + ARCHIVE, data, sha='0' * 64)
    proc, home = run(['--install'], tmp_path, tools)
    assert_clean_failure(proc, home, SENT_MISMATCH)


@needs_host
def test_install_with_a_wrong_size_is_thrown_away(tmp_path, file_server):
    root, base = file_server
    data = fake_archive()
    (root / ARCHIVE).write_bytes(data)
    tools = pins(tmp_path, base + ARCHIVE, data, size=len(data) + 7)
    proc, home = run(['--install'], tmp_path, tools)
    assert_clean_failure(proc, home, SENT_MISMATCH)


@needs_host
def test_install_when_the_server_says_404(tmp_path, file_server):
    root, base = file_server
    data = fake_archive()
    tools = pins(tmp_path, base + 'missing.tar.gz', data)
    proc, home = run(['--install'], tmp_path, tools)
    assert_clean_failure(proc, home, SENT_DOWNLOAD)
    assert 'Check the internet connection and try again.' in proc.stderr
    assert proc.stderr.strip().splitlines()[-1].startswith(SENT_DOWNLOAD)     # the last line is the sentence


@needs_host
def test_install_with_no_line_for_this_system(tmp_path, file_server):
    root, base = file_server
    only_node = tmp_path / 'tools-nopython.txt'
    only_node.write_text('# nothing\nnode  win-x64  1  ' + '0' * 64 + '  http://127.0.0.1:9/n.zip\n', encoding='utf-8')
    proc, home = run(['--install'], tmp_path, only_node)
    assert_clean_failure(proc, home, SENT_NO_LINE)


@needs_host
def test_a_home_folder_with_accents_and_spaces(tmp_path, file_server):
    """A creator's user folder can be "José Conceição": the download unpacks there, and the one line the script prints
    is that path in UTF-8 (what Claude's shell reads), not a mangled one."""
    root, url = file_server
    data = fake_archive()
    (root / ARCHIVE).write_bytes(data)
    home = tmp_path / 'José Conceição' / '.floored'
    proc, home = run(['--install'], tmp_path, pins(tmp_path, url + ARCHIVE, data), home=home)
    assert proc.returncode == 0, proc.stderr
    line = one_line(proc)
    assert line.startswith('FLOORED_PYTHON=')
    printed = line[len('FLOORED_PYTHON='):]
    assert os.path.isfile(printed), 'the printed path does not exist: %r' % printed
    assert same_path(printed, own_python(home))
    assert is_py310(printed)
    proc, _ = run([], tmp_path, home=home)                       # a plain find returns the same path, readable again
    assert same_path(one_line(proc)[len('FLOORED_PYTHON='):], own_python(home))
