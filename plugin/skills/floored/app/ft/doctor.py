"""floored doctor: checks what the studio needs and installs what it can, with the creator's consent (Claude asks first).

  floored.py doctor [--json]          the report below; exit 0 when every required item is fine, else 1
  floored.py doctor --install ITEM    install one item (python, ffmpeg, node, venv, packages, rvm-model, renderer, words) -> one JSON line
  floored.py doctor --gpu-check       compare the graphics card with the processor on 12 sample frames (about a minute)

Report: {"ok", "items": [{"id", "ok", "found", "need", "mb", "how": "auto"|"manual", "command", "note"}],
         "downloadMb", "summary"}.  Ids, in order: python, ffmpeg, node, browser, venv, packages, rvm-model, renderer,
words (optional), gpu (optional). `how` "auto": `--install ID` does it. "manual": the creator runs `command` (Claude can
run it for them); the doctor then finds the new program even when this shell's PATH is stale, and records its absolute path
in `config.json["tools"]` (read by proc.tool).

Python, ffmpeg (with ffprobe) and Node.js are "auto" too when this system has a pinned download in `tools.txt` (one line per
file: tool, system, size in bytes, SHA-256, address): `--install` downloads that file into floored's own folder
`<user dir>/tools/<tool>/`, checks size and SHA-256, unpacks it with Python's own zipfile and tarfile, starts it once to prove it
runs, and records it. No installer, no admin password, no PATH change; removing the folder removes the program. A system with no
pin (or an older one that can't be told) gets the manual answer (winget, brew or the download page) as before.

Standard library only: this module runs before the Python packages exist (every import of ft.* here is lazy and optional).
`note` and `summary` are plain English for a creator: no jargon. The ids are internal.
"""
import datetime
import glob
import hashlib
import http.client
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from ft import paths
from ft.proc import MissingTool, run, run_lines  # noqa: F401  (MissingTool re-exported for callers)

ITEM_IDS = ['python', 'ffmpeg', 'node', 'browser', 'venv', 'packages', 'rvm-model', 'renderer', 'words', 'gpu']
OPTIONAL_IDS = ('words', 'gpu')
AUTO_IDS = ('venv', 'packages', 'rvm-model', 'renderer', 'words')
TOOL_IDS = ('python', 'ffmpeg', 'node')                # also installed by floored itself, when this system has a pinned download
PACKAGE_MODULES = ('numpy', 'onnxruntime')           # what the studio imports; cli.py answers exit 5 without them
MIN_PYTHON = (3, 10)
MIN_NODE = 22
HYPERFRAMES_VERSION = '0.9.22'                       # a test keeps this equal to export.HYPERFRAMES_VERSION
WHISPER_REPO = 'Systran/faster-whisper-base'

RVM_URL = 'https://github.com/PeterL1n/RobustVideoMatting/releases/download/v1.0.0/rvm_mobilenetv3_fp32.onnx'
RVM_SHA256 = '88d4531297118f595bf2fd60f6f566aec2e559393802d1f436c380f0cbbd2828'   # the official release file, 14 975 696 bytes

# Download sizes in MB (1 MB = 1 000 000 bytes), measured 2026-11-09 on Windows 11 / Python 3.13 / Node 22 and the official
# download pages: python.org installer 27, Gyan full ffmpeg 169 (7z; winget's zip is a little bigger, so 170), Node 22 MSI 32,
# Chrome standalone installer 170, RVM 15 (14 975 696 bytes), hyperframes@0.9.22 117 on disk + its headless Chrome 282,
# numpy 12 + the onnxruntime wheel 25, the Python environment itself (pip, setuptools) 12, faster-whisper wheels 60 + model 148.
SIZES_MB = {'python': 27, 'ffmpeg': 170, 'node': 32, 'browser': 170, 'venv': 12, 'packages': 37, 'rvm-model': 15,
            'renderer': 399, 'words': 208, 'gpu': 0}
# How long the slow steps take, in minutes (the video maker: 12 min 23 s measured on Windows 11, npm prints almost nothing
# until it ends). Only these two items carry a "minutes" field; SKILL.md quotes it to the creator.
MINUTES = {'renderer': 12, 'words': 1}
LABELS = {'python': 'Python', 'ffmpeg': 'ffmpeg', 'node': 'Node.js', 'browser': 'Chrome', 'venv': 'the Python environment',
          'packages': 'the Python add-ons', 'rvm-model': 'the cutout model', 'renderer': 'the video maker',
          'words': 'the speech reader', 'gpu': 'the graphics-card check'}

# manual installs: winget id, brew formula (cask for the browser), download page
MANUAL = {
    'python': {'winget': 'Python.Python.3.12', 'brew': 'python@3.12', 'page': 'https://www.python.org/downloads/'},
    'ffmpeg': {'winget': 'Gyan.FFmpeg', 'brew': 'ffmpeg-full', 'page': 'https://www.gyan.dev/ffmpeg/builds/'},
    'node': {'winget': 'OpenJS.NodeJS.LTS', 'brew': 'node', 'page': 'https://nodejs.org/en/download'},
    'browser': {'winget': 'Google.Chrome', 'brew': 'google-chrome', 'cask': True, 'page': 'https://www.google.com/chrome/'},
}
WINGET_FLAGS = '--source winget --accept-source-agreements --accept-package-agreements --disable-interactivity'   # a fresh PC asks nothing
OWN_COPY_NOTE = 'floored downloads its own copy into its own folder; nothing else on your computer changes.'
OWN_COPY_KEEPS_YOURS = 'floored downloads its own copy into its own folder and leaves yours alone.'
MAC_PAGE = {'ffmpeg': 'https://ffmpeg.org/download.html'}
# Homebrew's plain `ffmpeg` has no zscale; `ffmpeg-full` has it but is keg-only, so it is never on PATH (Apple silicon, Intel).
FULL_FFMPEG_DIRS = ['/opt/homebrew/opt/ffmpeg-full/bin', '/usr/local/opt/ffmpeg-full/bin']
NOT_SET_UP = "floored isn't set up yet. Ask Claude to run the setup."


class DoctorError(Exception):
    """An install step failed; the message is for the creator."""


def log(text):
    print(text, file=sys.stderr, flush=True)


# -- small helpers -------------------------------------------------------------------------------------------------
def which(name, path=None):
    return shutil.which(name, path=path)


def _capture(cmd, timeout=60, env=None):
    """(exit code, stdout) of an argument list; (None, '') when it can't run at all."""
    try:
        code, out, _ = run(cmd, timeout=timeout, env=env)
        return code, out
    except (OSError, subprocess.SubprocessError):
        return None, ''


def _win():
    return sys.platform == 'win32'


def _mac():
    return sys.platform == 'darwin'


def _which_in(folder, name):
    """The file `name` (with .exe/.cmd on Windows) directly inside `folder`, or None."""
    for ext in (('.exe', '.cmd', '.bat', '') if _win() else ('',)):
        candidate = os.path.join(folder, name + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


def _config_path():
    return paths.user_dir() / 'config.json'


def _read_json(path):
    try:
        with open(str(path), encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    path = paths.user_dir() / path if isinstance(path, str) else path
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    with open(str(tmp), 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(str(tmp), str(path))


def recorded_tools():
    tools = _read_json(_config_path()).get('tools')
    return dict(tools) if isinstance(tools, dict) else {}


def record_tool(name, path):
    cfg = _read_json(_config_path())
    tools = cfg.get('tools') if isinstance(cfg.get('tools'), dict) else {}
    tools[name] = str(path)
    cfg['tools'] = tools
    _write_json(_config_path(), cfg)


def forget_tool(name):
    cfg = _read_json(_config_path())
    if isinstance(cfg.get('tools'), dict) and name in cfg['tools']:
        del cfg['tools'][name]
        _write_json(_config_path(), cfg)


# -- the pinned downloads (tools.txt) ------------------------------------------------------------------------------
def tools_file():
    """tools.txt next to the app; FLOORED_TOOLS_FILE points tests at another file."""
    env = os.environ.get('FLOORED_TOOLS_FILE')
    return Path(env).expanduser() if env else paths.APP_DIR / 'tools.txt'


def read_pins():
    """{(tool, system): {"bytes", "sha256", "url"}} from tools.txt. Blank lines, # lines and malformed lines are skipped."""
    pins = {}
    try:
        with open(str(tools_file()), encoding='utf-8') as f:
            lines = f.read().splitlines()
    except OSError:
        return pins
    for line in lines:
        fields = line.split()
        if len(fields) != 5 or line.lstrip().startswith('#') or not fields[2].isdigit():
            continue
        tool, system, size, sha, url = fields
        pins.setdefault((tool, system), {'bytes': int(size), 'sha256': sha.lower(), 'url': url})     # the first line wins, as in get-python
    return pins


def system_key():
    """win-x64, darwin-arm64 or darwin-x64; None for any other system (no pinned download)."""
    machine = (platform.machine() or '').lower()
    if sys.platform == 'win32':
        return 'win-x64' if machine in ('amd64', 'x86_64') else None
    if sys.platform == 'darwin':
        return {'arm64': 'darwin-arm64', 'x86_64': 'darwin-x64'}.get(machine)
    return None


def pins_for(item_id):
    """[pin, ...] of the files an item downloads on this system (ffmpeg: ffmpeg, plus ffprobe on a Mac), or None."""
    key = system_key()
    pins = read_pins()
    names = ['ffmpeg', 'ffprobe'] if item_id == 'ffmpeg' else [item_id]
    found = [dict(pins[(name, key)], tool=name) for name in names if (name, key) in pins]
    return found if key is not None and found and found[0]['tool'] == names[0] else None


def tools_dir():
    return paths.user_dir() / 'tools'


def _own_dirs():
    """floored's own program folders, where a downloaded Python, Node.js or ffmpeg lives."""
    base = tools_dir()
    return [str(base / 'python'), str(base / 'python' / 'bin'), str(base / 'node'), str(base / 'node' / 'bin'), str(base / 'ffmpeg')]


def own_python():
    return tools_dir() / 'python' / ('python.exe' if _win() else 'bin/python3')


# -- finding programs ----------------------------------------------------------------------------------------------
def _python_folder_key(folder):
    """A folder like Python313 gives (3, 13): the newest Python first, by number (Python313 before Python39), not as text."""
    m = re.search(r'Python(\d)(\d*)$', os.path.basename(folder))
    return (int(m.group(1)), int(m.group(2) or 0)) if m else (0, 0)


def search_dirs():
    """Where an installer leaves a program that this shell's PATH does not know yet (a winget or brew install)."""
    found = _own_dirs()                          # floored's own downloaded programs come first
    if _win():
        local = os.environ.get('LOCALAPPDATA')
        program_files = [os.environ.get(v) for v in ('ProgramFiles', 'ProgramW6432')] + [r'C:\Program Files']
        if local:
            found.append(os.path.join(local, 'Microsoft', 'WinGet', 'Links'))
            found += sorted(glob.glob(os.path.join(glob.escape(local), 'Microsoft', 'WinGet', 'Packages', 'Gyan.FFmpeg*', '**', 'bin'),
                                      recursive=True))
            found += sorted(glob.glob(os.path.join(glob.escape(local), 'Programs', 'Python', 'Python3*')), key=_python_folder_key, reverse=True)
        for pf in program_files:
            if pf:
                found.append(os.path.join(pf, 'nodejs'))
                found += sorted(glob.glob(os.path.join(glob.escape(pf), 'Python3*')), key=_python_folder_key, reverse=True)
    else:
        found += FULL_FFMPEG_DIRS + ['/opt/homebrew/bin', '/usr/local/bin']
    seen, out = set(), []
    for d in found:
        key = os.path.normcase(d)
        if key not in seen:
            seen.add(key)
            out.append(d)
    return out


def find_program(name):
    """{"path", "via": "config"|"path"|"search", "stale": old recorded path or None} or None.
    Order: the recorded path (config.json["tools"]), PATH, then the installers' folders. A recorded path whose file is
    gone is reported as `stale` and replaced by what is found (or forgotten when nothing is)."""
    recorded = recorded_tools().get(name)
    stale = None
    if recorded:
        if os.path.isfile(recorded):
            return {'path': recorded, 'via': 'config', 'stale': None}
        stale = recorded
    found, via = which(name), 'path'
    if not found:
        via = 'search'
        for folder in search_dirs():
            found = _which_in(folder, name)
            if found:
                break
    if found:
        found = os.path.abspath(found)
        if via == 'search' or stale:
            record_tool(name, found)           # PATH-found programs stay on PATH; only the ones PATH misses are recorded
        return {'path': found, 'via': via, 'stale': stale}
    if stale:
        forget_tool(name)
    return None


# -- the OS command for a manual install --------------------------------------------------------------------------
def install_command(item_id):
    spec = MANUAL[item_id]
    if _win() and which('winget'):
        return 'winget install --id %s -e %s' % (spec['winget'], WINGET_FLAGS)
    if _mac() and which('brew'):
        return 'brew install --cask %s' % spec['brew'] if spec.get('cask') else 'brew install %s' % spec['brew']
    return MAC_PAGE.get(item_id, spec['page']) if _mac() else spec['page']


def _item(item_id, ok, found=None, need='', how='auto', command='', note=''):
    item = {'id': item_id, 'ok': bool(ok), 'found': found, 'need': need, 'mb': SIZES_MB[item_id],
            'how': how, 'command': command, 'note': note}
    if item_id in MINUTES:
        item['minutes'] = MINUTES[item_id]
    return item


def _manual_item(item_id, ok, found, need, note):
    return _item(item_id, ok, found, need, 'manual', '' if ok else install_command(item_id), '' if ok else note)


def _missing_item(item_id, found, need, note, found_older=False, fix=''):
    """A python, ffmpeg or node that is not there or not good enough: floored downloads its own copy when this system has a
    pin; otherwise the manual answer (command or page). `fix` is what the creator would do themselves ("Reinstall it."):
    it is said only with the manual answer, never beside "floored downloads its own copy"."""
    pins = pins_for(item_id)
    if not pins:
        return _manual_item(item_id, False, found, need, (note + ' ' + fix).strip())
    tail = OWN_COPY_KEEPS_YOURS if found_older else OWN_COPY_NOTE
    item = _item(item_id, False, found, need, 'auto', 'download ' + pins[0]['url'], note + ' ' + tail)
    item['mb'] = int(round(sum(p['bytes'] for p in pins) / 1e6))
    return item


STALE_NOTE = ' The saved location of %s was gone, so floored looked again.'


# -- the checks ----------------------------------------------------------------------------------------------------
def _version_text(version):
    return '.'.join(str(n) for n in version)


def _pythons():
    """(executable, (major, minor, micro)) candidates, this interpreter first, then the ones installers leave."""
    yield sys.executable, tuple(sys.version_info[:3])
    own = own_python()                                       # floored's own downloaded Python, right after this interpreter
    if own.is_file():
        code, out = _capture([str(own), '-c', 'import sys;print(*sys.version_info[:3])'], timeout=20)
        if code == 0 and re.fullmatch(r'\d+ \d+ \d+', out.strip()):
            yield str(own), tuple(int(n) for n in out.split())
    for name in ('python3.13', 'python3.12', 'python3.11', 'python3.10', 'python3', 'python'):
        hit = find_program(name)
        if hit:
            code, out = _capture([hit['path'], '-c', 'import sys;print(*sys.version_info[:3])'], timeout=20)
            if code == 0 and re.fullmatch(r'\d+ \d+ \d+', out.strip()):
                yield hit['path'], tuple(int(n) for n in out.split())


def find_python():
    """(executable, version tuple) of a Python 3.10 or newer, or (None, best older version tuple or None)."""
    best = None
    for exe, version in _pythons():
        if version >= MIN_PYTHON:
            return exe, version
        best = max(best or version, version)
    return None, best


def check_python():
    exe, version = find_python()
    need = 'Python 3.10 or newer'
    if exe:
        return _item('python', True, 'Python ' + _version_text(version), need, 'manual')
    note = ("Python 3.10 or newer isn't installed." if version is None
            else 'Your Python is %s, and floored needs 3.10 or newer.' % _version_text(version))
    return _missing_item('python', ('Python ' + _version_text(version)) if version else None, need, note, found_older=version is not None)


def ffmpeg_features(exe):
    """{"version", "missing": [...]} for an ffmpeg program: it needs zscale (HDR to SDR), libvpx-vp9 and libx264."""
    _, banner = _capture([exe, '-version'], timeout=30)
    m = re.search(r'version\s+(\S+)', banner)
    missing = []
    _, filters = _capture([exe, '-hide_banner', '-filters'], timeout=30)
    if not re.search(r'^\s*\S+\s+zscale\s', filters, re.M):
        missing.append('zscale')
    _, encoders = _capture([exe, '-hide_banner', '-encoders'], timeout=30)
    for encoder in ('libvpx-vp9', 'libx264'):
        if not re.search(r'^\s*\S+\s+%s\s' % re.escape(encoder), encoders, re.M):
            missing.append(encoder)
    return {'version': m.group(1) if m else None, 'missing': missing}


FFMPEG_MISSING_TEXT = {'zscale': "it can't convert HDR video", 'libvpx-vp9': "it can't write the cutout video",
                       'libx264': "it can't write the final video"}


def full_build_ffmpeg():
    """(ffmpeg, ffprobe) of a full build in a folder PATH never has (Homebrew's keg-only ffmpeg-full), or None."""
    if not _mac():
        return None
    for folder in FULL_FFMPEG_DIRS:
        exe, probe = _which_in(folder, 'ffmpeg'), _which_in(folder, 'ffprobe')
        if exe and probe and not ffmpeg_features(exe)['missing']:
            return exe, probe
    return None


def check_ffmpeg():
    need = 'ffmpeg (the full build)'
    hit = find_program('ffmpeg')
    probe = find_program('ffprobe') if hit else None
    note_tail = STALE_NOTE % 'ffmpeg' if hit and hit['stale'] else ''
    if not hit:
        return _missing_item('ffmpeg', None, need, "ffmpeg isn't installed.")
    features = ffmpeg_features(hit['path'])
    full = full_build_ffmpeg() if features['missing'] else None
    if full:                                     # the PATH one is a slim build: record the full one, it goes first
        record_tool('ffmpeg', full[0])
        record_tool('ffprobe', full[1])
        hit, probe = {'path': full[0], 'via': 'search', 'stale': None}, {'path': full[1]}
        features = ffmpeg_features(full[0])
    found = 'ffmpeg ' + (features['version'] or '')
    if features['missing']:
        return _missing_item('ffmpeg', found.strip(), need,
                             'This ffmpeg is missing parts floored needs (%s).' % ', '.join(
                                 FFMPEG_MISSING_TEXT[m] for m in features['missing']), found_older=True, fix='Install the full build.')
    if not probe:
        return _missing_item('ffmpeg', found.strip(), need, "ffprobe (it comes with ffmpeg) wasn't found.", found_older=True,
                             fix='Reinstall ffmpeg.')
    return _item('ffmpeg', True, found.strip(), need, 'manual', note=note_tail.strip())


def node_version(exe):
    code, out = _capture([exe, '--version'], timeout=20)
    m = re.match(r'v?(\d+)\.(\d+)\.(\d+)', out.strip()) if code == 0 else None
    return tuple(int(n) for n in m.groups()) if m else None


def check_node():
    need = 'Node.js 22 or newer'
    hit = find_program('node')
    if not hit:
        return _missing_item('node', None, need, "Node.js isn't installed.")
    version = node_version(hit['path'])
    if not version:
        return _missing_item('node', None, need, "Node.js is installed but doesn't start.", found_older=True, fix='Reinstall it.')
    if version[0] < MIN_NODE:
        return _missing_item('node', 'Node.js ' + _version_text(version), need,
                             'Your Node.js is %s, and floored needs 22 or newer.' % _version_text(version), found_older=True)
    npm = find_program('npm')
    if not npm:
        return _missing_item('node', 'Node.js ' + _version_text(version), need, "npm (it comes with Node.js) wasn't found.", found_older=True,
                             fix='Reinstall Node.js.')
    return _item('node', True, 'Node.js ' + _version_text(version), need, 'manual',
                 note=(STALE_NOTE % 'Node.js').strip() if hit['stale'] else '')


def check_browser():
    need = 'Google Chrome or Microsoft Edge'
    try:
        from ft import cli
        name = cli.find_chromium()
    except Exception:                                       # a broken optional import must not stop the report
        name = None
    names = {'chrome': 'Google Chrome', 'msedge': 'Microsoft Edge'}
    if name:
        return _item('browser', True, names.get(name, name), need, 'manual')
    return _manual_item('browser', False, None, need, "Neither Chrome nor Edge was found. The studio opens in one of them.")


def venv_dir():
    return paths.user_dir() / 'venv'


def venv_python():
    return venv_dir() / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def check_venv():
    need = 'a private Python environment for floored'
    py = venv_python()
    if py.is_file():
        return _item('venv', True, str(venv_dir()), need, 'auto')
    return _item('venv', False, None, need, 'auto', 'python -m venv %s' % venv_dir(), "floored keeps its Python add-ons in its own folder, so nothing else on your computer changes.")


def packages_found():
    """'numpy 2.2.6, onnxruntime 1.24.4' from the private environment, or None."""
    py = venv_python()
    if not py.is_file():
        return None
    code, out = _capture([str(py), '-c', 'import numpy, onnxruntime; print("numpy", numpy.__version__ + ",", "onnxruntime", onnxruntime.__version__)'],
                         timeout=120)
    return out.strip() if code == 0 and out.strip() else None


def check_packages():
    need = 'the Python add-ons floored uses (numbers and the cutout engine)'
    found = packages_found()
    if found:
        return _item('packages', True, found, need, 'auto')
    note = ('The Python environment comes first.' if not venv_python().is_file()
            else "The Python add-ons aren't installed in floored's environment.")
    return _item('packages', False, None, need, 'auto', '%s -m pip install -r requirements.txt' % venv_python(), note)


def sha256_file(path):
    h = hashlib.sha256()
    with open(str(path), 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def check_rvm():
    need = 'the cutout model (a 15 MB file)'
    target = paths.rvm_model_path()
    if not target.is_file():
        return _item('rvm-model', False, None, need, 'auto', 'download %s' % RVM_URL, 'The model that cuts you out of the video is downloaded once, then it works offline.')
    try:
        same = sha256_file(target) == RVM_SHA256
    except OSError:
        same = False
    if same:
        return _item('rvm-model', True, str(target), need, 'auto')
    blocked = _item('rvm-model', False, str(target), need, 'manual', '',
                    "A different file is already at %s. floored won't overwrite it: move it away, then run the setup again." % target)
    blocked['mb'] = 0                                    # nothing will be downloaded until the creator moves that file
    return blocked


def _export_or_none():
    try:
        from ft import export
        return export
    except ImportError:
        return None


def renderer_dir():
    """The folder of the local video maker. Same answer as export.renderer_dir() (a test keeps them equal); this copy
    exists because export needs the Python add-ons and the doctor runs without them."""
    export = _export_or_none()
    if export:
        return export.renderer_dir()
    env = os.environ.get('FLOORED_RENDERER_DIR')
    return os.path.abspath(os.path.expanduser(env)) if env else str(paths.user_dir() / 'renderer')


def renderer_exe():
    return os.path.join(renderer_dir(), 'node_modules', '.bin', 'hyperframes.cmd' if os.name == 'nt' else 'hyperframes')


def renderer_version():
    try:
        with open(os.path.join(renderer_dir(), 'node_modules', 'hyperframes', 'package.json'), encoding='utf-8') as f:
            return json.load(f).get('version')
    except (OSError, ValueError, AttributeError):
        return None


def _renderer_env():
    export = _export_or_none()
    if export:
        return export.renderer_env()                       # also puts the folders of the recorded node and ffmpeg on PATH
    return dict(os.environ, HYPERFRAMES_NO_TELEMETRY='1', DO_NOT_TRACK='1', HYPERFRAMES_NO_UPDATE_CHECK='1')


def browser_for_renderer():
    """The headless Chrome HyperFrames would use (it finds one or has downloaded one), or None."""
    if not os.path.isfile(renderer_exe()):
        return None
    code, out = _capture([renderer_exe(), 'browser', 'path'], timeout=60, env=_renderer_env())
    lines = [l.strip() for l in out.splitlines() if l.strip()]
    return lines[-1] if code == 0 and lines and os.path.isfile(lines[-1]) else None


def check_renderer():
    need = 'the video maker, with its built-in browser'
    version = renderer_version()
    command = 'npm install --prefix %s hyperframes@%s' % (renderer_dir(), HYPERFRAMES_VERSION)
    if version != HYPERFRAMES_VERSION:
        note = ("The video maker isn't installed yet." if version is None
                else 'The video maker is version %s, and floored needs %s.' % (version, HYPERFRAMES_VERSION))
        return _item('renderer', False, version, need, 'auto', command, note)
    if not browser_for_renderer():
        return _item('renderer', False, version, need, 'auto', 'hyperframes browser ensure',
                     "The video maker's built-in browser hasn't been downloaded yet. It is a one-time download.")
    return _item('renderer', True, version, need, 'auto')


def words_found():
    py = venv_python()
    if not py.is_file() or not (paths.user_dir() / 'models' / 'faster-whisper-base' / 'model.bin').is_file():
        return False
    code, _ = _capture([str(py), '-c', 'import faster_whisper'], timeout=60)
    return code == 0


def check_words():
    need = 'Optional: reads the words from your speech'
    if words_found():
        return _item('words', True, 'installed', need, 'auto')
    return _item('words', False, None, need, 'auto', '%s -m pip install -r requirements-words.txt' % venv_python(),
                 'Optional. Without it you type the words yourself instead of getting them from your speech.')


def recorded_provider():
    value = _read_json(paths.user_dir() / 'machine.json').get('matteProvider')
    return value if value in ('dml', 'coreml', 'cpu') else None


def check_gpu():
    need = 'Optional: use the graphics card for faster cutouts'
    value = recorded_provider()
    if value in ('dml', 'coreml'):
        return _item('gpu', True, 'graphics card', need, 'auto')
    if value == 'cpu':
        return _item('gpu', False, 'processor only', need, 'auto', 'floored.py doctor --gpu-check',
                     "Optional. The graphics card didn't give identical results, so cutouts use the processor.")
    return _item('gpu', False, None, need, 'auto', 'floored.py doctor --gpu-check',
                 'Optional. Checks whether your graphics card can make cutouts faster with identical results.')


CHECKS = {'python': check_python, 'ffmpeg': check_ffmpeg, 'node': check_node, 'browser': check_browser, 'venv': check_venv,
          'packages': check_packages, 'rvm-model': check_rvm, 'renderer': check_renderer, 'words': check_words, 'gpu': check_gpu}


# -- the report ----------------------------------------------------------------------------------------------------
def _mb(n):
    return '%d MB' % int(round(n))


def summarize(items):
    """(downloadMb, one-line summary) over the items that are not ok. Optional items are listed apart, not counted."""
    todo = [i for i in items if not i['ok'] and i['id'] not in OPTIONAL_IDS and i['mb'] > 0]
    optional = [i for i in items if not i['ok'] and i['id'] in OPTIONAL_IDS and i['mb'] > 0]
    total = sum(i['mb'] for i in todo)
    required_bad = [i for i in items if not i['ok'] and i['id'] not in OPTIONAL_IDS]
    parts = []
    if todo:
        parts.append('Setup needs %d download%s, about %s in total: %s.' % (
            len(todo), '' if len(todo) == 1 else 's', _mb(total), ', '.join('%s (%s)' % (LABELS[i['id']], _mb(i['mb'])) for i in todo)))
    elif required_bad:
        parts.append('Setup needs nothing to download, but %s still need%s attention.' % (
            ', '.join(LABELS[i['id']] for i in required_bad), 's' if len(required_bad) == 1 else ''))
    else:
        parts.append('Everything floored needs is installed.')
    if optional:
        parts.append('Optional, not counted: %s.' % ', '.join('%s (%s)' % (LABELS[i['id']], _mb(i['mb'])) for i in optional))
    return total, ' '.join(parts)


def build_report():
    """The plain report touches no network at all: sizes are the constants in SIZES_MB. Downloads happen only under --install."""
    items = [CHECKS[i]() for i in ITEM_IDS]
    total, summary = summarize(items)
    return {'ok': all(i['ok'] for i in items if i['id'] not in OPTIONAL_IDS), 'items': items, 'downloadMb': total, 'summary': summary}


# -- installing ----------------------------------------------------------------------------------------------------
def _opener(url):
    """urllib opener; a loopback address (tests) never goes through a proxy."""
    host = urllib.parse.urlparse(url).hostname or ''
    if host in ('127.0.0.1', 'localhost', '::1'):
        return urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener()


def download_rvm(log=log):
    """Download the weights to paths.rvm_model_path(): to `<file>.part`, check the SHA-256, then rename. A wrong hash deletes
    only the .part file. A file that was there before is never replaced or deleted."""
    url = os.environ.get('FLOORED_RVM_URL') or RVM_URL
    target = paths.rvm_model_path()
    if target.exists():
        if target.is_file() and sha256_file(target) == RVM_SHA256:
            return
        raise DoctorError("A different file is already at %s. floored won't overwrite it: move it away, then run the setup again." % target)
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(target.name + '.part')
    h = hashlib.sha256()
    done, shown = 0, 0
    try:
        with _opener(url).open(urllib.request.Request(url, headers={'User-Agent': 'floored-doctor'}), timeout=60) as r, open(str(part), 'wb') as f:
            total = int(r.headers.get('Content-Length') or 0)
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if done - shown >= 3_000_000:
                    shown = done
                    log('cutout model: %.0f of %.0f MB' % (done / 1e6, total / 1e6 if total else SIZES_MB['rvm-model']))
    except (OSError, urllib.error.URLError) as e:
        _remove(part)
        raise DoctorError("Couldn't download the cutout model (%s). Check the internet connection and try again." % (getattr(e, 'reason', None) or e))
    if h.hexdigest() != RVM_SHA256:
        _remove(part)
        raise DoctorError("The cutout model didn't download correctly (the file isn't the expected one), so it was thrown away. Try again.")
    if target.exists():                                      # someone else put a file there meanwhile: keep theirs
        _remove(part)
        raise DoctorError("Another file appeared at %s while downloading, so it was left alone." % target)
    os.rename(str(part), str(target))                        # never replaces: on Windows rename fails if the target exists


def _remove(path):
    try:
        os.remove(str(path))
    except OSError:
        pass


# -- floored's own Python, Node.js and ffmpeg ----------------------------------------------------------------------
def _rmtree(path):
    """Remove one of floored's own folders (a leftover, or the copy being replaced); DoctorError when something holds it.
    Read-only files (Windows keeps some) are made writable and the removal is tried once more. No `onerror` or `onexc`
    argument: each exists only in some Python versions, and this runs on whichever Python the computer has."""
    if not os.path.lexists(str(path)):
        return
    for last_try in (False, True):
        try:
            shutil.rmtree(str(path))
            return
        except OSError:
            if last_try:
                raise DoctorError("Couldn't replace the old copy in %s. Close anything that is using it, then try again." % path)
            for root, dirs, files in os.walk(str(path)):
                for name in dirs + files:
                    try:
                        os.chmod(os.path.join(root, name), 0o700)
                    except OSError:
                        pass


def _download_pin(item_id, label, pin, part, log):
    """Download pin['url'] to `part`. The byte count and the SHA-256 must equal the pin, else the part file is deleted."""
    address = urllib.parse.urlparse(pin['url'])
    if address.scheme != 'https' and not (address.scheme == 'http' and address.hostname in ('127.0.0.1', 'localhost', '::1')):
        raise DoctorError("floored only downloads over https, and the address it has for %s isn't one. Update floored." % label)
    part.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    done, shown = 0, 0
    try:
        with _opener(pin['url']).open(urllib.request.Request(pin['url'], headers={'User-Agent': 'floored-doctor'}), timeout=60) as r, \
                open(str(part), 'wb') as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if done - shown >= 5_000_000:
                    shown = done
                    log('%s: %.0f of %.0f MB' % (label, done / 1e6, pin['bytes'] / 1e6))
    except urllib.error.HTTPError as e:
        _remove(part)
        if e.code == 404:
            raise DoctorError("The file for %s has moved, so floored can't download it. Update floored, or install %s yourself from %s"
                              % (label, label, MANUAL[item_id]['page']))
        raise DoctorError("Couldn't download %s (the server answered %s). Check the internet connection and try again." % (label, e.code))
    except (OSError, urllib.error.URLError, http.client.HTTPException) as e:
        _remove(part)
        raise DoctorError("Couldn't download %s (%s). Check the internet connection and try again." % (label, getattr(e, 'reason', None) or e))
    if done != pin['bytes'] or h.hexdigest() != pin['sha256']:
        _remove(part)
        raise DoctorError("%s didn't download correctly (the file isn't the expected one), so it was thrown away. Try again." % label)


def _parts(name):
    """The parts of an archive path; a name that climbs out of the folder (or is absolute) is refused."""
    parts = [p for p in name.replace('\\', '/').split('/') if p not in ('', '.')]
    if '..' in parts or re.match(r'^[A-Za-z]:', name) or name.startswith(('/', '\\')):
        raise DoctorError("The download holds a file that would land outside floored's folder, so it was not unpacked.")
    return parts


def _system_tar():
    """The system's own tar: bsdtar on Windows 10 and later, and on macOS. It refuses to write through a link."""
    return os.path.join(os.environ.get('SystemRoot') or r'C:\Windows', 'System32', 'tar.exe') if _win() else '/usr/bin/tar'


def _unpack_tar(archive, dest):
    """Unpack a .tar.gz into dest without its single top folder, keeping symbolic links. A name that climbs out, a link
    that points out and anything that is not a file, a folder or a link are refused here. What a chain of links could do
    is left to tarfile's 'data' filter or, on a Python too old to have it (before 3.12, 3.11.4 and 3.10.12), to the
    system's own tar: an unfiltered extractall would follow the chain out of the folder."""
    with tarfile.open(str(archive), 'r:*') as t:
        members = []
        for m in t.getmembers():
            parts = _parts(m.name)[1:]
            if not parts:
                continue
            m.name = '/'.join(parts)
            if m.islnk():
                m.linkname = '/'.join(_parts(m.linkname)[1:])
            elif m.issym():
                target = os.path.normpath(os.path.join(os.path.dirname(m.name), m.linkname)).replace('\\', '/')
                if os.path.isabs(m.linkname) or re.match(r'^[A-Za-z]:', m.linkname) or target == '..' or target.startswith('../'):
                    raise DoctorError("The download holds a link that points outside floored's folder, so it was not unpacked.")
            elif not (m.isfile() or m.isdir()):
                raise DoctorError("The download holds something that is not a file, a folder or a link, so it was not unpacked.")
            members.append(m)
        if hasattr(tarfile, 'data_filter'):
            t.extractall(str(dest), members=members, filter='data')
            return
    try:
        code, _, err = run([_system_tar(), '-xf', str(archive), '-C', str(dest), '--strip-components', '1'], timeout=1800)
    except (OSError, subprocess.SubprocessError) as e:
        code, err = None, str(e)
    if code != 0:
        raise tarfile.TarError((err or 'the system tar did not run').strip().splitlines()[-1][:200])


def _unpack_zip(archive, dest, place):
    """Write the files of a zip into dest. place(parts) gives the path parts to write a file at, or None to skip it."""
    with zipfile.ZipFile(str(archive)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            target = place(_parts(info.filename))
            if not target:
                continue
            out = Path(str(dest)).joinpath(*target)
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as src, open(str(out), 'wb') as dst:
                shutil.copyfileobj(src, dst)


def _unpack(item_id, tool, archive, dest):
    if not zipfile.is_zipfile(str(archive)):
        _unpack_tar(archive, dest)
    elif item_id != 'ffmpeg':
        _unpack_zip(archive, dest, lambda parts: parts[1:] or None)          # Node.js for Windows: the top folder is dropped
    elif system_key() == 'win-x64':                    # ffmpeg and ffprobe in one zip: the files of bin/ go flat (DLLs too), the player stays out
        _unpack_zip(archive, dest, lambda parts: [parts[-1]] if len(parts) == 3 and parts[1] == 'bin'
                    and parts[-1].lower() != 'ffplay.exe' else None)
    else:                                                                    # one file per zip, made executable (zipfile doesn't keep the mode)
        with zipfile.ZipFile(str(archive)) as z:
            files = [_parts(i.filename) for i in z.infolist() if not i.is_dir()]
        hit = [p for p in files if p[-1] == tool] or (files if len(files) == 1 else [])
        _unpack_zip(archive, dest, lambda parts: [tool] if hit and parts == hit[0] else None)
        if os.path.isfile(os.path.join(str(dest), tool)):
            os.chmod(os.path.join(str(dest), tool), 0o755)


def _check_python_install():
    exe = own_python()
    code, out = _capture([str(exe), '-c', 'import sys;print(*sys.version_info[:3])'], timeout=30) if exe.is_file() else (None, '')
    if code != 0 or not re.fullmatch(r'\d+ \d+ \d+', out.strip()) or tuple(int(n) for n in out.split()) < MIN_PYTHON:
        raise DoctorError("Python was downloaded but doesn't start on this computer. Install Python 3.10 or newer yourself from %s"
                          % MANUAL['python']['page'])


def _check_node_install():
    folder = str(tools_dir() / 'node') if _win() else str(tools_dir() / 'node' / 'bin')
    exe, npm = _which_in(folder, 'node'), _which_in(folder, 'npm')
    version = node_version(exe) if exe else None
    if not version or version[0] < MIN_NODE:
        raise DoctorError("Node.js was downloaded but doesn't start on this computer. Install Node.js 22 or newer yourself from %s"
                          % MANUAL['node']['page'])
    if not npm:
        raise DoctorError("Node.js was downloaded without npm, so it can't be used. Try again.")
    record_tool('node', os.path.abspath(exe))
    record_tool('npm', os.path.abspath(npm))


def _check_ffmpeg_install():
    folder = str(tools_dir() / 'ffmpeg')
    exe, probe = _which_in(folder, 'ffmpeg'), _which_in(folder, 'ffprobe')
    if not exe or not probe:
        raise DoctorError("The ffmpeg download didn't hold ffmpeg and ffprobe, so it can't be used. Try again.")
    missing = ffmpeg_features(exe)['missing']
    if missing:
        raise DoctorError("The downloaded ffmpeg is missing parts floored needs (%s), so it can't be used." % ', '.join(
            FFMPEG_MISSING_TEXT[m] for m in missing))
    record_tool('ffmpeg', os.path.abspath(exe))
    record_tool('ffprobe', os.path.abspath(probe))


def _install_tool(item_id, log):
    """Download floored's own copy of python, node or ffmpeg into <user dir>/tools/<item>, then start it once to prove it runs."""
    pins = pins_for(item_id)
    if not pins:
        raise DoctorError('floored has no download for %s on this computer.' % LABELS[item_id])
    check = {'python': _check_python_install, 'node': _check_node_install, 'ffmpeg': _check_ffmpeg_install}[item_id]
    base = tools_dir()
    base.mkdir(parents=True, exist_ok=True)
    final, new = base / item_id, base / (item_id + '.new')
    if final.is_dir():                                   # asked twice: a copy that is there and runs is kept, not downloaded again
        try:
            check()
            return
        except DoctorError:
            pass
    parts = [base / (pin['tool'] + '.part') for pin in pins]
    _rmtree(new)
    try:
        new.mkdir()
        for pin, part in zip(pins, parts):
            _download_pin(item_id, LABELS.get(pin['tool'], pin['tool']), pin, part, log)
            try:
                _unpack(item_id, pin['tool'], part, new)
            except (OSError, tarfile.TarError, zipfile.BadZipFile) as e:
                raise DoctorError("%s was downloaded but couldn't be unpacked (%s). Try again." % (LABELS[item_id], e))
            finally:
                _remove(part)
        _rmtree(final)                                   # floored's own folder: a copy from an earlier run is replaced
        os.replace(str(new), str(final))
    finally:
        for part in parts:
            _remove(part)
        _rmtree(new)
    try:
        check()
    except DoctorError:
        _rmtree(final)                                   # don't leave a program that doesn't work in its own folder
        raise


def install_python(log=log):
    _install_tool('python', log)


def install_node(log=log):
    _install_tool('node', log)


def install_ffmpeg(log=log):
    _install_tool('ffmpeg', log)


def _stream(cmd, label, env=None, timeout=None):
    """Run cmd, relaying its output lines to stderr; DoctorError with the tail when it fails."""
    code, tail = run_lines(cmd, lambda line: log(label + ': ' + line[:200]), env=env, timeout=timeout)
    if code != 0:
        raise DoctorError('%s failed (exit %s): %s' % (label, code, ' | '.join(tail[-6:])))


def requirements_file(name):
    if (paths.APP_DIR / name).is_file():
        return paths.APP_DIR / name
    raise DoctorError("floored's list of add-ons (%s) is missing from this copy of the plugin." % name)


def install_venv(log=log):
    if venv_python().is_file():
        return
    exe, _ = find_python()
    if not exe:
        raise DoctorError('Python 3.10 or newer is needed first. Set up Python first (the doctor report shows how), then run this step again.')
    paths.user_dir().mkdir(parents=True, exist_ok=True)
    _stream([exe, '-m', 'venv', str(venv_dir())], 'python environment')
    if not venv_python().is_file():
        raise DoctorError("The Python environment wasn't created.")


def _pip(requirements, label):
    install_venv()
    _stream([str(venv_python()), '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '--only-binary=:all:',
             '-r', str(requirements_file(requirements))], label, timeout=1800)


def install_packages(log=log):
    _pip('requirements.txt', 'python add-ons')
    if not packages_found():
        raise DoctorError("The Python add-ons installed but don't start. Run the setup again.")


def _node_env():
    node, npm = find_program('node'), find_program('npm')
    if not node or not npm or not node_version(node['path']) or node_version(node['path'])[0] < MIN_NODE:
        raise DoctorError('Node.js 22 or newer is needed first. Set up Node.js first (the doctor report shows how), then run this step again.')
    find_program('ffmpeg')                       # records its folder (when found by search) for renderer_env() to put on PATH
    env = _renderer_env()
    env['PATH'] = os.path.dirname(node['path']) + os.pathsep + env.get('PATH', '')    # npm itself needs node, even before export exists
    return npm['path'], env


def _warmup_composition(folder):
    gsap = paths.WEB_DIR / 'engine' / 'gsap.min.js'
    shutil.copyfile(str(gsap), os.path.join(folder, 'gsap.min.js'))
    with open(os.path.join(folder, 'index.html'), 'w', encoding='utf-8') as f:
        f.write('<!DOCTYPE html>\n<html><head><meta charset="UTF-8"><meta name="viewport" content="width=320, height=568">\n'
                '<script src="gsap.min.js"></script>\n<style>html,body{margin:0;background:#000}</style></head>\n'
                '<body><div id="root" data-composition-id="main" data-start="0" data-width="320" data-height="568" '
                'data-duration="0.04" data-fps="30"></div>\n<script>window.__timelines=window.__timelines||{};'
                'var tl=gsap.timeline({paused:true});tl.to("#root",{duration:0.04,opacity:1});window.__timelines["main"]=tl;</script>\n'
                '</body></html>\n')


def install_renderer(log=log):
    if _export_or_none() is None:
        raise DoctorError('Install the Python add-ons first, then run this step again.')
    npm, env = _node_env()
    folder = renderer_dir()
    os.makedirs(folder, exist_ok=True)
    if renderer_version() != HYPERFRAMES_VERSION:
        log("video maker: installing (usually 10-15 minutes; it prints little until it's done)")
        _stream([npm, 'install', '--prefix', folder, 'hyperframes@' + HYPERFRAMES_VERSION, '--no-audit', '--no-fund'],
                'video maker', env=env, timeout=2700)
    if renderer_version() != HYPERFRAMES_VERSION or not os.path.isfile(renderer_exe()):
        raise DoctorError("The video maker didn't install correctly.")
    _stream([renderer_exe(), 'browser', 'ensure'], 'video maker browser', env=env, timeout=1800)
    with tempfile.TemporaryDirectory(prefix='ft-warm-') as work:         # one frame: proves the whole chain works offline later
        _warmup_composition(work)
        out = os.path.join(work, 'warmup.mp4')
        _stream([renderer_exe(), 'render', work, '-o', out, '--fps', '30', '--quality', 'draft', '--workers', '1', '--quiet'],
                'test video', env=env, timeout=900)
        if not os.path.isfile(out) or os.path.getsize(out) == 0:
            raise DoctorError("The video maker ran but didn't make its test video.")


def _pip_installed(name):
    code, out = _capture([str(venv_python()), '-m', 'pip', 'show', name], timeout=120)
    return code == 0 and out.lstrip().startswith('Name:')


def restore_onnxruntime():
    """faster-whisper depends on the plain `onnxruntime`, which would overwrite the Windows DirectML build (both provide the
    module `onnxruntime`). Its speech part never uses it, so after the words install the pinned build is put back."""
    if sys.platform == 'win32' and _pip_installed('onnxruntime'):
        py = str(venv_python())
        _stream([py, '-m', 'pip', 'uninstall', '-y', 'onnxruntime', 'onnxruntime-directml'], 'python add-ons', timeout=300)
        _stream([py, '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '--only-binary=:all:', '--no-deps',
                 '-r', str(requirements_file('requirements.txt'))], 'python add-ons', timeout=900)


def install_words(log=log):
    _pip('requirements-words.txt', 'speech reader')
    restore_onnxruntime()
    if not packages_found():
        raise DoctorError("The Python add-ons stopped working after the speech reader was added. Run the setup again.")
    target = paths.user_dir() / 'models' / 'faster-whisper-base'
    target.mkdir(parents=True, exist_ok=True)
    code = ('from huggingface_hub import snapshot_download\n'
            'snapshot_download(%r, local_dir=%r, allow_patterns=["config.json", "model.bin", "tokenizer.json", "vocabulary.*"])\n'
            % (WHISPER_REPO, str(target)))
    _stream([str(venv_python()), '-c', code], 'speech model', timeout=3600)
    if not words_found():
        raise DoctorError("The speech reader didn't install correctly.")


def gpu_check(log=log):
    """Compare the graphics card with the processor on 12 frames of the sample; record machine.json["matteProvider"]."""
    provider = {'win32': 'dml', 'darwin': 'coreml'}.get(sys.platform, 'cpu')
    result = {'worst': None}
    if provider != 'cpu':
        if not paths.rvm_model_path().is_file():
            raise DoctorError('The cutout model is needed first. Run the setup for it, then check again.')
        try:
            from ft import matte
        except ImportError:
            raise DoctorError('Install the Python add-ons first, then check again.')
        log('graphics card: comparing 12 frames with the processor')
        try:
            result = matte.parity(str(paths.SAMPLE_DIR / 'source.mp4'), provider, frames=12)
        except Exception:                                       # the card or its driver failed: the processor still works
            result = {'ok': False, 'worst': None, 'failed': True}
        if not result.get('ok'):
            provider = 'cpu'
    machine = _read_json(paths.user_dir() / 'machine.json')
    machine['matteProvider'] = provider
    machine['gpuCheck'] = {'date': datetime.date.today().isoformat(), 'worst': result.get('worst')}
    _write_json(paths.user_dir() / 'machine.json', machine)
    if provider == 'cpu':
        if result.get('failed'):
            return "Cutouts will use the processor (the graphics card couldn't be checked)."
        return "Cutouts will use the processor%s." % ('' if result.get('worst') is None else " (the graphics card's results weren't identical)")
    return 'Cutouts will use the graphics card; the results match the processor.'


INSTALLERS = {'python': install_python, 'ffmpeg': install_ffmpeg, 'node': install_node, 'venv': install_venv, 'packages': install_packages, 'rvm-model': download_rvm, 'renderer': install_renderer,
              'words': install_words}


def install(item_id, log=log):
    """{"id", "ok", "message"}. Never raises for an expected failure."""
    if item_id not in ITEM_IDS:
        return {'id': item_id, 'ok': False, 'message': 'There is no setup step called "%s".' % item_id, 'code': 2}
    if item_id in MANUAL and not (item_id in TOOL_IDS and pins_for(item_id)):      # a pinned download is floored's own job
        command = install_command(item_id)
        return {'id': item_id, 'ok': False, 'code': 2, 'command': command,
                'message': "%s is installed with a command, not by floored: %s" % (LABELS[item_id], command)}
    try:
        if item_id == 'gpu':
            return {'id': item_id, 'ok': True, 'message': gpu_check(log), 'code': 0}
        INSTALLERS[item_id](log)
    except DoctorError as e:
        return {'id': item_id, 'ok': False, 'message': str(e), 'code': 1}
    label = LABELS[item_id]                              # "The video maker is ready." but "ffmpeg is ready.": its name is written small
    name = label if item_id == 'ffmpeg' else label[0].upper() + label[1:]
    return {'id': item_id, 'ok': True, 'message': '%s %s ready.' % (name, 'are' if item_id == 'packages' else 'is'), 'code': 0}


# -- running from the private environment --------------------------------------------------------------------------
def run_in_venv(argv, script):
    """floored.py's first step: when ~/.floored/venv exists and this is not it, run the same command there and return
    its exit code. None when this interpreter is the one to use."""
    py = venv_python()
    if os.environ.get('FLOORED_NO_VENV') == '1' or not py.is_file():
        return None
    if os.path.normcase(os.path.realpath(sys.prefix)) == os.path.normcase(os.path.realpath(str(venv_dir()))):
        return None
    return subprocess.call([str(py), script] + list(argv))


def packages_here():
    """True when this interpreter can import the studio's Python add-ons."""
    import importlib.util
    try:
        return all(importlib.util.find_spec(m) is not None for m in PACKAGE_MODULES)
    except (ImportError, ValueError):
        return False


# -- the command ---------------------------------------------------------------------------------------------------
def format_report(report):
    lines = []
    for i in report['items']:
        mark = 'ok ' if i['ok'] else ('-- ' if i['id'] in OPTIONAL_IDS else 'NO ')
        lines.append('[%s] %-10s %s' % (mark.strip(), i['id'], i['found'] or i['need']))
        if not i['ok'] and i['note']:
            lines.append('       ' + i['note'])
        if not i['ok'] and i['command']:
            lines.append('       ' + i['command'])
    lines.append(report['summary'])
    return '\n'.join(lines)


def main(args):
    """args: the parsed `doctor` options (json, install, gpu_check)."""
    if args.install:
        result = install(args.install)
        code = result.pop('code', 0 if result['ok'] else 1)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return code
    if args.gpu_check:
        result = install('gpu')
        code = result.pop('code', 0 if result['ok'] else 1)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return code
    report = build_report()
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_report(report), flush=True)
    return 0 if report['ok'] else 1
