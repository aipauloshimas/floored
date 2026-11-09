"""Running other programs: argument lists only (never a shell string), no console window on Windows."""
import json
import os
import shutil
import subprocess
import threading

from ft import paths

NO_WINDOW = 0x08000000 if os.name == 'nt' else 0


class MissingTool(Exception):
    """A program the studio needs (ffmpeg, node...) is not installed."""

    def __init__(self, name):
        super().__init__('%s is not installed.' % name)
        self.name = name


def pid_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = wintypes.HANDLE
        handle = k32.OpenProcess(0x1000, False, pid)                  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            return bool(k32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259     # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def run(cmd, timeout=None, env=None):
    """Run an argument list, return (code, stdout, stderr)."""
    p = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout,
                       env=env, creationflags=NO_WINDOW)
    return p.returncode, p.stdout, p.stderr


def kill_tree(p):
    """Kill a process we started and everything it started (npm, ffmpeg, a browser...). Never by name: by PID only."""
    if p.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)], capture_output=True, creationflags=NO_WINDOW)
    else:
        import signal
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except OSError:
            pass
    try:
        p.kill()                                           # the parent itself, if the tree kill missed it
    except OSError:
        pass


def run_lines(cmd, on_line, env=None, timeout=None):
    """Run cmd, feed every output line (stdout + stderr merged) to on_line; return (code, last 40 lines).
    `timeout` is a real deadline: a timer kills the whole process tree, so a program that prints nothing is stopped too
    (its last line is then 'timed out')."""
    extra = {} if os.name == 'nt' else {'start_new_session': True}      # its own group, so the POSIX kill gets the children
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                         errors='replace', env=env, creationflags=NO_WINDOW, **extra)
    timed_out = []
    timer = None
    if timeout:
        def expire():
            timed_out.append(True)
            kill_tree(p)
        timer = threading.Timer(timeout, expire)
        timer.daemon = True
        timer.start()
    tail = []
    try:
        for line in p.stdout:
            line = line.rstrip()
            if not line:
                continue
            tail.append(line)
            del tail[:-40]
            on_line(line)
    finally:
        if timer:
            timer.cancel()
        p.stdout.close()
        p.wait()
    if timed_out:
        tail.append('timed out')
    return p.returncode, tail


def tool(name):
    """Absolute path of a program: `config.json["tools"][name]` in the user folder, else PATH, else MissingTool."""
    try:
        with open(paths.user_dir() / 'config.json', encoding='utf-8') as f:
            configured = (json.load(f).get('tools') or {}).get(name)
    except (OSError, ValueError, AttributeError):
        configured = None
    if configured and os.path.isfile(configured):
        return str(configured)
    found = shutil.which(name)
    if found:
        return found
    raise MissingTool(name)
