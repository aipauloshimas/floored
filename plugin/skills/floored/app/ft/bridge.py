"""The Claude bridge: what the command line does for Claude (the skill) without opening the studio.

  validate_suggestions(data)   the hook suggestions Claude writes into a take (checked by the command line first and by
                               the server again): {"suggestions": [1-6 strings], "smallSuggestions": [0-3 strings]}
  wait_for_take(...)           poll a take's status.json (files only: no server needed) until it is ready, failed, or late
"""
import os
import re
import sys
import time

from ft import pipeline

MAX_SUGGESTIONS = 6
MAX_SUGGESTION_CHARS = 60
MAX_SUGGESTION_WORDS = 12
MAX_SMALL = 3
MAX_SMALL_CHARS = 40
POLL_S = 2.0
NEXT_TOLERANCE_S = 1.0                     # --next: a folder made this long before the command started still counts
TAKE_ID = re.compile(r'[A-Za-z0-9_.-]+')


class BridgeError(Exception):
    """Something the caller got wrong; str(e) is one line saying what and how to fix it."""


def valid_take_id(tid):
    return isinstance(tid, str) and bool(TAKE_ID.fullmatch(tid)) and not tid.startswith('.')


def _strings(data, key, lo, hi, max_chars, max_words=None):
    items = data.get(key, [])
    if not isinstance(items, list):
        raise BridgeError('"%s" must be a list of strings.' % key)
    if not lo <= len(items) <= hi:
        raise BridgeError('"%s" needs %s, found %d.' % (key, ('%d to %d strings' % (lo, hi)) if lo != hi else '%d strings' % lo, len(items)))
    out = []
    for i, s in enumerate(items, 1):
        if not isinstance(s, str):
            raise BridgeError('"%s" #%d is not a string.' % (key, i))
        s = s.strip()
        if not s:
            raise BridgeError('"%s" #%d is empty.' % (key, i))
        if len(s) > max_chars:
            raise BridgeError('"%s" #%d is %d characters; the limit is %d: "%s"' % (key, i, len(s), max_chars, s))
        if max_words and len(s.split()) > max_words:
            raise BridgeError('"%s" #%d has %d words; the limit is %d: "%s"' % (key, i, len(s.split()), max_words, s))
        out.append(s)
    return out


def validate_suggestions(data):
    """The cleaned {"suggestions", "smallSuggestions"} (strings trimmed), or BridgeError. suggestions: 1-6 strings, each
    non-empty, at most 60 characters and 12 words. smallSuggestions: 0-3 strings (absent = none), at most 40 characters.
    Any other key is refused."""
    if not isinstance(data, dict):
        raise BridgeError('The suggestions must be a JSON object: {"suggestions": [...], "smallSuggestions": [...]}.')
    extra = sorted(set(data) - {'suggestions', 'smallSuggestions'})
    if extra:
        raise BridgeError('Unknown key%s: %s. Only "suggestions" and "smallSuggestions" are allowed.'
                          % ('s' if len(extra) > 1 else '', ', '.join(extra)))
    if 'suggestions' not in data:
        raise BridgeError('"suggestions" is missing (1 to %d strings).' % MAX_SUGGESTIONS)
    return {'suggestions': _strings(data, 'suggestions', 1, MAX_SUGGESTIONS, MAX_SUGGESTION_CHARS, MAX_SUGGESTION_WORDS),
            'smallSuggestions': _strings(data, 'smallSuggestions', 0, MAX_SMALL, MAX_SMALL_CHARS)}


# -- wait ----------------------------------------------------------------------------------------------------------
def _created_at(path):
    """When a folder was created, or None where the file system cannot tell (POSIX ctime is the last change)."""
    st = os.stat(path)
    if hasattr(st, 'st_birthtime'):
        return st.st_birthtime
    return st.st_ctime if os.name == 'nt' else None


def _take_folders(takes_dir):
    try:
        return [d for d in os.listdir(takes_dir) if d != 'sample' and os.path.isdir(os.path.join(takes_dir, d))]
    except OSError:
        return []


class NextTake:
    """The first take folder created after the command started: not in the snapshot taken at the start, or (where the
    file system says) created within NEXT_TOLERANCE_S before it."""

    def __init__(self, takes_dir, started=None):
        self.takes_dir = str(takes_dir)
        self.started = started if started is not None else time.time()
        self.before = set(_take_folders(self.takes_dir))

    def find(self):
        best = None
        for d in _take_folders(self.takes_dir):
            try:
                made = _created_at(os.path.join(self.takes_dir, d))
            except OSError:
                continue
            fresh = d not in self.before or (made is not None and made >= self.started - NEXT_TOLERANCE_S)
            if fresh and (best is None or (made or 0) < best[0]):
                best = (made or 0, d)
        return best[1] if best else None


def ready_result(tid, takes_dir):
    take_json = os.path.abspath(os.path.join(str(takes_dir), tid, 'take.json'))
    take = pipeline.read_json(take_json, {}) or {}
    words = take.get('words') or []
    return {'take': tid, 'stage': 'ready', 'takeJson': take_json, 'hasWords': bool(words),
            'language': take.get('language'), 'transcript': take.get('transcript') or '',
            'warnings': take.get('warnings') or []}


def wait_for_take(takes_dir, take=None, next_take=None, timeout=3600.0, poll=POLL_S, progress=None, clock=time.time):
    """Poll until the take is ready or failed. Returns (exit code, result dict): 0 ready, 3 error, 4 timeout.
    `take` is an id; `next_take` a NextTake (the take is the first new folder). progress(text) gets stage changes."""
    deadline = clock() + timeout
    tid = take
    last = None
    while True:
        if tid is not None and take is None and not os.path.isdir(os.path.join(str(takes_dir), tid)):
            tid = last = None                      # --next: its folder vanished (an interrupted upload): look for the next one
        if tid is None:
            tid = next_take.find()
        if tid is not None:
            st = pipeline.read_json(os.path.join(str(takes_dir), tid, 'status.json'))
            stage = st.get('stage') if isinstance(st, dict) else None
            if stage == 'ready':
                return 0, ready_result(tid, takes_dir)
            if stage == 'error':
                return 3, {'take': tid, 'stage': 'error', 'message': st.get('message') or st.get('error') or 'The take failed.'}
            if progress and stage and (stage, int(100 * (st.get('overall') or 0))) != last:
                last = (stage, int(100 * (st.get('overall') or 0)))
                progress('%s %s %d%%' % (tid, stage, last[1]))
        if clock() >= deadline:
            return 4, {'take': tid, 'stage': 'timeout'}
        time.sleep(poll)


def log_progress(text):
    print(text, file=sys.stderr, flush=True)
