"""floored: the creator's preferences, kept by the server in the user folder (not in the browser: localStorage is per
port, so a server restarted on another port would forget everything).

  <user dir>/prefs.json = {"lastLook": str|None, "brand": {"floor": "#rrggbb", "ink": "#rrggbb"}|None,
                           "small": {"on": bool, "text": str (40 characters at most)},
                           "looks": [{"id", "name", "settings", "created"}]}

`Prefs` is safe to share between server threads (one lock around every read-modify-write); writes are atomic.
A file that cannot be read is renamed `prefs.json.bad-<stamp>` and defaults are used.
"""
import datetime
import json
import os
import re
import secrets
import threading
import time

from ft import pipeline

SMALL_MAX = 40
LOOK_NAME_MAX = 30
LOOK_SETTINGS_MAX = 64 * 1024                       # bytes of JSON
HEX = re.compile(r'#[0-9a-fA-F]{6}')
PATCH_KEYS = ('lastLook', 'brand', 'small')


class PrefsError(ValueError):
    """The input is not acceptable; str(e) is a short reason fit for a 400."""


def default_prefs():
    return {'lastLook': None, 'brand': None, 'small': {'on': False, 'text': ''}, 'looks': []}


def _brand(v):
    if v is None:
        return None
    if not isinstance(v, dict) or set(v) != {'floor', 'ink'} or \
            not all(isinstance(v[k], str) and HEX.fullmatch(v[k]) for k in v):
        raise PrefsError('brand must be null or {floor, ink}, both like #rrggbb.')
    return {'floor': v['floor'], 'ink': v['ink']}


def _small(v, base):
    """`v` may carry on and/or text; the rest comes from `base`."""
    if not isinstance(v, dict) or not v or set(v) - {'on', 'text'}:
        raise PrefsError('small must be {on, text}.')
    out = dict(base)
    if 'on' in v:
        if not isinstance(v['on'], bool):
            raise PrefsError('small.on must be true or false.')
        out['on'] = v['on']
    if 'text' in v:
        if not isinstance(v['text'], str) or len(v['text']) > SMALL_MAX:
            raise PrefsError('small.text must be text of %d characters at most.' % SMALL_MAX)
        out['text'] = v['text']
    return out


def _settings(v):
    if not isinstance(v, dict):
        raise PrefsError('settings must be an object.')
    if len(json.dumps(v, ensure_ascii=False).encode('utf-8')) > LOOK_SETTINGS_MAX:
        raise PrefsError('settings are too large (64 KB at most).')
    return v


def _now():
    return datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _clean(raw):
    """A prefs dict from whatever the file held: the good parts stay, the rest falls back to defaults."""
    out = default_prefs()
    if isinstance(raw.get('lastLook'), str):
        out['lastLook'] = raw['lastLook']
    try:
        out['brand'] = _brand(raw.get('brand'))
    except PrefsError:
        pass
    try:
        out['small'] = _small(raw.get('small'), out['small'])
    except PrefsError:
        pass
    for l in raw.get('looks') if isinstance(raw.get('looks'), list) else []:
        if isinstance(l, dict) and all(isinstance(l.get(k), str) and l[k] for k in ('id', 'name', 'created')) \
                and isinstance(l.get('settings'), dict) and not any(x['id'] == l['id'] for x in out['looks']):
            out['looks'].append({'id': l['id'], 'name': l['name'], 'settings': l['settings'], 'created': l['created']})
    return out


class Prefs:
    def __init__(self, user_dir):
        self.dir = str(user_dir)
        self.path = os.path.join(self.dir, 'prefs.json')
        self.lock = threading.RLock()

    # -- file ------------------------------------------------------------------------------------------------
    def _load(self):
        """The prefs as stored (call with the lock held)."""
        raw = None
        for _ in range(8):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    raw = json.load(f)
                break
            except FileNotFoundError:
                return default_prefs()
            except ValueError:
                break
            except OSError:                     # being replaced (Windows): look again in a moment
                time.sleep(0.02)
        else:
            return default_prefs()
        if not isinstance(raw, dict):
            self._set_aside()
            return default_prefs()
        return _clean(raw)

    def _set_aside(self):
        stamp = time.strftime('%Y%m%d-%H%M%S')
        for n in range(100):
            dst = '%s.bad-%s%s' % (self.path, stamp, '' if n == 0 else '-%d' % n)
            if not os.path.exists(dst):
                try:
                    os.replace(self.path, dst)
                except OSError:
                    pass
                return

    def _save(self, prefs):
        os.makedirs(self.dir, exist_ok=True)
        pipeline.write_json(self.path, prefs)

    # -- API -------------------------------------------------------------------------------------------------
    def get(self):
        with self.lock:
            return self._load()

    def put(self, patch):
        """Merge lastLook / brand / small into the prefs; returns the new prefs. Raises PrefsError."""
        if not isinstance(patch, dict):
            raise PrefsError('Send an object.')
        unknown = [k for k in patch if k not in PATCH_KEYS]
        if unknown:
            raise PrefsError('Unknown setting: %s.' % ', '.join(sorted(map(str, unknown))))
        with self.lock:
            cur = self._load()
            new = {}
            if 'lastLook' in patch:
                if not isinstance(patch['lastLook'], str):
                    raise PrefsError('lastLook must be text.')
                new['lastLook'] = patch['lastLook']
            if 'brand' in patch:
                new['brand'] = _brand(patch['brand'])
            if 'small' in patch:
                new['small'] = _small(patch['small'], cur['small'])
            cur.update(new)
            self._save(cur)
            return cur

    def add_look(self, name, settings):
        """Save a look; the same name (ignoring case and outer spaces) replaces the old one and keeps its id."""
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= LOOK_NAME_MAX:
            raise PrefsError('A look name needs 1 to %d characters.' % LOOK_NAME_MAX)
        name = name.strip()
        settings = _settings(settings)
        with self.lock:
            cur = self._load()
            for l in cur['looks']:
                if l['name'].strip().lower() == name.lower():
                    l['name'], l['settings'] = name, settings
                    self._save(cur)
                    return l['id']
            ids = {l['id'] for l in cur['looks']}
            lid = secrets.token_hex(4)
            while lid in ids:
                lid = secrets.token_hex(4)
            cur['looks'].append({'id': lid, 'name': name, 'settings': settings, 'created': _now()})
            self._save(cur)
            return lid

    def delete_look(self, look_id):
        with self.lock:
            cur = self._load()
            keep = [l for l in cur['looks'] if l['id'] != look_id]
            if len(keep) == len(cur['looks']):
                return False
            cur['looks'] = keep
            self._save(cur)
            return True
