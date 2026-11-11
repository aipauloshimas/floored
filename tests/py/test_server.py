"""The workspace server and its command line: ports, reuse, detach, stop, status, idle exit, and the local-only guards."""
import json
import os
import random
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from conftest import APP, REPO, free_port
from ft import cli, paths, pipeline, server

FLOORED = str(APP / 'floored.py')


def port_base():
    """A base whose next few ports are free, in 20000-40000: away from 3020 / 3010 / 3198 / 3199 (other servers may run)."""
    for _ in range(200):
        base = random.randint(20000, 40000)
        try:
            for p in range(base, base + 4):
                with socket.socket() as s:
                    s.bind(('127.0.0.1', p))
            return base
        except OSError:
            continue
    raise RuntimeError('no port')


class Cli:
    """Runs `floored.py <args>` as a child process with a private user folder and port range."""

    def __init__(self, home, base):
        self.env = dict(os.environ, PYTHONUTF8='1', FLOORED_HOME=str(home), FT_PORT_BASE=str(base))
        self.workspaces = []

    def run(self, *args, timeout=60, env=None):
        args = [str(a) for a in args]
        if '--workspace' in args:
            self.workspaces.append(args[args.index('--workspace') + 1])
        e = dict(self.env, **(env or {}))
        return subprocess.run([sys.executable, FLOORED, *args], capture_output=True, stdin=subprocess.DEVNULL, text=True, encoding='utf-8',
                              errors='replace', timeout=timeout, env=e)

    @staticmethod
    def url_of(result):
        lines = [l for l in result.stdout.splitlines() if l.startswith('FLOORED_URL=')]
        assert len(lines) == 1, (result.stdout, result.stderr)
        return lines[0].split('=', 1)[1]


@pytest.fixture
def ftcli(tmp_path_factory):
    c = Cli(tmp_path_factory.mktemp('ft-home'), port_base())
    yield c
    for w in sorted(set(c.workspaces)):                      # (a copy: run() appends) detached servers are nobody's children: stop them by hand
        try:
            c.run('stop', '--workspace', w, timeout=30)       # stop by the pid in .server.json, never by process name
        except subprocess.TimeoutExpired:
            pass
        rec = server.read_server_file(paths.Workspace(w))
        if rec and rec.get('pid') != os.getpid() and cli.pid_alive(rec.get('pid') or 0):   # silent_server records this very process
            cli.kill_tree(rec['pid'])


def fetch(url, path, headers=None, method='GET', data=None):
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url.rstrip('/') + path, headers=headers or {}, method=method, data=data)
    try:
        with server.LOOPBACK.open(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode('utf-8') or 'null')
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode('utf-8') or 'null')


def wait_gone(pid, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not cli.pid_alive(pid):
            return True
        time.sleep(0.1)
    return not cli.pid_alive(pid)


# ----------------------------------------------------------------------------------------------------------- ports
def test_bind_does_no_name_lookup(monkeypatch):
    """HTTPServer's own bind asks reverse DNS for the host's name: 35 s on GitHub's Macs. Ours never asks."""
    def no_dns(*a, **k):
        raise AssertionError('reverse DNS lookup at bind')
    monkeypatch.setattr(socket, 'getfqdn', no_dns)
    srv = server.bind(None)
    try:
        assert srv.server_name == '127.0.0.1' and srv.server_port == srv.server_address[1]
    finally:
        srv.server_close()


def test_first_free_port(tmp_path, ftcli):
    base = port_base()
    busy = socket.socket()
    busy.bind(('127.0.0.1', base))
    busy.listen(1)
    try:
        r = ftcli.run('serve', '--workspace', tmp_path / 'p', '--detach', env={'FT_PORT_BASE': str(base)})
        assert r.returncode == 0, r.stderr
        assert ftcli.url_of(r) == 'http://127.0.0.1:%d/' % (base + 1)
    finally:
        busy.close()


def test_explicit_port_busy_fails_with_a_message(tmp_path, ftcli):
    busy = socket.socket()
    busy.bind(('127.0.0.1', 0))
    busy.listen(1)
    try:
        r = ftcli.run('serve', '--workspace', tmp_path / 'p', '--detach', '--port', busy.getsockname()[1])
        assert r.returncode != 0
        assert 'FLOORED_URL' not in r.stdout
        assert 'port' in (r.stderr + r.stdout).lower()
    finally:
        busy.close()


def test_host_flag_is_gone(tmp_path, ftcli):
    r = ftcli.run('serve', '--workspace', tmp_path / 'p', '--host', '0.0.0.0')
    assert r.returncode == 2 and '--host' in r.stderr


# ------------------------------------------------------------------------------------------- detach, reuse, stop
def test_reuse_running_server(tmp_path, ftcli):
    a = ftcli.run('serve', '--workspace', tmp_path / 'p', '--detach')
    b = ftcli.run('serve', '--workspace', tmp_path / 'p', '--detach')
    assert a.returncode == b.returncode == 0, (a.stderr, b.stderr)
    assert ftcli.url_of(a) == ftcli.url_of(b)
    rec = server.read_server_file(paths.Workspace(tmp_path / 'p'))
    status, info = fetch(ftcli.url_of(a), '/api/info')
    assert status == 200 and info['pid'] == rec['pid']          # one server, one pid


def test_server_json_and_info(tmp_path, ftcli):
    r = ftcli.run('serve', '--workspace', tmp_path / 'p', '--detach')
    url = ftcli.url_of(r)
    rec = json.loads((tmp_path / 'p' / 'floored' / '.server.json').read_text(encoding='utf-8'))
    assert set(rec) == {'pid', 'port', 'url', 'workspace', 'version', 'started'}
    assert rec['url'] == url and rec['port'] == int(url.split(':')[2].strip('/'))
    plugin_version = json.loads((REPO / 'plugin' / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))['version']
    status, info = fetch(url, '/api/info')
    assert status == 200 and info['version'] == rec['version'] == plugin_version
    assert os.path.realpath(info['workspace']) == os.path.realpath(tmp_path / 'p')
    assert info['estimates'] == {'renderSecPerFrame': {'1': 1.3, '2': 2.7}}
    assert (tmp_path / 'p' / 'floored' / 'server.log').is_file()


def test_detached_server_in_a_path_with_accents(tmp_path, ftcli):
    ws = tmp_path / 'Área de Trabalho' / 'meu reel ção ł日本'
    ws.mkdir(parents=True)
    r = ftcli.run('serve', '--workspace', ws, '--detach')
    assert r.returncode == 0, r.stderr
    status, info = fetch(ftcli.url_of(r), '/api/info')
    assert status == 200 and 'meu reel' in info['workspace']
    assert 'FLOORED_URL=' in (ws / 'floored' / 'server.log').read_text(encoding='utf-8')


def test_stop(tmp_path, ftcli):
    w = tmp_path / 'p'
    r = ftcli.run('serve', '--workspace', w, '--detach')
    assert r.returncode == 0
    pid = server.read_server_file(paths.Workspace(w))['pid']
    s = ftcli.run('stop', '--workspace', w)
    assert s.returncode == 0, s.stderr
    assert wait_gone(pid, 10)
    assert not (w / 'floored' / '.server.json').exists()
    again = ftcli.run('stop', '--workspace', w)                       # none running: still exit 0
    assert again.returncode == 0


def test_stop_with_nothing_running(tmp_path, ftcli):
    assert ftcli.run('stop', '--workspace', tmp_path / 'nothing').returncode == 0


def test_stop_never_kills_an_unrelated_pid(tmp_path, ftcli):
    """.server.json names a pid that something else now uses (nothing listens on the recorded port)."""
    w = tmp_path / 'p'
    paths.Workspace(w).ensure()
    other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    try:
        (w / 'floored' / '.server.json').write_text(json.dumps(
            {'pid': other.pid, 'port': free_port(), 'url': 'x', 'workspace': str(w), 'version': '0', 'started': 'x'}), encoding='utf-8')
        assert ftcli.run('stop', '--workspace', w).returncode == 0
        assert other.poll() is None                                   # still running
        assert not (w / 'floored' / '.server.json').exists()       # the stale record is cleaned up
    finally:
        other.kill()
        other.wait()


def test_stop_does_not_kill_another_workspaces_server(tmp_path, ftcli):
    a, b = tmp_path / 'a', tmp_path / 'b'
    ra = ftcli.run('serve', '--workspace', a, '--detach')
    assert ra.returncode == 0
    rec = server.read_server_file(paths.Workspace(a))
    paths.Workspace(b).ensure()
    (b / 'floored' / '.server.json').write_text(json.dumps(rec), encoding='utf-8')       # b's record points at a's server
    assert ftcli.run('stop', '--workspace', b).returncode == 0
    assert cli.pid_alive(rec['pid'])
    assert fetch(ftcli.url_of(ra), '/api/info')[0] == 200


def _seed(w):
    """One take (cutting) and one export (done) on disk, the way a studio leaves them."""
    d = paths.Workspace(w).takes / 't1'
    d.mkdir(parents=True)
    (d / 'take.json').write_text('{"id": "t1", "name": "x", "created": "2026-01-01T00:00:00"}', encoding='utf-8')
    (d / 'status.json').write_text('{"stage": "cutting", "progress": 0.5, "overall": 0.4, "message": "m"}', encoding='utf-8')
    e = paths.Workspace(w).exports / '20260101-000000-abcd'
    e.mkdir(parents=True)
    (e / 'status.json').write_text('{"id": "20260101-000000-abcd", "stage": "done", "progress": 1}', encoding='utf-8')


def test_status_no_studio_lists_the_takes_of_the_folder(tmp_path, ftcli):
    w = tmp_path / 'p'
    r = ftcli.run('status', '--workspace', w)                       # nothing there yet
    assert r.returncode == 0
    assert json.loads(r.stdout) == {'running': False, 'url': None, 'takes': [], 'exports': []}
    _seed(w)                                                        # a studio that stopped leaves these behind
    r = ftcli.run('status', '--workspace', w)
    assert r.returncode == 0
    out = json.loads(r.stdout)
    assert out['running'] is False and out['url'] is None
    assert out['takes'] == [{'id': 't1', 'name': 'x', 'stage': 'cutting', 'progress': 0.4}]
    assert out['exports'] == [{'id': '20260101-000000-abcd', 'stage': 'done'}]


def test_status_running_studio(tmp_path, ftcli):
    w = tmp_path / 'p'
    url = ftcli.url_of(ftcli.run('serve', '--workspace', w, '--detach'))
    _seed(w)
    out = json.loads(ftcli.run('status', '--workspace', w).stdout)
    assert out['running'] is True
    assert out['url'] == url
    assert out['takes'] == [{'id': 't1', 'name': 'x', 'stage': 'cutting', 'progress': 0.4}]          # the built-in sample is not a take
    assert out['exports'] == [{'id': '20260101-000000-abcd', 'stage': 'done'}]


def test_idle_exit(tmp_path, ftcli):
    w = tmp_path / 'p'
    r = ftcli.run('serve', '--workspace', w, '--detach', '--idle-exit', '2')
    assert r.returncode == 0
    pid = server.read_server_file(paths.Workspace(w))['pid']
    fetch(ftcli.url_of(r), '/api/info')                                # the last request
    assert wait_gone(pid, 5)
    assert not (w / 'floored' / '.server.json').exists()


def test_activity_counts_requests_and_never_idles_mid_request():
    clock = [100.0]
    a = server.Activity(lambda: clock[0])
    clock[0] = 110.0
    assert a.idle_for() == 10.0
    a.begin()
    clock[0] = 500.0
    assert a.idle_for() == 0                                          # a long upload is not idle
    a.end()
    clock[0] = 503.0
    assert a.idle_for() == 3.0


def test_idle_decision_waits_for_work_to_finish():
    assert server.should_exit(7200, 7200.0, busy=False)
    assert not server.should_exit(7200, 7200.0, busy=True)           # a cutout or render is running
    assert not server.should_exit(7200, 100.0, busy=False)
    assert not server.should_exit(0, 10 ** 9, busy=False)            # 0 = never


def test_busy_sees_takes_and_exports():
    import queue
    import types
    srv = types.SimpleNamespace(pipe=types.SimpleNamespace(busy=None, q=queue.Queue()), exporter=types.SimpleNamespace(jobs={}))
    assert server.Server.busy(srv) is False
    srv.exporter.jobs['x'] = {'stage': 'rendering'}
    assert server.Server.busy(srv) is True
    srv.exporter.jobs['x'] = {'stage': 'done'}
    assert server.Server.busy(srv) is False
    srv.pipe.busy = 't'
    assert server.Server.busy(srv) is True
    srv.pipe.busy = None
    srv.pipe.q.put('t2')
    assert server.Server.busy(srv) is True


# ------------------------------------------------------------------------------------------------- local-only guards
def test_foreign_origin_refused(tmp_path, server_factory):
    srv = server_factory(tmp_path)
    body = {'takeId': 'sample', 'settings': {}, 'events': []}
    for origin in ('https://evil.example', 'null', 'http://127.0.0.1:1', 'http://localhost', 'http://127.0.0.1.evil.example'):
        r = srv.request('/api/export', 'POST', body, headers={'Origin': origin})
        assert r.status == 403, origin
    assert srv.request('/api/takes', 'POST', b'x', headers={'Origin': 'https://evil.example', 'X-Filename': 'a.mp4'}).status == 403
    assert srv.request('/api/takes/sample', 'PUT', b'{}', headers={'Origin': 'https://evil.example'}).status == 403
    assert srv.request('/api/takes/sample', 'DELETE', headers={'Origin': 'https://evil.example'}).status == 403
    assert not any(paths.Workspace(tmp_path).exports.iterdir())                    # nothing was created
    assert not any(t.name != 'sample' for t in paths.Workspace(tmp_path).takes.iterdir())


def test_own_origin_and_no_origin_allowed(tmp_path, server_factory):
    srv = server_factory(tmp_path)
    port = srv.base.rsplit(':', 1)[1]
    for origin in ('http://127.0.0.1:' + port, 'http://localhost:' + port, None):
        h = {'Origin': origin} if origin else {}
        r = srv.request('/api/export', 'POST', {'takeId': 'sample'}, headers=h)
        assert r.status == 400, origin                                  # reached the handler: it wants {settings}
    assert srv.request('/api/takes/sample', headers={'Origin': 'https://evil.example'}).status == 200      # GET: no Origin rule


def test_foreign_host_header_refused(tmp_path, server_factory):
    srv = server_factory(tmp_path)
    port = srv.base.rsplit(':', 1)[1]
    assert srv.get('/api/info', headers={'Host': 'evil.example'}).status == 403           # DNS rebinding
    assert srv.get('/', headers={'Host': 'evil.example:%s' % port}).status == 403
    assert srv.get('/api/info', headers={'Host': '127.0.0.1:1'}).status == 403
    assert srv.get('/api/info', headers={'Host': 'localhost:' + port}).status == 200
    assert srv.get('/api/info', headers={'Host': '127.0.0.1:' + port}).status == 200


def test_reveal_outside_exports_refused(tmp_path, server_factory):
    srv = server_factory(tmp_path)
    ws = paths.Workspace(tmp_path)
    outside = tmp_path / 'secret.txt'
    outside.write_text('x')
    take_file = ws.takes / 'sample.txt'
    take_file.write_text('x')
    for p in (outside, take_file, ws.exports, ws.exports / '..' / 'secret.txt', tmp_path.anchor, '', 5):
        r = srv.post_json('/api/reveal', {'path': str(p) if p != 5 else p})
        assert r.status in (400, 403), p
    r = srv.post_json('/api/reveal', {'path': str(ws.exports / 'nope' / 'a.mp4')})            # inside, but not there
    assert r.status == 404


def test_info_reads_machine_json_and_survives_garbage(tmp_path, server_factory):
    home = tmp_path / 'home'
    home.mkdir()
    (home / 'machine.json').write_text('{"renderSecPerFrame": {"1": 0.75, "2": 2.5}}', encoding='utf-8')
    srv = server_factory(tmp_path / 'a', extra_env={'FLOORED_HOME': str(home)})
    assert srv.get_json('/api/info')['estimates'] == {'renderSecPerFrame': {'1': 0.75, '2': 2.5}}
    (home / 'machine.json').write_text('{ not json', encoding='utf-8')
    assert srv.get_json('/api/info')['estimates'] == {'renderSecPerFrame': {'1': 1.3, '2': 2.7}}
    (home / 'machine.json').write_text('{"renderSecPerFrame": {"1": "fast", "2": -4}}', encoding='utf-8')
    assert srv.get_json('/api/info')['estimates'] == {'renderSecPerFrame': {'1': 1.3, '2': 2.7}}
    (home / 'machine.json').unlink()
    assert srv.get_json('/api/info')['estimates'] == {'renderSecPerFrame': {'1': 1.3, '2': 2.7}}


# ----------------------------------------------------------------------------------------------------------- --open
def test_open_command_per_platform():
    assert cli.open_command('chrome', 'http://127.0.0.1:3020/', 'win32') == ['cmd', '/c', 'start', '', 'chrome', 'http://127.0.0.1:3020/']
    assert cli.open_command('msedge', 'http://u/', 'win32')[-2:] == ['msedge', 'http://u/']
    assert cli.open_command('Google Chrome', 'http://u/', 'darwin') == ['open', '-a', 'Google Chrome', 'http://u/']
    assert cli.open_command('Microsoft Edge', 'http://u/', 'darwin') == ['open', '-a', 'Microsoft Edge', 'http://u/']


def test_open_without_chromium_prints_the_download_page(capsys):
    launched = []
    assert cli.open_in_browser('http://u/', find=lambda: None, launch=launched.append) is False
    assert capsys.readouterr().out.strip() == 'NO_CHROMIUM https://www.google.com/chrome/'
    assert launched == []


def test_open_launches_what_it_found(capsys):
    launched = []
    assert cli.open_in_browser('http://u/', find=lambda: 'msedge', launch=launched.append) is True
    assert launched and launched[0][-1] == 'http://u/' and 'msedge' in launched[0] + ['']
    assert capsys.readouterr().out == ''


def test_serve_open_on_a_running_server(tmp_path, ftcli, monkeypatch, capsys):
    w = tmp_path / 'p'
    url = ftcli.url_of(ftcli.run('serve', '--workspace', w, '--detach'))
    opened = []
    monkeypatch.setattr(cli, 'open_in_browser', lambda u, **kw: opened.append(u) or True)
    assert cli.main(['serve', '--workspace', str(w), '--open']) == 0
    assert opened == [url]
    assert 'FLOORED_URL=' + url in capsys.readouterr().out



# ---------------------------------------------------------------------- a server that is alive but does not answer
@pytest.fixture
def silent_server(tmp_path):
    """A workspace whose .server.json names a live pid (this test process) and a port where a listener accepts
    connections and never answers: what a server that is busy cutting looks like to a 2 s probe."""
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(5)
    w = tmp_path / 'p'
    ws = paths.Workspace(w).ensure()
    port = listener.getsockname()[1]
    record = {'pid': os.getpid(), 'port': port, 'url': 'http://127.0.0.1:%d/' % port, 'workspace': str(w),
              'version': '0', 'started': 'x'}
    ws.server_file.write_text(json.dumps(record), encoding='utf-8')
    yield w, record
    listener.close()


def test_serve_does_not_start_a_second_server_when_the_first_does_not_answer(silent_server, ftcli):
    w, record = silent_server
    before = (w / 'floored' / '.server.json').read_text(encoding='utf-8')
    for extra in ((), ('--detach',)):
        r = ftcli.run('serve', '--workspace', w, *extra, env={'FT_PROBE_TIMEOUT': '0.3'})
        assert r.returncode != 0, extra
        assert 'FLOORED_URL' not in r.stdout
        assert "didn't answer" in r.stderr and 'busy' in r.stderr
    assert (w / 'floored' / '.server.json').read_text(encoding='utf-8') == before
    assert not (w / 'floored' / 'server.log').exists()                     # no child was ever started


def test_stop_keeps_the_record_when_the_server_does_not_answer(silent_server, ftcli):
    w, record = silent_server
    r = ftcli.run('stop', '--workspace', w, env={'FT_PROBE_TIMEOUT': '0.3'})
    assert r.returncode != 0 and "couldn't reach" in r.stderr
    assert cli.pid_alive(os.getpid())
    assert json.loads((w / 'floored' / '.server.json').read_text(encoding='utf-8')) == record


def test_a_slow_probe_is_retried_before_the_server_is_called_stale(silent_server, monkeypatch):
    w, record = silent_server
    ws = paths.Workspace(w)
    calls = []
    answers = iter(['silent', 'silent', 'ok'])

    def fake(port, timeout=None):
        calls.append(timeout)
        a = next(answers)
        return a, ({'pid': record['pid'], 'workspace': str(w)} if a == 'ok' else None)
    monkeypatch.setattr(server, 'probe_port', fake)
    state, rec = server.probe(ws, tries=3, timeout=0.1)
    assert state == 'running' and len(calls) == 3
    answers = iter(['silent'] * 3)
    assert server.probe(ws, tries=3, timeout=0.1)[0] == 'unreachable'
    answers = iter(['closed'])
    assert server.probe(ws, tries=3, timeout=0.1)[0] == 'stale'               # refused: nothing listens, no retries


# --------------------------------------------------------------------------------------------------- proxies
def test_loopback_calls_ignore_proxy_settings(tmp_path, ftcli):
    proxy = {'HTTP_PROXY': 'http://127.0.0.1:9', 'HTTPS_PROXY': 'http://127.0.0.1:9',
             'http_proxy': 'http://127.0.0.1:9', 'https_proxy': 'http://127.0.0.1:9', 'NO_PROXY': '', 'no_proxy': ''}
    r = ftcli.run('serve', '--workspace', tmp_path / 'p', '--detach', env=proxy)
    assert r.returncode == 0, r.stderr
    url = ftcli.url_of(r)
    again = ftcli.run('serve', '--workspace', tmp_path / 'p', '--detach', env=proxy)       # reuse needs /api/info too
    assert ftcli.url_of(again) == url
    assert json.loads(ftcli.run('status', '--workspace', tmp_path / 'p', env=proxy).stdout)['url'] == url
    assert ftcli.run('stop', '--workspace', tmp_path / 'p', env=proxy).returncode == 0
    assert server.read_server_file(paths.Workspace(tmp_path / 'p')) is None


# ------------------------------------------------------------------------------------- a take that cannot be checked
def test_missing_tool_or_timeout_during_the_upload_check_fails_the_take(ws, portrait_1080, monkeypatch):
    from ft import proc
    pipe = pipeline.Pipeline(ws)
    for exc in (proc.MissingTool('ffprobe'), subprocess.TimeoutExpired('ffprobe', 30), RuntimeError('boom')):
        tid, path = pipe.begin_upload('a.mp4')
        Path(path).write_bytes(Path(portrait_1080).read_bytes())

        def boom(*a, _exc=exc, **k):
            raise _exc
        monkeypatch.setattr(pipeline, 'check_clip', boom)
        pipe.finish_upload(tid)                                          # must not raise, must not stay "queued"
        st = pipe.get(tid)['status']
        assert st['stage'] == 'error' and st['error'] == st['message']
        assert st['message'] and 'Traceback' not in st['message'] and 'boom' not in st['message']
        assert (Path(pipe.folder(tid)) / 'log.txt').read_text(encoding='utf-8').strip()
    pipe.shutdown()


def test_unreadable_take_folder_during_the_upload_check_fails_the_take(ws, portrait_1080, monkeypatch):
    pipe = pipeline.Pipeline(ws)
    tid, path = pipe.begin_upload('a.mp4')
    Path(path).write_bytes(Path(portrait_1080).read_bytes())
    real = os.listdir
    calls = []

    def listdir(p='.'):
        if os.path.normcase(str(p)) == os.path.normcase(pipe.folder(tid)) and not calls:
            calls.append(p)
            raise PermissionError('denied')
        return real(p)
    monkeypatch.setattr(pipeline.os, 'listdir', listdir)
    pipe.finish_upload(tid)
    st = pipe.get(tid)['status']
    assert calls and st['stage'] == 'error' and st['message'] and 'denied' not in st['message']
    pipe.shutdown()
