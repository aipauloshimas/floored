"""ft.proc.run_lines: a real deadline (a timer that kills the process tree), even when the program prints nothing."""
import sys
import time

from ft import proc

SLEEPER = 'import time\ntime.sleep(60)\n'
FAMILY = ('import subprocess, sys, time\n'
          'c = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])\n'
          'print(c.pid, flush=True)\n'
          'time.sleep(60)\n')


def test_run_lines_deadline_kills_a_silent_process():
    t0 = time.time()
    code, tail = proc.run_lines([sys.executable, '-c', SLEEPER], lambda line: None, timeout=1.5)
    assert time.time() - t0 < 20                          # it returned long before the sleeper's 60 s
    assert code != 0 and tail[-1] == 'timed out'


def test_run_lines_deadline_kills_the_children_too():
    seen = []
    code, tail = proc.run_lines([sys.executable, '-c', FAMILY], seen.append, timeout=2.5)
    assert code != 0 and tail[-1] == 'timed out'
    child = int(seen[0])
    for _ in range(50):                                   # the whole tree goes, not only the parent
        if not proc.pid_alive(child):
            break
        time.sleep(0.1)
    assert not proc.pid_alive(child)


def test_run_lines_still_relays_lines_and_exit_code():
    got = []
    code, tail = proc.run_lines([sys.executable, '-c', 'print("a"); print("b"); raise SystemExit(3)'], got.append, timeout=30)
    assert (code, got, tail) == (3, ['a', 'b'], ['a', 'b'])
