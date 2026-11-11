"""Package hygiene for a public repository: no private footage, no private names or paths, small, every bundled
font and library carries its licence, and the plugin validates.

Everything here looks at the files git tracks (a public clone has no others)."""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / 'plugin' / 'skills' / 'floored'
APP = SKILL / 'app'
LICENSES = SKILL / 'licenses'
FONT_DIR = APP / 'web' / 'engine' / 'fonts'
SELF = Path(__file__).resolve().relative_to(REPO).as_posix()

# a user-folder name that looks real; placeholders such as <name>, you or creator are fine in examples
HOME_NAME = r'(?!(?:you|creator|user|name|yourname|username|me)\b|[<%{$])\w'
PRIVATE_PATH = re.compile(r'look-test|spikes|person_pp|shadow_pp|DdRQtGEM4yU', re.I)
# text that must not appear in any tracked text file: names of people whose footage is private, private clip ids,
# and absolute user paths (Windows or macOS home folders)
PRIVATE_TEXT = [
    re.compile(r'Brian'),
    re.compile(r'Paulo'),
    re.compile(r"O'Donnell"),
    re.compile(r'DdRQtGEM4yU'),
    re.compile(r'person_pp'),
    re.compile(r'shadow_pp'),
    re.compile(r'[A-Za-z]:[\\/]+Users[\\/]+' + HOME_NAME, re.I),
    re.compile(r'(?<![\w.~])/Users/' + HOME_NAME),
]
MAX_BYTES = 30 * 1024 * 1024
BINARY_EXT = {'.png', '.jpg', '.jpeg', '.webm', '.mp4', '.m4a', '.woff2', '.woff', '.ttf', '.gif', '.ico', '.onnx'}

# woff2 file in the engine's fonts folder -> the licence file that covers it
FONT_LICENCE = {
    'anton.woff2': 'OFL-Anton.txt',
    'serif.woff2': 'OFL-InstrumentSerif.txt',
    'geo.woff2': 'OFL-Poppins.txt',
    'mono.woff2': 'OFL-JetBrainsMono.txt',
    'stencil.woff2': 'OFL-BigShouldersStencil.txt',
    'gochihand.woff2': 'OFL-GochiHand.txt',
    'inter.woff2': 'OFL-Inter.txt',
}


def tracked():
    out = subprocess.run(['git', 'ls-files', '-z'], cwd=str(REPO), capture_output=True, check=True).stdout
    return [p for p in out.decode('utf-8').split('\0') if p and (REPO / p).is_file()]


def tracked_text():
    for rel in tracked():
        if Path(rel).suffix.lower() in BINARY_EXT:
            continue
        try:
            data = (REPO / rel).read_bytes()
        except OSError:
            continue
        if b'\0' in data:
            continue
        yield rel, data.decode('utf-8', 'replace')


def sha256(path):
    h = hashlib.sha256()
    with open(str(path), 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------------------------------- footage

def test_no_private_footage():
    files = tracked()
    bad = [p for p in files if PRIVATE_PATH.search(p) and p != SELF]
    assert not bad, 'tracked paths that look like private footage: %s' % bad

    # When the private folders sit next to this repo (the maintainer's machine), no tracked file may be a copy of one
    # of their files. Only files whose size matches a tracked file are hashed, so nothing else is opened.
    private_dirs = [d for d in (REPO.parent / 'look-test', REPO.parent / 'spikes') if d.is_dir()]
    if not private_dirs:
        return
    by_size = {}
    for p in files:
        by_size.setdefault((REPO / p).stat().st_size, []).append(p)
    candidates = [f for d in private_dirs for f in d.rglob('*') if f.is_file() and f.stat().st_size in by_size]
    tracked_hash = {}
    for f in candidates:
        size = f.stat().st_size
        for p in by_size[size]:
            tracked_hash.setdefault(sha256(REPO / p), p)
    clashes = [str(f) for f in candidates if sha256(f) in tracked_hash]
    assert not clashes, 'private files also tracked in the repo: %s' % clashes


def test_no_private_text():
    hits = []
    for rel, text in tracked_text():
        if rel == SELF:
            continue
        for rx in PRIVATE_TEXT:
            m = rx.search(text)
            if m:
                line = text.count('\n', 0, m.start()) + 1
                hits.append('%s:%d %r' % (rel, line, m.group(0)))
    assert not hits, 'private names or absolute user paths in tracked text files:\n' + '\n'.join(hits)


def test_comments_do_not_name_private_things():
    """Comments and docs must not point at the private spike folders or call the code a throwaway."""
    rx = re.compile(r'\bspikes?/|look-test|throwaway|throw-away prototype', re.I)
    hits = []
    for rel, text in tracked_text():
        if rel == SELF or rel.endswith('gsap.min.js') or rel == 'package-lock.json':
            continue
        for n, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                hits.append('%s:%d %s' % (rel, n, line.strip()[:100]))
    assert not hits, '\n'.join(hits)


# ---------------------------------------------------------------------------------------------------- size

def test_repo_under_30_mb():
    total = sum((REPO / p).stat().st_size for p in tracked())
    assert total < MAX_BYTES, 'tracked files are %.1f MB, the limit is 30 MB' % (total / 1048576)


FILMING_IMG = APP / 'web' / 'img' / 'filming'
FILMING_FILES = {'good-take.webp', 'good-intro.webp', 'above-take.webp', 'above-intro.webp', 'too-close.webp',
                 'walking.webp', 'two-people.webp', 'where-the-phone-goes.svg'}


def test_filming_pictures_are_light():
    """The studio's pictures of good and bad takes: exactly these files, 60 KB each at most, 350 KB together."""
    files = {p.name: p.stat().st_size for p in FILMING_IMG.iterdir() if p.is_file()}
    assert set(files) == FILMING_FILES, 'unexpected files in %s: %s' % (FILMING_IMG, sorted(set(files) ^ FILMING_FILES))
    too_big = {n: s for n, s in files.items() if s > 60 * 1024}
    assert not too_big, 'over 60 KB: %s' % too_big
    assert sum(files.values()) <= 350 * 1024, 'together %d bytes, the limit is 350 KB' % sum(files.values())


def test_bench_output_is_ignored():
    gi = (REPO / '.gitignore').read_text(encoding='utf-8')
    assert 'dev/bench/*/' in gi
    r = subprocess.run(['git', 'check-ignore', '-q', 'dev/bench/some-run/out.png'], cwd=str(REPO))
    assert r.returncode == 0


# ---------------------------------------------------------------------------------------------------- licences

def test_every_font_has_a_licence():
    fonts = sorted(p.name for p in FONT_DIR.glob('*.woff2'))
    assert fonts, 'no fonts found in %s' % FONT_DIR
    for name in fonts:
        assert name in FONT_LICENCE, '%s has no licence mapping in this test: add its OFL text' % name
        lic = LICENSES / FONT_LICENCE[name]
        assert lic.is_file(), 'missing %s' % lic
        text = lic.read_text(encoding='utf-8')
        assert 'SIL OPEN FONT LICENSE Version 1.1' in text, '%s is not the OFL 1.1 text' % lic.name
        assert 'Copyright' in text, '%s has no copyright line' % lic.name
        first = text.lstrip().splitlines()[0]
        assert 'github.com/google/fonts' in first or 'raw.githubusercontent.com/google/fonts' in first, \
            '%s: record the source URL at the top' % lic.name


def test_bundled_fonts_use_no_reserved_name():
    """A subset is a Modified Version: a family whose OFL text reserves its name must be renamed in the font itself."""
    from fontTools.ttLib import TTFont
    for name, lic in FONT_LICENCE.items():
        text = (LICENSES / lic).read_text(encoding='utf-8')
        reserved = re.findall(r'Reserved Font Names? ((?:"[^"]+"(?:,? and |, )?)+)', text)
        names = re.findall(r'"([^"]+)"', ' '.join(reserved))
        font = TTFont(str(FONT_DIR / name))
        used = [str(r) for r in font['name'].names if r.nameID in (1, 3, 4, 6, 16, 18, 21)]
        for rn in names:
            for s in used:
                assert rn.lower() not in s.lower(), '%s still names itself %r (reserved by %s)' % (name, s, lic)
    # Gochi Hand is the one that reserves names: it must be there, and renamed
    gochi = (LICENSES / 'OFL-GochiHand.txt').read_text(encoding='utf-8')
    assert 'Reserved Font Names "Gochi" and "Gochi Hand"' in gochi
    assert (FONT_DIR / 'gochihand.woff2').is_file()


def test_third_party_notices():
    third = (REPO / 'THIRD_PARTY.md').read_text(encoding='utf-8')
    for font in ('Anton', 'Instrument Serif', 'Poppins', 'JetBrains Mono', 'Big Shoulders Stencil', 'Gochi Hand', 'Inter'):
        assert font in third, 'THIRD_PARTY.md does not list %s' % font
    assert 'GSAP' in third and '3.14.2' in third

    notice = (LICENSES / 'NOTICE.md').read_text(encoding='utf-8')
    for needle in ('GPL-3.0', 'rvm_mobilenetv3_fp32.onnx', 'never bundled', 'HyperFrames', 'Apache-2.0',
                   'faster-whisper', 'onnxruntime', 'numpy', 'BSD-3', 'GSAP', 'MIT'):
        assert needle in notice, 'NOTICE.md is missing %r' % needle

    gsap = (LICENSES / 'GSAP.md').read_text(encoding='utf-8')
    assert 'gsap.com/standard-license' in gsap and '3.14.2' in gsap
    assert '3.14.2' in (APP / 'web' / 'engine' / 'gsap.min.js').read_text(encoding='utf-8')[:400]


def test_licence_files_exist():
    lic = (REPO / 'LICENSE').read_text(encoding='utf-8')
    assert lic.startswith('MIT License')
    assert 'Copyright (c) 2026 aipauloshimas' in lic
    assert (APP / 'sample' / 'README.md').is_file()


def test_readme_covers_the_basics():
    text = (REPO / 'README.md').read_text(encoding='utf-8')
    low = text.lower()
    assert 'floored' in low
    for needle in ('claude plugin marketplace add', 'claude plugin install floored@floored',
                   'claude plugin uninstall floored', '~/.floored', 'reference/filming.md',
                   'poster.jpg', 'Windows 11', 'Mac'):
        assert needle in text, 'README.md is missing %r' % needle
    for word in ('requirements', 'install', 'first run', 'filming', 'privacy', 'uninstall'):
        assert re.search(r'^#+ .*%s' % word, low, re.M), 'README.md has no %r heading' % word
    # the picture it points at is tracked
    assert (APP / 'sample' / 'poster.jpg').is_file()


# ---------------------------------------------------------------------------------------------------- plugin

@pytest.mark.skipif(shutil.which('claude') is None, reason='the claude CLI is not on PATH')
@pytest.mark.parametrize('target', ['plugin', '.'])
def test_plugin_validates(target):
    r = subprocess.run([shutil.which('claude'), 'plugin', 'validate', target], cwd=str(REPO),
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, 'claude plugin validate %s failed:\n%s%s' % (target, r.stdout, r.stderr)


def _git(*args):
    return subprocess.run(['git'] + list(args), cwd=str(REPO), capture_output=True, text=True, encoding='utf-8')


def test_a_change_to_the_plugin_comes_with_a_new_version():
    """Claude Code keeps an installed plugin by its version, so a fix pushed under the published version reaches nobody.
    Compares the working tree with the published branch when this checkout knows one (skipped when it doesn't)."""
    ref = next((r for r in ('github/main', 'origin/main')
                if _git('rev-parse', '--verify', '--quiet', r + '^{commit}').returncode == 0), None)
    if ref is None:
        pytest.skip('this checkout has no published branch to compare with')
    if _git('diff', '--quiet', ref, '--', 'plugin').returncode == 0:
        return                                            # the plugin is what is published: nothing to bump
    shown = _git('show', ref + ':plugin/.claude-plugin/plugin.json')
    if shown.returncode != 0:
        pytest.skip('the published branch has no plugin.json')
    published = json.loads(shown.stdout)['version']
    here = json.loads((REPO / 'plugin' / '.claude-plugin' / 'plugin.json').read_text(encoding='utf-8'))['version']
    assert here != published, ('plugin/ differs from %s but the version is still %s: change "version" in '
                               'plugin/.claude-plugin/plugin.json' % (ref, published))
