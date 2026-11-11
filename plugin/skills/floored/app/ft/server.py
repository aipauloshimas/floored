"""floored: local server (static files + API), bound to 127.0.0.1 only (never another interface).

  python app/floored.py serve --workspace DIR [--port N] [--detach] [--open] [--idle-exit S]   (see ft/cli.py)

Local only, and safe from web pages the creator visits: every request needs a `Host` of 127.0.0.1:<port> or
localhost:<port> (DNS rebinding), and a POST/PUT/DELETE/PATCH that carries an `Origin` header must carry our own
(a page on another site cannot post to localhost). No `Origin` header (curl, the command line) is fine. One `guard()`
does both, for every method.

Static:  /  and /<file> -> app/web/      /takes/<id>/<file> -> <workspace>/takes/ (the sample: app/sample/, read only)
         /exports/<id>/<file> -> <workspace>/exports/
API (app/SPEC.md "Server API"):
  GET  /api/takes              [{take, status}] newest first, sample last
  POST /api/takes              raw body = the video, header X-Filename -> {id}; the pipeline starts
  GET  /api/takes/<id>         {take, status}
  POST /api/export             {takeId, settings, events} -> {id}
  GET  /api/exports/<id>       {stage, progress, message, file, path}
  POST /api/reveal             {path} -> opens the folder with the file selected (only inside the workspace's exports)
  GET|PUT /api/prefs           {lastLook, brand, small, looks}; PUT takes a patch of lastLook / brand / small (user folder)
  GET  /api/looks              [{id, name, settings, created}]      POST /api/looks {name, settings} -> {id}
  DELETE /api/looks/<id>       -> {ok}
  GET|PUT /api/takes/<id>/settings   the take's studio settings, one JSON object (<workspace>/settings/<id>.json; the
                               sample's too: app/sample/ is never written)
  POST /api/takes/<id>/suggestions   {suggestions, smallSuggestions} -> {ok, rev}; stored in
                               <workspace>/settings/<id>.suggestions.json, rev + 1 each time. GET /api/takes/<id> (and the
                               list) merge suggestions, smallSuggestions and suggestionsRev into `take` (the workspace's win)
  POST /api/takes/<id>/retry   re-queue a failed take from its first unfinished stage -> {ok, from}; 404 / 409 / 422 {error}
  GET  /api/info               {version, workspace, pid, estimates: {renderSecPerFrame: {"1", "2"}}}
  GET  /api/status             {running, url, takes: [{id, name, stage, progress}], exports: [{id, stage}]}
Errors are JSON {error} with a 4xx/5xx status.
"""
import email.utils
import http.client as http_client
import json
import os
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from ft import bridge, export, paths, pipeline
from ft.prefs import Prefs, PrefsError
from ft.proc import pid_alive

HOST = '127.0.0.1'
WEB = str(paths.WEB_DIR)
PORT_BASE_DEFAULT = 3020
PORT_SPAN = 80                              # --port not given: the first free one from FT_PORT_BASE to base + 79
IDLE_EXIT_DEFAULT = 7200
DEFAULT_RENDER_SEC_PER_FRAME = export.DEFAULT_RENDER_SEC_PER_FRAME   # wall-clock s per frame (Task 2: ~31 s and ~65 s per video second at 24 fps)
MAX_UPLOAD = 2 * 1024 ** 3
MAX_JSON = 8 * 1024 ** 2
CHUNK = 256 * 1024

MIME = {
    '.html': 'text/html; charset=utf-8', '.htm': 'text/html; charset=utf-8',
    '.js': 'text/javascript; charset=utf-8', '.mjs': 'text/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8',
    '.txt': 'text/plain; charset=utf-8', '.log': 'text/plain; charset=utf-8', '.md': 'text/plain; charset=utf-8',
    '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf', '.otf': 'font/otf',
    '.webm': 'video/webm', '.mp4': 'video/mp4', '.m4v': 'video/mp4', '.mov': 'video/quicktime',
    '.m4a': 'audio/mp4', '.wav': 'audio/wav', '.mp3': 'audio/mpeg',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png', '.gif': 'image/gif', '.webp': 'image/webp',
    '.svg': 'image/svg+xml', '.ico': 'image/x-icon',
}
PLACEHOLDER = b"""<!doctype html><meta charset="utf-8"><title>floored</title>
<body style="font:16px system-ui;margin:48px;color:#222"><h1>floored server is running</h1>
<p>The studio page (<code>app/web/index.html</code>) has not been built yet.</p>
<p>API: <a href="/api/takes">/api/takes</a></p></body>"""
BENIGN = (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)
UNSAFE_METHODS = ('POST', 'PUT', 'DELETE', 'PATCH')


def _plugin_version():
    try:
        with open(paths.PLUGIN_JSON, encoding='utf-8') as f:
            return str(json.load(f)['version'])
    except (OSError, ValueError, KeyError, TypeError):
        return '0.0.0'


VERSION = _plugin_version()                 # read once: the plugin's own version


# -- who is running ------------------------------------------------------------------------------------------------
def same_path(a, b):
    return os.path.normcase(os.path.realpath(str(a))) == os.path.normcase(os.path.realpath(str(b)))


def read_server_file(ws):
    """The workspace's .server.json as a dict, or None (absent, unreadable, or not an object)."""
    rec = pipeline.read_json(str(ws.server_file))
    return rec if isinstance(rec, dict) else None


# every call to our own server goes through this opener: system and environment proxies must never see loopback traffic
LOOPBACK = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PROBE_TRIES = 3
PROBE_TIMEOUT = 3.0                         # seconds per try; FT_PROBE_TIMEOUT overrides it (tests)
UNREACHABLE_COPY = ("floored: a server for this project is running (pid %d) but didn't answer. It may be busy with a "
                    'cutout or a render. Wait a minute and try again; nothing was changed.')


def probe_port(port, timeout=2.0):
    """Ask whatever listens on 127.0.0.1:<port> for /api/info. Returns (state, info):
    'ok' (info is the dict), 'closed' (connection refused: nobody listens), 'silent' (connected, but no usable answer
    in time: possibly a busy server), 'foreign' (answered, but not like our server)."""
    try:
        with LOOPBACK.open('http://%s:%d/api/info' % (HOST, int(port)), timeout=timeout) as r:
            info = json.loads(r.read().decode('utf-8'))
    except urllib.error.HTTPError:
        return 'foreign', None
    except (ValueError, UnicodeDecodeError):
        return 'foreign', None
    except urllib.error.URLError as e:
        return ('closed' if isinstance(e.reason, ConnectionRefusedError) else 'silent'), None
    except ConnectionRefusedError:
        return 'closed', None
    except (OSError, http_client.HTTPException):          # timeouts, resets, half answers
        return 'silent', None
    return ('ok', info) if isinstance(info, dict) else ('foreign', None)


def fetch_info(port, timeout=2.0):
    """The /api/info dict of our server on that port, else None."""
    state, info = probe_port(port, timeout)
    return info if state == 'ok' else None


def _probe_timeout():
    try:
        return float(os.environ.get('FT_PROBE_TIMEOUT') or PROBE_TIMEOUT)
    except ValueError:
        return PROBE_TIMEOUT


def probe(ws, tries=None, timeout=None):
    """Is a floored server running for this workspace? Returns (state, record):
      'running'      the record's port answers /api/info with this workspace and the recorded pid
      'unreachable'  the recorded pid is alive and its port is open but gives no answer after `tries` tries (a server
                     busy with a cutout can be slow): it may well be ours, so callers must neither start a second
                     server nor delete the record
      'stale'        no record, the pid is gone, nothing listens on the port, or something else answers there"""
    rec = read_server_file(ws)
    if not rec or not isinstance(rec.get('port'), int) or not isinstance(rec.get('pid'), int):
        return 'stale', None
    if not pid_alive(rec['pid']):
        return 'stale', None
    tries = tries or PROBE_TRIES
    timeout = timeout or _probe_timeout()
    for _ in range(tries):
        state, info = probe_port(rec['port'], timeout)
        if state == 'ok':
            if info.get('pid') == rec['pid'] and same_path(info.get('workspace') or '', ws.project):
                return 'running', rec
            return 'stale', None
        if state != 'silent':
            return 'stale', None
    return 'unreachable', rec


def find_running(ws):
    """The record of a verified live server for this workspace, else None. One quick look (use probe() to decide)."""
    rec = read_server_file(ws)
    if not rec or not isinstance(rec.get('port'), int) or not isinstance(rec.get('pid'), int):
        return None
    info = fetch_info(rec['port'])
    if info and info.get('pid') == rec['pid'] and same_path(info.get('workspace') or '', ws.project):
        return rec
    return None


def loopback_json(url, timeout=10):
    with LOOPBACK.open(url, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8'))


def render_estimates():
    """machine.json["renderSecPerFrame"] per tier ("1", "2"); 1.3 and 2.7 when absent, unreadable or not a positive number."""
    stored = pipeline.read_json(str(pipeline.machine_file()), {})
    stored = stored.get('renderSecPerFrame') if isinstance(stored, dict) else None
    out = dict(DEFAULT_RENDER_SEC_PER_FRAME)
    if isinstance(stored, dict):
        for tier in out:
            v = stored.get(tier)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                out[tier] = float(v)
    return out


# -- idle ----------------------------------------------------------------------------------------------------------
class Activity:
    """When the last HTTP request ended, and how many are in flight (a long upload is never idle)."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.lock = threading.Lock()
        self.inflight = 0
        self.last = clock()

    def begin(self):
        with self.lock:
            self.inflight += 1

    def end(self):
        with self.lock:
            self.inflight = max(0, self.inflight - 1)
            self.last = self.clock()

    def idle_for(self):
        with self.lock:
            return 0.0 if self.inflight else self.clock() - self.last


def should_exit(idle_exit, idle_for, busy):
    """Exit after `idle_exit` seconds without a request, but never while a take or an export is in progress.
    idle_exit 0 turns it off."""
    return bool(idle_exit) and idle_for >= idle_exit and not busy


class Server(ThreadingHTTPServer):
    daemon_threads = True
    # Windows lets a second process share a port when SO_REUSEADDR is set: keep the address exclusive instead
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        if os.name == 'nt' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        # HTTPServer.server_bind also asks socket.getfqdn(host), a reverse DNS lookup that can take many seconds on a Mac
        # (35 s on GitHub's macOS runners). The name is never used: bind the TCP socket and keep the address as it is.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]

    ws = None
    url = None
    activity = None

    def busy(self):
        """A take is being cut (or waits for its turn) or an export is running: the server must stay up."""
        if self.pipe.busy or self.pipe.q.qsize():
            return True
        return any(j.get('stage') not in ('done', 'error') for j in list(self.exporter.jobs.values()))

    def info(self):
        return {'version': VERSION, 'workspace': os.path.realpath(str(self.ws.project)), 'pid': os.getpid(),
                'estimates': {'renderSecPerFrame': render_estimates()}}

    def status(self):
        return {'running': True, 'url': self.url, 'takes': pipeline.take_summaries(self.pipe.list()),
                'exports': export.export_summaries(self.exports_dir, self.exporter.status)}

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], BENIGN):        # the browser closed a video request mid-way: normal
            return
        super().handle_error(request, client_address)


class TooLarge(Exception):
    """The upload went past MAX_UPLOAD."""


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'floored/0.1'
    timeout = 120                                        # seconds without a byte: a stalled body aborts the request, not a thread

    def log_message(self, fmt, *args):                   # static files are noise; API calls are worth a line
        if self.path.startswith('/api/'):
            sys.stderr.write('%s %s -> %s\n' % (time.strftime('%H:%M:%S'), self.requestline, args[1] if len(args) > 1 else ''))

    _begun = False

    def handle_one_request(self):
        self._begun = False
        try:
            super().handle_one_request()
        finally:
            if self._begun:
                self.server.activity.end()

    def guard(self):
        """Count the request as activity, then refuse what a web page on another site could send (see the module
        docstring). Returns False after answering 403. Every do_* method starts with this."""
        self.server.activity.begin()
        self._begun = True
        port = self.server.server_address[1]
        host = self.headers.get('Host')
        if host is not None and host.strip().lower() not in ('127.0.0.1:%d' % port, 'localhost:%d' % port):
            self.fail(403, 'This server only answers on 127.0.0.1.', close=True)
            return False
        origin = self.headers.get('Origin')
        if self.command in UNSAFE_METHODS and origin is not None and \
                origin.strip().lower() not in ('http://127.0.0.1:%d' % port, 'http://localhost:%d' % port):
            self.fail(403, 'Requests from other sites are not allowed.', close=True)
            return False
        return True

    # -- replies ---------------------------------------------------------------------------------------------
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def fail(self, code, message, close=False):
        if close:                                        # the request body was not read: the connection is unusable
            self.close_connection = True
        self.send_json({'error': message}, code)

    # -- routing ---------------------------------------------------------------------------------------------
    def do_GET(self):
        if not self.guard():
            return
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith('/api/'):
            return self.api_get(path)
        self.static(path)

    do_HEAD = do_GET

    def do_POST(self):
        if not self.guard():
            return
        path = urllib.parse.urlsplit(self.path).path
        if path == '/api/takes':
            return self.post_take()
        if path == '/api/export':
            return self.post_export()
        if path == '/api/reveal':
            return self.post_reveal()
        if path == '/api/looks':
            return self.post_look()
        parts = self.api_parts()
        if len(parts) == 3 and parts[0] == 'takes' and parts[2] == 'suggestions':
            return self.post_suggestions(parts[1])
        if len(parts) == 3 and parts[0] == 'takes' and parts[2] == 'retry':
            return self.post_retry(parts[1])
        self.fail(404 if path.startswith('/api/') else 405, 'No such endpoint.', close=True)

    def do_PUT(self):
        if not self.guard():
            return
        parts = self.api_parts()
        if parts == ['prefs']:
            return self.put_prefs()
        if len(parts) == 3 and parts[0] == 'takes' and parts[2] == 'settings':
            return self.put_take_settings(parts[1])
        self.fail(404 if parts else 405, 'No such endpoint.' if parts else 'Method not allowed.', close=True)

    def do_DELETE(self):
        if not self.guard():
            return
        parts = self.api_parts()
        if len(parts) == 2 and parts[0] == 'looks':
            if self.server.prefs.delete_look(parts[1]):
                return self.send_json({'ok': True})
            return self.fail(404, 'No such look.')
        self.fail(404 if parts else 405, 'No such endpoint.' if parts else 'Method not allowed.', close=True)

    def do_PATCH(self):
        if not self.guard():
            return
        self.fail(405, 'Method not allowed.', close=True)

    def api_parts(self):
        """The /api/ path as a list of decoded segments, or [] for a path outside /api/."""
        path = urllib.parse.urlsplit(self.path).path
        if not path.startswith('/api/'):
            return []
        return [urllib.parse.unquote(p) for p in path.split('/')[2:] if p]

    def do_OPTIONS(self):
        if not self.guard():
            return
        self.send_response(204)
        self.send_header('Allow', 'GET, HEAD, POST, PUT, DELETE')
        self.send_header('Content-Length', '0')
        self.end_headers()

    # -- API: GET --------------------------------------------------------------------------------------------
    def api_get(self, path):
        pipe, exporter = self.server.pipe, self.server.exporter
        parts = [urllib.parse.unquote(p) for p in path.split('/')[2:] if p]
        if parts == ['info']:
            return self.send_json(self.server.info())
        if parts == ['status']:
            return self.send_json(self.server.status())
        if parts == ['takes']:
            return self.send_json([self.with_suggestions(item) for item in pipe.list()])
        if len(parts) == 2 and parts[0] == 'takes':
            item = pipe.get(parts[1])
            return self.send_json(self.with_suggestions(item)) if item else self.fail(404, 'No such take.')
        if parts == ['prefs']:
            return self.send_json(self.server.prefs.get())
        if parts == ['looks']:
            return self.send_json(self.server.prefs.get()['looks'])
        if len(parts) == 3 and parts[0] == 'takes' and parts[2] == 'settings':
            return self.get_take_settings(parts[1])
        if len(parts) == 2 and parts[0] == 'exports':
            st = exporter.status(parts[1])
            return self.send_json(st) if st else self.fail(404, 'No such export.')
        self.fail(404, 'No such endpoint.')

    # -- API: POST -------------------------------------------------------------------------------------------
    def read_json_body(self):
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_JSON:
            self.fail(400 if n <= 0 else 413, 'Send a JSON body.' if n <= 0 else 'That body is too large.', close=True)
            return None
        raw = self.rfile.read(n)
        try:
            data = json.loads(raw.decode('utf-8'))
        except (ValueError, RecursionError):             # RecursionError: a body nested thousands of levels deep
            self.fail(400, 'The body is not valid JSON.')
            return None
        if not isinstance(data, dict):
            self.fail(400, 'The body must be a JSON object.')
            return None
        return data

    def body_chunks(self):
        """Yield the request body: Content-Length, or chunked transfer encoding as a fallback."""
        if 'chunked' in (self.headers.get('Transfer-Encoding') or '').lower():
            while True:
                size = int(self.rfile.readline().split(b';')[0].strip() or b'0', 16)
                if size == 0:
                    self.rfile.readline()
                    return
                left = size
                while left:
                    buf = self.rfile.read(min(CHUNK, left))
                    if not buf:
                        raise ConnectionError('closed')
                    left -= len(buf)
                    yield buf
                self.rfile.readline()
        else:
            left = int(self.headers.get('Content-Length'))
            while left:
                buf = self.rfile.read(min(CHUNK, left))
                if not buf:
                    raise ConnectionError('closed')
                left -= len(buf)
                yield buf

    def post_take(self):
        pipe = self.server.pipe
        chunked = 'chunked' in (self.headers.get('Transfer-Encoding') or '').lower()
        try:
            n = int(self.headers.get('Content-Length') or -1)
        except ValueError:
            n = -1
        if n < 0 and not chunked:
            return self.fail(411, 'Send the video as the request body (Content-Length needed).', close=True)
        if n == 0:
            return self.fail(400, 'That file is empty.', close=True)
        if n > MAX_UPLOAD:
            return self.fail(413, 'That file is too large (2 GB at most).', close=True)
        filename = urllib.parse.unquote(self.headers.get('X-Filename') or 'clip.mp4')
        try:
            tid, path = pipe.begin_upload(filename)
        except pipeline.PipelineError as e:
            return self.fail(415, str(e), close=True)
        try:
            got = 0
            with open(path, 'wb') as f:
                for buf in self.body_chunks():
                    got += len(buf)
                    if got > MAX_UPLOAD:                 # a chunked body has no Content-Length to check up front
                        raise TooLarge()
                    f.write(buf)
            if got == 0:
                raise ValueError('empty')
        except TooLarge:
            pipe.abort_upload(tid)
            return self.fail(413, 'That file is too large (2 GB at most).', close=True)
        except (ConnectionError, OSError, ValueError):
            pipe.abort_upload(tid)
            self.close_connection = True
            try:
                self.send_json({'error': 'The upload was interrupted. Try again.'}, 400)
            except OSError:
                pass
            return
        pipe.finish_upload(tid)
        self.send_json({'id': tid})

    def post_export(self):
        data = self.read_json_body()
        if data is None:
            return
        try:
            eid = self.server.exporter.submit(data.get('takeId'), data.get('settings'), data.get('events'))
        except export.ExportError as e:
            return self.fail(e.code, str(e))
        self.send_json({'id': eid})

    def put_prefs(self):
        data = self.read_json_body()
        if data is None:
            return
        try:
            self.send_json(self.server.prefs.put(data))
        except PrefsError as e:
            self.fail(400, str(e))

    def post_look(self):
        data = self.read_json_body()
        if data is None:
            return
        try:
            self.send_json({'id': self.server.prefs.add_look(data.get('name'), data.get('settings'))})
        except PrefsError as e:
            self.fail(400, str(e))

    def take_settings_file(self, tid):
        """The settings file of an existing take (the sample too), or None. The id is checked by the pipeline's own
        take-id rule, so it can never leave the settings folder."""
        if not self.server.pipe.get(tid):
            return None
        return os.path.join(self.server.ws.settings_dir, tid + '.json')

    def get_take_settings(self, tid):
        f = self.take_settings_file(tid)
        if f is None:
            return self.fail(404, 'No such take.')
        data = pipeline.read_json(f, {})
        self.send_json(data if isinstance(data, dict) else {})

    def put_take_settings(self, tid):
        data = self.read_json_body()
        if data is None:
            return
        f = self.take_settings_file(tid)
        if f is None:
            return self.fail(404, 'No such take.')
        with self.server.settings_lock:
            os.makedirs(os.path.dirname(f), exist_ok=True)
            pipeline.write_json(f, data)
        self.send_json({'ok': True})

    def suggestions_file(self, tid):
        return os.path.join(str(self.server.ws.settings_dir), tid + '.suggestions.json')

    def with_suggestions(self, item):
        """The take with Claude's suggestions merged in: the workspace file wins over the take.json's own (the sample's).
        suggestionsRev counts the writes (0 = none yet), so the studio can tell when new ones arrived."""
        take = item['take']
        take['suggestionsRev'] = 0
        if not bridge.valid_take_id(take.get('id')):
            return item
        rec = pipeline.read_json(self.suggestions_file(take['id']), None)
        if isinstance(rec, dict) and isinstance(rec.get('suggestions'), list):
            take['suggestions'] = rec['suggestions']
            take['smallSuggestions'] = rec.get('smallSuggestions') if isinstance(rec.get('smallSuggestions'), list) else []
            take['suggestionsRev'] = rec['rev'] if isinstance(rec.get('rev'), int) else 1
        return item

    def post_suggestions(self, tid):
        data = self.read_json_body()
        if data is None:
            return
        try:
            clean = bridge.validate_suggestions(data)
        except bridge.BridgeError as e:
            return self.fail(400, str(e))
        if not self.server.pipe.get(tid):
            return self.fail(404, 'No such take.')
        f = self.suggestions_file(tid)
        with self.server.settings_lock:
            old = pipeline.read_json(f, {})
            rev = (old.get('rev') if isinstance(old, dict) and isinstance(old.get('rev'), int) else 0) + 1
            os.makedirs(os.path.dirname(f), exist_ok=True)
            pipeline.write_json(f, dict(clean, rev=rev))
        self.send_json({'ok': True, 'rev': rev})

    def post_retry(self, tid):
        try:                                                           # the body is not used: read it off the connection
            self.rfile.read(min(int(self.headers.get('Content-Length') or 0), MAX_JSON))
        except ValueError:
            self.close_connection = True
        try:
            stage = self.server.pipe.retry(tid)
        except pipeline.RetryError as e:
            return self.fail(e.code, str(e))
        self.send_json({'ok': True, 'from': stage})

    def post_reveal(self):
        data = self.read_json_body()
        if data is None:
            return
        path = data.get('path')
        if not isinstance(path, str) or not path:
            return self.fail(400, 'Send {path}.')
        real, root = os.path.realpath(path), os.path.realpath(self.server.exports_dir)
        try:
            inside = os.path.commonpath([root, real]) == root and real != root
        except ValueError:                               # another drive
            inside = False
        if not inside:
            return self.fail(403, 'Only exported files can be shown.')
        if not os.path.exists(real):
            return self.fail(404, 'That file no longer exists.')
        if os.environ.get('FT_REVEAL_STUB'):            # tests only: no file manager window
            return self.send_json({'ok': True})
        try:
            if os.name == 'nt':
                # explorer wants /select,"path" as one command line (not a shell string: no shell is involved)
                subprocess.Popen('explorer /select,"%s"' % os.path.normpath(real))
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', '-R', real])
            else:
                subprocess.Popen(['xdg-open', os.path.dirname(real)])
        except OSError as e:
            return self.fail(500, "Couldn't open the folder (%s)." % e)
        self.send_json({'ok': True})

    # -- static files ----------------------------------------------------------------------------------------
    def static(self, path):
        raw = urllib.parse.unquote(path)
        if raw == '/favicon.ico':
            self.send_response(204)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        parts = [p for p in raw.split('/') if p != '']
        if any(p in ('.', '..') or p.startswith('.') or any(c in p for c in '\\:\0') for p in parts):
            return self.fail(403, 'Forbidden.')
        root = WEB
        if len(parts) >= 3 and parts[0] in ('takes', 'exports'):
            if parts[0] == 'takes':
                root = self.server.pipe.folder(parts[1])      # one take's folder; the sample's is read only
                parts = parts[2:]
            else:
                root = self.server.exports_dir
                parts = parts[1:]
        elif not parts:
            parts = ['index.html']
        root_real = os.path.realpath(root)
        full = os.path.realpath(os.path.join(root_real, *parts))
        try:
            inside = os.path.commonpath([root_real, full]) == root_real
        except ValueError:
            inside = False
        if not inside:
            return self.fail(403, 'Forbidden.')
        if not os.path.isfile(full):
            if parts == ['index.html'] and root == WEB:
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(PLACEHOLDER)))
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(PLACEHOLDER)
                return
            return self.fail(404, 'Not found.')
        self.send_file(full)

    def send_file(self, full):
        st = os.stat(full)
        size = st.st_size
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, 'application/octet-stream')
        etag = '"%x-%x"' % (st.st_mtime_ns, size)
        last_mod = email.utils.formatdate(st.st_mtime, usegmt=True)
        cache = 'no-store' if ext == '.json' else 'no-cache'
        # not modified?
        inm, ims = self.headers.get('If-None-Match'), self.headers.get('If-Modified-Since')
        if ext != '.json' and (inm == etag or (not inm and ims and self._not_newer(ims, st.st_mtime))):
            self.send_response(304)
            self.send_header('ETag', etag)
            self.send_header('Cache-Control', cache)
            self.end_headers()
            return
        start, end, code = 0, size - 1, 200
        rng = self.headers.get('Range')
        if rng and rng.startswith('bytes=') and self.headers.get('If-Range') in (None, etag, last_mod):
            spec = rng[6:].split(',')[0].strip()
            a, _, b = spec.partition('-')
            try:
                if a == '':                                  # bytes=-N : the last N bytes
                    start, end = max(0, size - int(b)), size - 1
                else:
                    start = int(a)
                    end = int(b) if b else size - 1
                    end = min(end, size - 1)
                if start > end or start >= size:
                    raise ValueError
                code = 206
            except ValueError:
                self.send_response(416)
                self.send_header('Content-Range', 'bytes */%d' % size)
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
        length = end - start + 1
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(length))
        self.send_header('Accept-Ranges', 'bytes')
        if code == 206:
            self.send_header('Content-Range', 'bytes %d-%d/%d' % (start, end, size))
        self.send_header('ETag', etag)
        self.send_header('Last-Modified', last_mod)
        self.send_header('Cache-Control', cache)
        self.end_headers()
        if self.command == 'HEAD':
            return
        with open(full, 'rb') as f:
            f.seek(start)
            left = length
            while left:
                buf = f.read(min(CHUNK, left))
                if not buf:
                    break
                self.wfile.write(buf)
                left -= len(buf)

    @staticmethod
    def _not_newer(ims, mtime):
        try:
            return email.utils.parsedate_to_datetime(ims).timestamp() >= int(mtime)
        except (TypeError, ValueError):
            return False


def bind(port=None):
    """The server socket: `port`, or the first free port from FT_PORT_BASE (default 3020) up to base + 79. OSError if none."""
    if port:
        return Server((HOST, int(port)), Handler)
    try:
        base = int(os.environ.get('FT_PORT_BASE') or PORT_BASE_DEFAULT)
    except ValueError:
        base = PORT_BASE_DEFAULT
    last = None
    for p in range(base, min(base + PORT_SPAN, 65536)):
        try:
            return Server((HOST, p), Handler)
        except OSError as e:
            last = e
    raise OSError('no free port from %d to %d (%s)' % (base, base + PORT_SPAN - 1, last))


def serve(ws, port=None, idle_exit=IDLE_EXIT_DEFAULT, on_ready=None):
    """Run the studio server for a workspace (a ft.paths.Workspace) until interrupted, stopped, or idle.

    port: that port, or None for the first free one from FT_PORT_BASE. Prints `FLOORED_URL=http://127.0.0.1:<port>/`
    and writes <workspace>/floored/.server.json {pid, port, url, workspace, version, started} once it listens.
    idle_exit: seconds. The server exits when no HTTP request has arrived for that long AND no take is being cut and no
    export is running (it never exits in the middle of a cutout or a render). 0 turns it off.
    on_ready(url) runs once the server listens (the command line opens the browser there).
    Returns 0, or 1 when no port could be bound."""
    ws.ensure()
    try:
        srv = bind(port)
    except OSError as e:
        print('floored: cannot listen on port %s (%s). Is another server using that port?' % (port or 'range', e),
              file=sys.stderr)
        return 1
    state, live = probe(ws)                                # two starts raced: the first one wins
    if state == 'running' and live['pid'] != os.getpid():
        srv.server_close()
        print('FLOORED_URL=' + live['url'], flush=True)
        return 0
    if state == 'unreachable':                             # a live but silent server owns this workspace
        srv.server_close()
        print(UNREACHABLE_COPY % live['pid'], file=sys.stderr)
        return 1
    pipe = pipeline.Pipeline(ws)
    exporter = export.Exporter(pipe, ws.exports)
    port = srv.server_address[1]
    url = 'http://%s:%d/' % (HOST, port)
    srv.pipe, srv.exporter, srv.exports_dir, srv.ws, srv.url = pipe, exporter, str(ws.exports), ws, url
    srv.activity = Activity()
    srv.prefs = Prefs(paths.user_dir())
    srv.settings_lock = threading.Lock()
    pipeline.write_json(str(ws.server_file), {
        'pid': os.getpid(), 'port': port, 'url': url, 'workspace': os.path.realpath(str(ws.project)),
        'version': VERSION, 'started': pipeline.now_iso()})
    print('FLOORED_URL=' + url, flush=True)
    print('floored server: http://%s:%d/  (workspace: %s)' % (HOST, port, ws.root), flush=True)
    stopping = threading.Event()

    def watch_idle():
        while not stopping.wait(0.5):
            if should_exit(idle_exit, srv.activity.idle_for(), srv.busy()):
                print('floored: idle for %d s, shutting down.' % idle_exit, flush=True)
                srv.shutdown()
                return

    threading.Thread(target=watch_idle, name='idle', daemon=True).start()
    if os.name != 'nt':                                    # `stop` sends SIGTERM
        signal.signal(signal.SIGTERM, lambda *_: threading.Thread(target=srv.shutdown, daemon=True).start())
    try:
        if on_ready:
            on_ready(url)
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stopping.set()
        pipe.shutdown()
        exporter.shutdown()
        srv.server_close()
        rec = read_server_file(ws)
        if rec and rec.get('pid') == os.getpid():
            try:
                os.remove(str(ws.server_file))
            except OSError:
                pass
    return 0
