"""CI check: the studio server starts in a fresh workspace and prints its URL within 60 s.

If it doesn't, every thread's Python stack is dumped (faulthandler on SIGABRT, POSIX) so the log shows where it waits.
Usage: python dev/ci/server_smoke.py"""
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FLOORED = ROOT / 'plugin' / 'skills' / 'floored' / 'app' / 'floored.py'
WAIT_S = 60


def main():
    tmp = Path(tempfile.mkdtemp(prefix='ft-smoke-'))
    env = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1', PYTHONFAULTHANDLER='1',
               FLOORED_HOME=str(tmp / 'home'), FT_PORT_BASE='51200')
    cmd = [sys.executable, str(FLOORED), 'serve', '--workspace', str(tmp / 'project'), '--idle-exit', '0']
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env,
                         text=True, encoding='utf-8', errors='replace')
    lines, ready = [], threading.Event()

    def read():
        for line in p.stdout:
            lines.append(line.rstrip())
            print('[%5.1fs] %s' % (time.time() - t0, line.rstrip()), flush=True)
            if line.startswith('FLOORED_URL='):
                ready.set()
    threading.Thread(target=read, daemon=True).start()
    ok = ready.wait(WAIT_S)
    if not ok and p.poll() is None and os.name != 'nt':
        print('no URL after %d s: dumping the stacks' % WAIT_S, flush=True)
        p.send_signal(signal.SIGABRT)
        time.sleep(3)
    if p.poll() is None:
        p.kill()
    p.wait(timeout=10)
    time.sleep(0.5)
    print('server_smoke: %s after %.1f s (exit %s)' % ('ready' if ok else 'NOT READY', time.time() - t0, p.returncode))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
