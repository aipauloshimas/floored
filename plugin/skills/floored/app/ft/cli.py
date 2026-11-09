"""Command line.

  floored.py serve  --workspace DIR [--port N] [--detach] [--open] [--idle-exit S]
  floored.py stop   --workspace DIR
  floored.py status --workspace DIR

serve  Prints one line `FLOORED_URL=http://127.0.0.1:<port>/`. A server already running for the workspace is reused
       (its URL is printed, exit 0). --port N, else the first free port from FT_PORT_BASE (default 3020) up to base + 79.
       --detach starts the server in the background (output in <workspace>/floored/server.log), waits up to 15 s for
       it to answer, prints the URL line and exits 0; on failure it prints why and exits non-zero.
       --open opens the URL in Chrome or Edge (neither installed: prints `NO_CHROMIUM https://www.google.com/chrome/`).
       --idle-exit S (default 7200): the server exits after S seconds without a request, but never while a take is
       being cut or an export is running. 0 = never.
stop   Stops this workspace's server (exit 0 also when none runs). It only kills a process that answers /api/info as a
       floored server for this workspace with the recorded pid, never an unrelated process that reused the number.
status Prints {"url", "takes": [{id, stage, progress}], "exports": [{id, stage}]} as JSON; "url" is null when no server runs.

The Claude bridge (what the skill runs for the creator; each prints one JSON line on stdout, notes and errors go to stderr):
  floored.py add     VIDEO --workspace DIR     sends the video to the studio server (started detached when none runs)
                                                 -> {"take": id, "url"}. Exit 2: no such file, or the server refused it.
  floored.py wait    --workspace DIR (--take ID | --next) [--timeout S]
                                                 waits (polling the take's files every 2 s; no server needed) until the take is
                                                 ready -> exit 0 {"take", "stage": "ready", "takeJson", "hasWords", "language",
                                                 "transcript", "warnings"}; failed -> exit 3 {"take", "stage": "error",
                                                 "message"}; S seconds (default 3600) pass -> exit 4 {"take", "stage": "timeout"}.
                                                 --next: the first take created after this command started (a browser upload).
  floored.py suggest --workspace DIR --take ID --file JSON
                                                 writes the hook suggestions into the take: {"suggestions": [1-6 strings, at
                                                 most 60 characters and 12 words], "smallSuggestions": [0-3 strings, at most 40
                                                 characters]}; "-" reads stdin -> {"ok": true, "rev": n}. Exit 2: invalid.
  floored.py retry   --workspace DIR --take ID re-queues a failed take from its first unfinished stage -> {"take", "ok": true,
                                                 "from"}. Exit 2 with the reason when it cannot (a refused, too-long clip).

Setup (ft/doctor.py; stdlib only, so it works before the Python add-ons exist):
  floored.py doctor [--json]          what is installed and what is missing -> the report; exit 0 when nothing required is missing
  floored.py doctor --install ITEM    venv, packages, rvm-model, renderer or words -> one JSON line {"id", "ok", "message"}
  floored.py doctor --gpu-check       compares the graphics card with the processor on 12 frames and records the result
Every other command answers exit 5 ("floored isn't set up yet. Ask Claude to run the setup.") when the add-ons are missing.
"""
import argparse
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from ft import doctor, paths
from ft.proc import NO_WINDOW, pid_alive  # noqa: F401  (also used by the tests)

try:
    from ft import bridge, pipeline, server
except ModuleNotFoundError as e:                                       # the Python add-ons are not installed (yet): the doctor
    if (e.name or '').split('.')[0] not in doctor.PACKAGE_MODULES:     # still works, every other command answers exit 5
        raise
    bridge = pipeline = server = None

DETACH_WAIT_S = 15
CHROME_URL = 'https://www.google.com/chrome/'


# -- processes -----------------------------------------------------------------------------------------------------
def kill_tree(pid, grace=5.0):
    """Stop a process and what it started (ffmpeg, node...). POSIX: SIGTERM to its group, SIGKILL after `grace`."""
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(pid)], capture_output=True, creationflags=NO_WINDOW)
        return
    import signal
    try:
        group = os.getpgid(pid) == pid                                 # a detached server leads its own group
    except OSError:
        return
    send = (lambda sig: os.killpg(pid, sig)) if group else (lambda sig: os.kill(pid, sig))
    try:
        send(signal.SIGTERM)
        deadline = time.time() + grace
        while time.time() < deadline and pid_alive(pid):
            time.sleep(0.1)
        if pid_alive(pid):
            send(signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


# -- opening the browser -------------------------------------------------------------------------------------------
def find_chromium():
    """'chrome' or 'msedge' (Windows: the names `start` resolves), 'Google Chrome' or 'Microsoft Edge' (macOS); None."""
    if sys.platform == 'win32':
        import winreg
        for exe, name in (('chrome.exe', 'chrome'), ('msedge.exe', 'msedge')):
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, r'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\%s' % exe):
                        return name
                except OSError:
                    pass
        roots = [os.environ.get(v) for v in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA')]
        for rel, name in ((r'Google\Chrome\Application\chrome.exe', 'chrome'), (r'Microsoft\Edge\Application\msedge.exe', 'msedge')):
            if any(r and os.path.isfile(os.path.join(r, rel)) for r in roots):
                return name
        return None
    if sys.platform == 'darwin':
        for app in ('Google Chrome', 'Microsoft Edge'):
            if any(os.path.isdir(os.path.join(base, app + '.app')) for base in ('/Applications', os.path.expanduser('~/Applications'))):
                return app
    return None


def open_command(browser, url, platform=None):
    if (platform or sys.platform) == 'darwin':
        return ['open', '-a', browser, url]
    return ['cmd', '/c', 'start', '', browser, url]


def _launch(argv):
    subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)


def open_in_browser(url, find=None, launch=None):
    """Open url in Chrome or Edge. Neither: print `NO_CHROMIUM <download page>` and return False. find and launch
    can be replaced (tests must not open a browser)."""
    browser = (find or find_chromium)()
    if not browser:
        print('NO_CHROMIUM ' + CHROME_URL, flush=True)
        return False
    try:
        (launch or _launch)(open_command(browser, url))
    except OSError as e:
        print("floored: couldn't open the browser (%s). Open %s yourself." % (e, url), file=sys.stderr, flush=True)
        return False
    return True


# -- the commands --------------------------------------------------------------------------------------------------
def spawn_detached(ws, port, idle_exit):
    """Start `floored.py serve` in the background, output appended to server.log. Returns the Popen."""
    script = os.path.join(str(paths.APP_DIR), 'floored.py')
    cmd = [sys.executable, script, 'serve', '--workspace', str(ws.project), '--idle-exit', str(idle_exit)]
    if port:
        cmd += ['--port', str(port)]
    env = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    kwargs = {}
    if os.name == 'nt':
        kwargs['creationflags'] = 0x00000008 | 0x00000200 | 0x08000000     # DETACHED_PROCESS | NEW_PROCESS_GROUP | NO_WINDOW
    else:
        kwargs['start_new_session'] = True
    ws.ensure()
    with open(str(ws.log_file), 'ab') as log:
        log.write(('\n--- %s  %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), ' '.join(cmd[2:]))).encode('utf-8', 'replace'))
        log.flush()
        return subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=env, close_fds=True, **kwargs)


def log_tail(ws, n=3):
    try:
        with open(str(ws.log_file), encoding='utf-8', errors='replace') as f:
            lines = [l.strip() for l in f.read().splitlines() if l.strip() and not l.startswith('---')]
        return ' | '.join(lines[-n:])
    except OSError:
        return ''


def start_detached(ws, port, idle_exit):
    """Returns the running server's record, or None after printing why it did not start."""
    proc = spawn_detached(ws, port, idle_exit)
    deadline = time.time() + DETACH_WAIT_S
    exited_at = None
    while time.time() < deadline:
        rec = server.find_running(ws)
        if rec:
            return rec
        if proc.poll() is not None:                                    # it may have lost a race to another start: give
            exited_at = exited_at or time.time()                       # its winner a moment to answer
            if time.time() - exited_at > 1.5:
                break
        time.sleep(0.15)
    if proc.poll() is None:
        kill_tree(proc.pid)
    why = log_tail(ws) or 'no output'
    print("floored: the server didn't start (%s). Details: %s" % (why, ws.log_file), file=sys.stderr)
    return None


def cmd_serve(args):
    ws = paths.Workspace(os.path.abspath(args.workspace))
    state, rec = server.probe(ws)
    if state == 'unreachable':                                         # alive but slow: never start a second server
        print(server.UNREACHABLE_COPY % rec['pid'], file=sys.stderr)
        return 1
    if rec is None and args.detach:
        rec = start_detached(ws, args.port, args.idle_exit)
        if rec is None:
            return 1
    if rec is not None:                                                # reuse, or the one just detached
        print('FLOORED_URL=' + local_url(rec), flush=True)
        if args.open:
            open_in_browser(local_url(rec))
        return 0
    return server.serve(ws, port=args.port, idle_exit=args.idle_exit,
                        on_ready=(lambda url: open_in_browser(url)) if args.open else None)


def cmd_stop(args):
    ws = paths.Workspace(os.path.abspath(args.workspace))
    if server.read_server_file(ws) is None:
        print('floored: no server is running for this project.')
        return 0
    state, rec = server.probe(ws)
    if state == 'unreachable':                                         # keep the record: the server may still be ours
        print("floored: couldn't reach the server (pid %d). It may be busy with a cutout or a render, so it was left "
              'running. Try again in a minute.' % rec['pid'], file=sys.stderr)
        return 1
    if state == 'running':
        kill_tree(rec['pid'])
        deadline = time.time() + 8
        while time.time() < deadline and pid_alive(rec['pid']):
            time.sleep(0.1)
        if pid_alive(rec['pid']):
            print("floored: couldn't stop the server (pid %d)." % rec['pid'], file=sys.stderr)
            return 1
        print('floored: server stopped.')
    else:
        print('floored: no server is running for this project.')
    try:
        os.remove(str(ws.server_file))
    except OSError:
        pass
    return 0


def cmd_status(args):
    ws = paths.Workspace(os.path.abspath(args.workspace))
    state, rec = server.probe(ws)
    out = {'url': None, 'takes': [], 'exports': []}
    code = 0
    if state == 'running':
        try:
            out = server.loopback_json(local_url(rec, '/api/status'))
        except (OSError, ValueError):
            pass
    elif state == 'unreachable':
        out = {'url': local_url(rec), 'takes': [], 'exports': [], 'unreachable': True}
        code = 1
    print(json.dumps(out, ensure_ascii=False))
    return code


# -- the Claude bridge --------------------------------------------------------------------------------------------
UPLOAD_TIMEOUT_S = 900                                                 # the server checks the clip before it answers


def say(obj):
    """The command's one stdout line."""
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def fail(message, code=1):
    print('floored: ' + message, file=sys.stderr, flush=True)
    return code


def ensure_server(ws):
    """The record of this workspace's server, started detached when none runs. None after printing why not."""
    state, rec = server.probe(ws)
    if state == 'unreachable':
        print(server.UNREACHABLE_COPY % rec['pid'], file=sys.stderr)
        return None
    if state == 'running':
        return rec
    return start_detached(ws, None, server.IDLE_EXIT_DEFAULT)


def local_url(rec, path='/'):
    """Where this workspace's server is: always 127.0.0.1 and the recorded port. The record's own `url` is never used
    to send anything (a tampered .server.json must not redirect the creator's video to another host)."""
    return 'http://%s:%d%s' % (server.HOST, int(rec['port']), path)


def send(rec, path, data, headers, timeout):
    """POST `data` (bytes or an open file) to the local server through the loopback opener. Returns (status, body dict);
    a connection that fails raises OSError."""
    req = urllib.request.Request(local_url(rec, path), data=data, method='POST', headers=headers)
    try:
        with server.LOOPBACK.open(req, timeout=timeout) as r:
            code, raw = r.status, r.read()
    except urllib.error.HTTPError as e:
        code, raw = e.code, e.read()
    try:
        return code, json.loads(raw.decode('utf-8', 'replace') or '{}')
    except ValueError:
        return code, {}


def post_json(rec, path, obj=None, timeout=60):
    body = json.dumps(obj if obj is not None else {}).encode('utf-8')
    return send(rec, path, body, {'Content-Type': 'application/json'}, timeout)


def upload(rec, path):
    """Stream the file to POST /api/takes (the studio's own upload), without reading it into memory."""
    with open(path, 'rb') as f:
        return send(rec, '/api/takes', f, {'Content-Type': 'application/octet-stream', 'Content-Length': str(os.path.getsize(path)),
                                           'X-Filename': urllib.parse.quote(os.path.basename(path), safe='')}, UPLOAD_TIMEOUT_S)


def server_error(status, body):
    msg = (body or {}).get('error') or 'the server answered %d' % status
    return fail(msg, 2 if 400 <= status < 500 else 1)


def cmd_add(args):
    video = os.path.abspath(args.video)
    if not os.path.isfile(video):
        return fail("can't find the video: %s" % video, 2)
    if os.path.splitext(video)[1].lower() not in pipeline.VIDEO_EXTS:       # the server refuses these before reading the body,
        return fail('Please add a video file (MP4, MOV, M4V, WebM, MKV or AVI): %s' % video, 2)    # which resets the upload
    if os.path.getsize(video) == 0:
        return fail('that file is empty: %s' % video, 2)
    if os.path.getsize(video) > server.MAX_UPLOAD:
        return fail('that file is too large (2 GB at most): %s' % video, 2)
    ws = paths.Workspace(os.path.abspath(args.workspace))
    rec = ensure_server(ws)
    if rec is None:
        return 1
    try:
        status, body = upload(rec, video)
    except (OSError, http.client.HTTPException) as e:
        return fail("couldn't send the video to the studio (%s)." % e)
    if status != 200 or not body.get('id'):
        return server_error(status, body)
    say({'take': body['id'], 'url': local_url(rec) + '#/processing/' + urllib.parse.quote(body['id'], safe='')})
    return 0


def cmd_wait(args):
    ws = paths.Workspace(os.path.abspath(args.workspace))
    takes = str(ws.takes)
    if args.take:
        if not bridge.valid_take_id(args.take) or not os.path.isdir(os.path.join(takes, args.take)):
            return fail('no such take: %s' % args.take, 2)
        wait = dict(take=args.take)
    else:
        wait = dict(next_take=bridge.NextTake(takes))
    try:
        poll = float(os.environ.get('FT_WAIT_POLL') or bridge.POLL_S)
    except ValueError:
        poll = bridge.POLL_S
    code, result = bridge.wait_for_take(takes, timeout=args.timeout, poll=poll, progress=bridge.log_progress, **wait)
    say(result)
    return code


def cmd_suggest(args):
    try:
        if args.file == '-':
            raw = sys.stdin.buffer.read()
        else:
            with open(args.file, 'rb') as f:
                raw = f.read()
        data = json.loads(raw.decode('utf-8-sig'))
    except OSError as e:
        return fail("can't read %s (%s)." % (args.file, e.strerror or e), 2)
    except ValueError as e:
        return fail('%s is not valid JSON (%s).' % (args.file, e), 2)
    try:
        clean = bridge.validate_suggestions(data)
    except bridge.BridgeError as e:
        return fail(str(e), 2)
    if not bridge.valid_take_id(args.take):
        return fail('no such take: %s' % args.take, 2)
    ws = paths.Workspace(os.path.abspath(args.workspace))
    rec = ensure_server(ws)
    if rec is None:
        return 1
    try:
        status, body = post_json(rec, '/api/takes/%s/suggestions' % urllib.parse.quote(args.take, safe=''), clean)
    except OSError as e:
        return fail("couldn't reach the studio (%s)." % e)
    if status != 200:
        return server_error(status, body)
    say({'ok': True, 'rev': body.get('rev')})
    return 0


def cmd_retry(args):
    if not bridge.valid_take_id(args.take):
        return fail('no such take: %s' % args.take, 2)
    ws = paths.Workspace(os.path.abspath(args.workspace))
    rec = ensure_server(ws)
    if rec is None:
        return 1
    try:
        status, body = post_json(rec, '/api/takes/%s/retry' % urllib.parse.quote(args.take, safe=''))
    except OSError as e:
        return fail("couldn't reach the studio (%s)." % e)
    if status != 200:
        return server_error(status, body)
    say({'take': args.take, 'ok': True, 'from': body.get('from')})
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if server is None and argv[:1] != ['doctor']:
        print(doctor.NOT_SET_UP, file=sys.stderr, flush=True)
        return 5
    ap = argparse.ArgumentParser(prog='floored', description='floored')
    sub = ap.add_subparsers(dest='command', required=True)
    sv = sub.add_parser('serve', help='run the studio server')
    sv.add_argument('--workspace', required=True, help='the project folder; takes and exports go in its floored/ folder')
    sv.add_argument('--port', type=int, default=None, help='default: the first free port from FT_PORT_BASE (3020)')
    sv.add_argument('--detach', action='store_true', help='run in the background; print the URL line and exit')
    sv.add_argument('--open', action='store_true', help='open the studio in Chrome or Edge')
    sv.add_argument('--idle-exit', type=int, default=server.IDLE_EXIT_DEFAULT if server else 7200, metavar='S',
                    help='exit after S seconds without a request and no take or export in progress (0 = never)')
    for name, text in (('stop', "stop this project's server"), ('status', "print this project's takes and exports as JSON")):
        p = sub.add_parser(name, help=text)
        p.add_argument('--workspace', required=True)
    ad = sub.add_parser('add', help='send a video to the studio -> {"take", "url"}')
    ad.add_argument('video')
    ad.add_argument('--workspace', required=True)
    wt = sub.add_parser('wait', help='wait until a take is ready (reads files; no server needed)')
    wt.add_argument('--workspace', required=True)
    which = wt.add_mutually_exclusive_group(required=True)
    which.add_argument('--take', help='the take id')
    which.add_argument('--next', action='store_true', help='the first take created after this command started')
    wt.add_argument('--timeout', type=float, default=3600, metavar='S', help='give up after S seconds (default 3600; exit 4)')
    sg = sub.add_parser('suggest', help='write hook suggestions into a take')
    sg.add_argument('--workspace', required=True)
    sg.add_argument('--take', required=True)
    sg.add_argument('--file', required=True, help='JSON {"suggestions": [...], "smallSuggestions": [...]}; - reads stdin')
    rt = sub.add_parser('retry', help='re-queue a failed take from its first unfinished stage')
    rt.add_argument('--workspace', required=True)
    rt.add_argument('--take', required=True)
    dr = sub.add_parser('doctor', help='check what floored needs and install what is missing')
    dr.add_argument('--json', action='store_true', help='print the report as JSON')
    dr.add_argument('--install', metavar='ITEM', help='install one item: venv, packages, rvm-model, renderer or words')
    dr.add_argument('--gpu-check', action='store_true', help='check whether the graphics card gives identical cutouts')
    args = ap.parse_args(argv)
    if args.command == 'doctor':
        return doctor.main(args)
    return {'serve': cmd_serve, 'stop': cmd_stop, 'status': cmd_status, 'add': cmd_add, 'wait': cmd_wait,
            'suggest': cmd_suggest, 'retry': cmd_retry}[args.command](args)


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
