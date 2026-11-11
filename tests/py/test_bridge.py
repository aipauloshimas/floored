"""The Claude bridge: floored.py add / wait / suggest / retry (what the skill runs for the creator)."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time

import pytest

from conftest import APP
from ft import cli, paths, pipeline, server, words
from test_server import FLOORED, Cli, fetch, port_base


# ------------------------------------------------------------------------------------------------------------ fixtures
@pytest.fixture(scope='module')
def bridge(tmp_path_factory):
    """A command line with a private user folder, the fake cutout and a fast poll; servers it starts are stopped by pid."""
    c = Cli(tmp_path_factory.mktemp('ft-home'), port_base())
    c.env.update(FT_FAKE_MATTE='1', FT_WAIT_POLL='0.2')
    yield c
    for w in sorted(set(c.workspaces)):
        try:
            c.run('stop', '--workspace', w, timeout=30)
        except subprocess.TimeoutExpired:
            pass
        rec = server.read_server_file(paths.Workspace(w))
        if rec and cli.pid_alive(rec.get('pid') or 0):
            cli.kill_tree(rec['pid'])


@pytest.fixture(scope='module')
def proj(tmp_path_factory):
    return tmp_path_factory.mktemp('proj')


def last_json(result):
    lines = [l for l in result.stdout.splitlines() if l.strip()]
    assert len(lines) == 1, (result.stdout, result.stderr)
    return json.loads(lines[0])


def add(bridge, proj, video):
    r = bridge.run('add', video, '--workspace', proj, timeout=120)
    assert r.returncode == 0, (r.stdout, r.stderr)
    return last_json(r)


@pytest.fixture(scope='module')
def ready_take(bridge, proj, tmp_path_factory):
    from conftest import _make, X264
    clip = _make(tmp_path_factory.mktemp('bridge-clips'), 'ready.mp4', '1080x1920', 30, 0.5, 'libx264', X264)
    tid = add(bridge, proj, clip)['take']
    r = bridge.run('wait', '--workspace', proj, '--take', tid, '--timeout', 180, timeout=200)
    assert r.returncode == 0, (r.stdout, r.stderr)
    return tid


@pytest.fixture(scope='module')
def srv_url(bridge, proj, ready_take):
    return server.read_server_file(paths.Workspace(proj))['url']


def make_take(ws_dir, tid, stage, message='', **take):
    """A take folder written by hand (no server involved)."""
    d = paths.Workspace(ws_dir).takes / tid
    d.mkdir(parents=True)
    pipeline.write_json(str(d / 'status.json'), {'stage': stage, 'progress': 1, 'overall': 0.5, 'message': message})
    pipeline.write_json(str(d / 'take.json'), dict({'id': tid, 'name': tid}, **take))
    return d


# ---------------------------------------------------------------------------------------------------------------- add
def test_add_prints_take_and_url_with_spaces_and_accents(bridge, tmp_path, portrait_1080):
    proj = tmp_path / 'proj'
    clip = tmp_path / 'meu vídeo ação.mp4'
    shutil.copyfile(portrait_1080, clip)
    out = add(bridge, proj, clip)
    assert set(out) == {'take', 'url'} and out['url'].startswith('http://127.0.0.1:') and out['take'] in out['url']
    take = fetch(out['url'].split('#')[0], '/api/takes/' + out['take'])[1]['take']
    assert take['name'] == 'meu vídeo ação' and take['file'] == 'meu vídeo ação.mp4'


def test_add_missing_file_exit_2(bridge, tmp_path):
    r = bridge.run('add', tmp_path / 'nope.mp4', '--workspace', tmp_path / 'proj')
    assert r.returncode == 2 and r.stdout == '' and 'find the video' in r.stderr
    assert not (tmp_path / 'proj' / 'floored' / '.server.json').exists()          # nothing was started for it


def test_add_reads_a_path_that_starts_at_the_home_folder(bridge, tmp_path):
    """A creator writes "~/Movies/take.mp4". Inside quotes the shell leaves the ~ as it is, so floored expands it."""
    home = tmp_path / 'home'
    home.mkdir()
    r = bridge.run('add', '~/Movies/nope.mp4', '--workspace', tmp_path / 'proj', env={'HOME': str(home), 'USERPROFILE': str(home)})
    assert r.returncode == 2 and os.path.join(str(home), 'Movies', 'nope.mp4') in r.stderr, r.stderr


def test_add_not_a_video_exit_2(bridge, tmp_path):
    txt = tmp_path / 'notes.txt'
    txt.write_text('hello', encoding='utf-8')
    r = bridge.run('add', txt, '--workspace', tmp_path / 'proj')
    assert r.returncode == 2 and r.stdout == '' and 'video file' in r.stderr


# --------------------------------------------------------------------------------------------------------------- wait
def test_wait_returns_when_ready(bridge, proj, ready_take):
    r = bridge.run('wait', '--workspace', proj, '--take', ready_take, '--timeout', 30)
    assert r.returncode == 0, r.stderr
    out = last_json(r)
    assert set(out) == {'take', 'stage', 'takeJson', 'hasWords', 'language', 'transcript', 'warnings'}
    assert out['take'] == ready_take and out['stage'] == 'ready'
    assert os.path.isabs(out['takeJson']) and os.path.isfile(out['takeJson'])
    on_disk = json.load(open(out['takeJson'], encoding='utf-8'))
    assert out['hasWords'] == bool(on_disk['words']) and out['warnings'] == on_disk['warnings']
    assert out['transcript'] == on_disk['transcript'] and isinstance(out['warnings'], list)


def test_wait_runs_while_the_take_is_still_being_made(bridge, tmp_path, portrait_1080):
    slow = Cli(bridge.env['FLOORED_HOME'], bridge.env['FT_PORT_BASE'])
    slow.env.update(bridge.env, FT_FAKE_MATTE_DELAY='3')
    proj = tmp_path / 'proj'
    tid = slow.run('add', portrait_1080, '--workspace', proj, timeout=120)
    tid = last_json(tid)['take']
    bridge.workspaces.append(str(proj))
    t0 = time.time()
    r = bridge.run('wait', '--workspace', proj, '--take', tid, '--timeout', 120, timeout=150)
    assert r.returncode == 0 and last_json(r)['stage'] == 'ready'
    assert time.time() - t0 >= 1.5 and r.stderr.strip()                                # it really waited, and said where


def test_wait_next_sees_browser_upload(bridge, proj, ready_take, srv_url, portrait_1080):
    p = subprocess.Popen([sys.executable, FLOORED, 'wait', '--workspace', str(proj), '--next', '--timeout', '120'],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=bridge.env)
    try:
        time.sleep(1.5)                                       # the command has looked at the folder by now
        with open(portrait_1080, 'rb') as f:
            code, body = fetch(srv_url, '/api/takes', headers={'X-Filename': 'from%20browser.mp4'}, method='POST', data=f.read())
        assert code == 200
        out, err = p.communicate(timeout=150)
    finally:
        if p.poll() is None:
            p.kill()
    assert p.returncode == 0, err
    got = json.loads(out.decode('utf-8'))
    assert got['take'] == body['id'] and got['take'] != ready_take and got['stage'] == 'ready'


def test_wait_error_exit_3(bridge, tmp_path, clip_12s):
    proj = tmp_path / 'proj'
    tid = add(bridge, proj, clip_12s)['take']                 # refused when it arrives: add still hands back the take
    bridge.workspaces.append(str(proj))
    r = bridge.run('wait', '--workspace', proj, '--take', tid, '--timeout', 60)
    assert r.returncode == 3
    out = last_json(r)
    assert out['take'] == tid and out['stage'] == 'error' and 'Trim' in out['message'] and '12.0' in out['message']


def test_wait_needs_no_server(bridge, tmp_path):
    proj = tmp_path / 'proj'
    d = make_take(proj, '261109-120000-abcd', 'ready', 'Ready', transcript='Hello there friend', language='en',
                  words=[{'word': 'Hello', 'start': 0.1, 'end': 0.4}], warnings=[{'code': 'edge', 'message': 'Leave room.'}])
    r = bridge.run('wait', '--workspace', proj, '--take', '261109-120000-abcd', '--timeout', 5)
    assert r.returncode == 0
    out = last_json(r)
    assert out['hasWords'] is True and out['language'] == 'en' and out['transcript'] == 'Hello there friend'
    assert out['warnings'] == [{'code': 'edge', 'message': 'Leave room.'}] and out['takeJson'] == os.path.abspath(str(d / 'take.json'))
    assert not (proj / 'floored' / '.server.json').exists()


def test_wait_times_out_with_exit_4(bridge, tmp_path):
    proj = tmp_path / 'proj'
    make_take(proj, 'slow-one', 'cutting', 'Cutting')
    r = bridge.run('wait', '--workspace', proj, '--take', 'slow-one', '--timeout', 1)
    assert r.returncode == 4 and last_json(r) == {'take': 'slow-one', 'stage': 'timeout'}
    r = bridge.run('wait', '--workspace', proj, '--next', '--timeout', 1)                # the existing take is not "next"
    assert r.returncode == 4 and last_json(r) == {'take': None, 'stage': 'timeout'}


def test_wait_next_ignores_the_sample_and_takes_it_finds_later(bridge, tmp_path):
    proj = tmp_path / 'proj'
    paths.Workspace(proj).ensure()
    (paths.Workspace(proj).takes / 'sample').mkdir()
    pipeline.write_json(str(paths.Workspace(proj).takes / 'sample' / 'status.json'), {'stage': 'ready'})
    p = subprocess.Popen([sys.executable, FLOORED, 'wait', '--workspace', str(proj), '--next', '--timeout', '30'],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, env=bridge.env)
    time.sleep(1.5)
    make_take(proj, 'new-take', 'error', 'Nope.')
    out, _ = p.communicate(timeout=40)
    assert p.returncode == 3 and json.loads(out.decode('utf-8'))['take'] == 'new-take'


def test_wait_unknown_take_and_bad_id_exit_2(bridge, tmp_path):
    for tid in ('missing', '..', 'a/b'):
        r = bridge.run('wait', '--workspace', tmp_path / 'proj', '--take', tid)
        assert r.returncode == 2 and r.stdout == '', tid
    assert bridge.run('wait', '--workspace', tmp_path).returncode == 2                   # argparse: --take or --next


# ------------------------------------------------------------------------------------------------------------ suggest
GOOD = {'suggestions': ['Hook one', 'Hook two', 'Hook three', 'Hook four'], 'smallSuggestions': ['IN CLAUDE CODE']}


def write_suggestions(tmp_path, obj, name='s.json'):
    f = tmp_path / name
    f.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding='utf-8')
    return f


def get_take(url, tid):
    code, body = fetch(url, '/api/takes/' + tid)
    assert code == 200
    return body['take']


def test_suggest_bumps_rev(bridge, proj, srv_url, ready_take, tmp_path):
    assert get_take(srv_url, ready_take)['suggestionsRev'] == 0
    r = bridge.run('suggest', '--workspace', proj, '--take', ready_take, '--file', write_suggestions(tmp_path, GOOD))
    assert r.returncode == 0, r.stderr
    assert last_json(r) == {'ok': True, 'rev': 1}
    take = get_take(srv_url, ready_take)
    assert take['suggestions'] == GOOD['suggestions'] and take['smallSuggestions'] == ['IN CLAUDE CODE']
    assert take['suggestionsRev'] == 1
    again = {'suggestions': ['  Não precisa de After Effects  '], 'smallSuggestions': []}
    r = bridge.run('suggest', '--workspace', proj, '--take', ready_take, '--file', write_suggestions(tmp_path, again, 'b.json'))
    assert last_json(r) == {'ok': True, 'rev': 2}
    take = get_take(srv_url, ready_take)
    assert take['suggestions'] == ['Não precisa de After Effects'] and take['smallSuggestions'] == [] and take['suggestionsRev'] == 2
    stored = json.load(open(paths.Workspace(proj).settings_dir / (ready_take + '.suggestions.json'), encoding='utf-8'))
    assert stored['rev'] == 2 and stored['suggestions'] == ['Não precisa de After Effects']
    listed = next(i['take'] for i in fetch(srv_url, '/api/takes')[1] if i['take']['id'] == ready_take)
    assert listed['suggestionsRev'] == 2                                                  # the list agrees with the take
    on_disk = json.load(open(paths.Workspace(proj).takes / ready_take / 'take.json', encoding='utf-8'))
    assert 'suggestions' not in on_disk                                                   # take.json itself is never touched


def test_suggest_reads_stdin(bridge, proj, ready_take):
    r = subprocess.run([sys.executable, FLOORED, 'suggest', '--workspace', str(proj), '--take', ready_take, '--file', '-'],
                       input=json.dumps(GOOD).encode('utf-8'), capture_output=True, env=bridge.env, timeout=60)
    assert r.returncode == 0 and json.loads(r.stdout.decode('utf-8'))['ok'] is True


LONG61 = 'x' * 61


@pytest.mark.parametrize('bad, reason', [
    ({'suggestions': [LONG61]}, '61 characters'),
    ({'suggestions': ['a b c d e f g h i j k l m']}, '13 words'),
    ({'suggestions': ['a'] * 7}, '7'),
    ({'suggestions': []}, '0'),
    ({}, 'missing'),
    ({'suggestions': ['ok', '   ']}, 'empty'),
    ({'suggestions': ['ok', 5]}, 'not a string'),
    ({'suggestions': 'ok'}, 'list'),
    ({'suggestions': ['ok'], 'smallSuggestions': ['x'] * 4}, '4'),
    ({'suggestions': ['ok'], 'smallSuggestions': ['x' * 41]}, '41 characters'),
    ({'suggestions': ['ok'], 'extra': 1}, 'extra'),
    (['ok'], 'object'),
    ('{ not json', 'JSON'),
])
def test_suggest_rejects_invalid(bridge, proj, srv_url, ready_take, tmp_path, bad, reason):
    before = get_take(srv_url, ready_take)['suggestionsRev']
    r = bridge.run('suggest', '--workspace', proj, '--take', ready_take, '--file', write_suggestions(tmp_path, bad))
    assert r.returncode == 2 and r.stdout == ''
    assert len(r.stderr.strip().splitlines()) == 1 and reason in r.stderr, r.stderr
    assert get_take(srv_url, ready_take)['suggestionsRev'] == before


def test_suggest_rejects_long(bridge, proj, srv_url, ready_take, tmp_path):
    r = bridge.run('suggest', '--workspace', proj, '--take', ready_take,
                   '--file', write_suggestions(tmp_path, {'suggestions': ['x' * 61]}))
    assert r.returncode == 2 and '61' in r.stderr


def test_suggest_limits_are_inclusive(bridge, proj, srv_url, ready_take, tmp_path):
    ok = {'suggestions': ['x' * 60, ' '.join(['w'] * 12)] + ['a'] * 4, 'smallSuggestions': ['y' * 40, 'b', 'c']}
    r = bridge.run('suggest', '--workspace', proj, '--take', ready_take, '--file', write_suggestions(tmp_path, ok))
    assert r.returncode == 0, r.stderr


def test_suggest_server_checks_too(srv_url, ready_take):
    body = json.dumps({'suggestions': [LONG61]}).encode('utf-8')
    code, out = fetch(srv_url, '/api/takes/%s/suggestions' % ready_take, headers={'Content-Type': 'application/json'},
                      method='POST', data=body)
    assert code == 400 and '61' in out['error']
    code, out = fetch(srv_url, '/api/takes/nope/suggestions', headers={'Content-Type': 'application/json'},
                      method='POST', data=json.dumps(GOOD).encode('utf-8'))
    assert code == 404


def test_suggest_unknown_take_exit_2(bridge, proj, srv_url, tmp_path):
    r = bridge.run('suggest', '--workspace', proj, '--take', 'no-such-take', '--file', write_suggestions(tmp_path, GOOD))
    assert r.returncode == 2 and 'No such take' in r.stderr


def test_suggest_reads_a_file_powershell_wrote(bridge, proj, srv_url, ready_take, tmp_path):
    """Windows PowerShell's `>` writes UTF-16 with a byte-order mark; the accents must arrive whole."""
    f = tmp_path / 'ps.json'
    f.write_bytes(json.dumps({'suggestions': ['Não é mágica, é método'], 'smallSuggestions': []}, ensure_ascii=False).encode('utf-16'))
    r = bridge.run('suggest', '--workspace', proj, '--take', ready_take, '--file', f)
    assert r.returncode == 0, r.stderr
    assert get_take(srv_url, ready_take)['suggestions'] == ['Não é mágica, é método']


def test_suggest_says_when_the_file_is_not_utf8(bridge, proj, srv_url, ready_take, tmp_path):
    """A file saved in the Windows code page: refuse it and say why, never store broken accents."""
    before = get_take(srv_url, ready_take)['suggestionsRev']
    f = tmp_path / 'ansi.json'
    f.write_bytes('{"suggestions": ["Não é mágica"], "smallSuggestions": []}'.encode('cp1252'))
    r = bridge.run('suggest', '--workspace', proj, '--take', ready_take, '--file', f)
    assert r.returncode == 2 and 'UTF-8' in r.stderr and 'file-writing tool' in r.stderr, r.stderr
    assert get_take(srv_url, ready_take)['suggestionsRev'] == before


def sha(path):
    return hashlib.sha256(open(path, 'rb').read()).hexdigest()


def test_suggest_on_sample(bridge, proj, srv_url, tmp_path):
    sample = paths.SAMPLE_DIR
    before = {f: sha(sample / f) for f in os.listdir(sample)}
    own = get_take(srv_url, 'sample')
    assert own['suggestions'][0] == "You don't need After Effects for this" and own['smallSuggestions'] == ['IN CLAUDE CODE']
    assert own['suggestionsRev'] == 0                                                     # the sample's own copy, nothing written yet
    r = bridge.run('suggest', '--workspace', proj, '--take', 'sample', '--file', write_suggestions(tmp_path, GOOD))
    assert r.returncode == 0 and last_json(r)['rev'] == 1
    mine = get_take(srv_url, 'sample')
    assert mine['suggestions'] == GOOD['suggestions'] and mine['suggestionsRev'] == 1     # the workspace's file wins
    assert (paths.Workspace(proj).settings_dir / 'sample.suggestions.json').is_file()
    assert {f: sha(sample / f) for f in os.listdir(sample)} == before                     # app/sample/ is never written


# ------------------------------------------------------------------------------------------------------------- retry
def test_retry_after_error(bridge, tmp_path, portrait_1080):
    proj = tmp_path / 'proj'
    d = make_take(proj, '261109-120001-beef', 'error', 'The cutout stopped before the end.', file='clip.mp4', created=pipeline.now_iso())
    shutil.copyfile(portrait_1080, d / 'source.mp4')
    bridge.workspaces.append(str(proj))
    r = bridge.run('retry', '--workspace', proj, '--take', '261109-120001-beef', timeout=60)
    assert r.returncode == 0, r.stderr
    assert last_json(r) == {'take': '261109-120001-beef', 'ok': True, 'from': 'checking'}
    w = bridge.run('wait', '--workspace', proj, '--take', '261109-120001-beef', '--timeout', 180, timeout=200)
    assert w.returncode == 0 and last_json(w)['stage'] == 'ready'


def test_retry_of_a_refused_clip_exit_2_with_the_reason(bridge, tmp_path, clip_12s):
    proj = tmp_path / 'proj'
    tid = add(bridge, proj, clip_12s)['take']
    bridge.workspaces.append(str(proj))
    r = bridge.run('retry', '--workspace', proj, '--take', tid)
    assert r.returncode == 2 and r.stdout == '' and 'Trim it' in r.stderr and '12.0' in r.stderr


def test_retry_of_a_take_that_did_not_fail_exit_2(bridge, proj, ready_take):
    r = bridge.run('retry', '--workspace', proj, '--take', ready_take)
    assert r.returncode == 2 and 'not failed' in r.stderr
    r = bridge.run('retry', '--workspace', proj, '--take', 'sample')
    assert r.returncode == 2 and 'No such take' in r.stderr
    r = bridge.run('retry', '--workspace', proj, '--take', 'nope')
    assert r.returncode == 2


def wait_stage(pipe, tid, stages, seconds=120):
    deadline = time.time() + seconds
    while time.time() < deadline:
        st = pipe.get(tid)['status']['stage']
        if st in stages:
            return st
        time.sleep(0.1)
    raise AssertionError('take %s never reached %s (at %s)' % (tid, stages, st))


@pytest.fixture
def local_pipe(ws, monkeypatch, tmp_path):
    monkeypatch.setenv('FT_FAKE_MATTE', '1')
    monkeypatch.setenv('FLOORED_HOME', str(tmp_path / 'home'))
    pipe = pipeline.Pipeline(ws, words_fn=lambda path, log: words.empty())
    yield pipe
    pipe.shutdown()


def run_take(pipe, video):
    tid, path = pipe.begin_upload(os.path.basename(str(video)))
    shutil.copyfile(video, path)
    pipe.finish_upload(tid)
    assert wait_stage(pipe, tid, ('ready', 'error')) == 'ready'
    return tid


def test_retry_resumes_from_the_first_unfinished_stage(local_pipe, ws, portrait_1080):
    pipe = local_pipe
    tid = run_take(pipe, portrait_1080)
    d = ws.takes / tid
    assert json.loads((d / 'stages.json').read_text(encoding='utf-8')) == ['checking', 'cutting', 'measuring', 'shadow']
    cutout_before = (d / 'person.webm').stat().st_mtime_ns
    stage_before = (d / 'stage.mp4').stat().st_mtime_ns
    # the shadow step died half-way: a stray half-file, no marker, the take in error
    (d / 'shadow.webm').write_bytes(b'half')
    pipeline.write_json(str(d / 'stages.json'), ['checking', 'cutting', 'measuring'])
    pipeline.write_json(str(d / 'status.json'), {'stage': 'error', 'progress': 0, 'message': 'boom', 'error': 'boom'})
    assert pipe.resume_point(tid) == 'shadow'
    assert pipe.retry(tid) == 'shadow'
    assert wait_stage(pipe, tid, ('ready', 'error')) == 'ready'
    assert (d / 'person.webm').stat().st_mtime_ns == cutout_before and (d / 'stage.mp4').stat().st_mtime_ns == stage_before
    assert (d / 'shadow.webm').stat().st_size > 100                                       # drawn again, the stray file is gone
    log = (d / 'log.txt').read_text(encoding='utf-8')
    assert 'retry: resuming from shadow' in log and 'resuming: the cutout is already made' in log
    assert json.loads((d / 'stages.json').read_text(encoding='utf-8')) == ['checking', 'cutting', 'measuring', 'shadow']
    take = json.loads((d / 'take.json').read_text(encoding='utf-8'))
    assert take['k0'] > 0 and take['frames'] > 0 and take['files']['shadow'] == 'shadow.webm'


@pytest.mark.parametrize('marked, drop, expect', [
    ([], [], 'checking'),
    (['checking'], [], 'cutting'),
    (['checking', 'cutting'], ['person.webm'], 'cutting'),                    # the marker without its file is not trusted
    (['checking', 'cutting'], [], 'measuring'),
    (['cutting', 'measuring'], [], 'checking'),                               # stages count in order
])
def test_resume_point(local_pipe, ws, portrait_1080, marked, drop, expect):
    pipe = local_pipe
    tid = run_take(pipe, portrait_1080)
    d = ws.takes / tid
    pipeline.write_json(str(d / 'stages.json'), marked)
    for f in drop:
        os.remove(str(d / f))
    assert pipe.resume_point(tid) == expect


def test_retry_refuses_a_take_that_is_not_failed(local_pipe, ws, portrait_1080):
    tid = run_take(local_pipe, portrait_1080)
    with pytest.raises(pipeline.RetryError) as e:
        local_pipe.retry(tid)
    assert e.value.code == 409
    with pytest.raises(pipeline.RetryError) as e:
        local_pipe.retry('sample')
    assert e.value.code == 404


def test_wait_next_counts_a_take_made_while_the_command_was_still_starting(bridge, tmp_path):
    """On a busy computer the command takes seconds to start. floored.py notes the moment it was launched, and a take
    made after that moment is the next take, even though it was already there at the waiter's first look."""
    from ft import bridge as b
    if b._created_at(str(tmp_path)) is None:
        pytest.skip('this file system does not say when a folder was made')
    proj = tmp_path / 'proj'
    paths.Workspace(proj).ensure()
    launched = time.time()
    make_take(proj, 'made-meanwhile', 'error', 'Nope.')
    time.sleep(b.NEXT_TOLERANCE_S + 1.2)                                 # the slow start
    r = bridge.run('wait', '--workspace', proj, '--next', '--timeout', 6, env={'FLOORED_STARTED': '%.3f' % launched}, timeout=40)
    assert r.returncode == 3 and json.loads(r.stdout)['take'] == 'made-meanwhile', (r.returncode, r.stdout, r.stderr)


def test_the_launch_moment_is_believed_only_when_it_is_plausible(monkeypatch):
    now = 1_800_000_000.0
    monkeypatch.delenv('FLOORED_STARTED', raising=False)
    assert cli.command_started(now) == now
    for value, want in (('%.3f' % (now - 2.5), now - 2.5), ('%.3f' % (now - 3600), now), ('%.3f' % (now + 5), now), ('soon', now), ('', now)):
        monkeypatch.setenv('FLOORED_STARTED', value)
        assert cli.command_started(now) == pytest.approx(want), value


# --------------------------------------------------------------------------------------------- the pure pieces
def test_next_take_matches_by_snapshot_and_by_creation_time(tmp_path):
    from ft import bridge as b
    (tmp_path / 'old').mkdir()
    n = b.NextTake(str(tmp_path), started=time.time() + 10)      # 'old' was made before the command "started"
    assert n.find() is None
    (tmp_path / 'sample').mkdir()
    assert n.find() is None
    (tmp_path / 'new').mkdir()
    assert n.find() == 'new'


def test_validate_suggestions_trims_and_defaults():
    from ft import bridge as b
    assert b.validate_suggestions({'suggestions': [' a ']}) == {'suggestions': ['a'], 'smallSuggestions': []}
    with pytest.raises(b.BridgeError):
        b.validate_suggestions({'suggestions': ['a'], 'smallSuggestions': 'x'})


# ------------------------------------------------------------------------------------------------------ fix round 1
def test_requests_go_to_loopback_whatever_the_record_says(bridge, tmp_path, portrait_1080):
    """A tampered .server.json url must never receive the video: every request is built from 127.0.0.1 and the port."""
    proj = tmp_path / 'proj'
    first = add(bridge, proj, portrait_1080)
    bridge.workspaces.append(str(proj))
    wsx = paths.Workspace(proj)
    rec = server.read_server_file(wsx)
    pipeline.write_json(str(wsx.server_file), dict(rec, url='http://example.invalid:%d/' % rec['port']))
    second = add(bridge, proj, portrait_1080)                                 # would fail (DNS) if it followed the url
    assert second['take'] != first['take'] and second['url'].startswith('http://127.0.0.1:%d/' % rec['port'])
    assert 'example.invalid' not in second['url']
    got = fetch('http://127.0.0.1:%d' % rec['port'], '/api/takes/' + second['take'])[0]
    assert got == 200                                                          # it really arrived on the real server
    r = bridge.run('suggest', '--workspace', proj, '--take', second['take'], '--file', write_suggestions(tmp_path, GOOD))
    assert r.returncode == 0, r.stderr                                         # and the JSON calls too
    r = bridge.run('retry', '--workspace', proj, '--take', second['take'])
    assert r.returncode in (0, 2)                                              # reached the server (ready or still running)
    assert 'example.invalid' not in r.stderr


def test_wait_next_forgets_a_take_whose_folder_vanishes(tmp_path):
    from ft import bridge as b
    takes = tmp_path / 'takes'
    takes.mkdir()
    nxt = b.NextTake(str(takes), started=time.time())
    result = {}

    def run():
        result['v'] = b.wait_for_take(str(takes), next_take=nxt, timeout=30, poll=0.05)

    t = threading.Thread(target=run)
    t.start()
    first = takes / 'first-drop'
    first.mkdir()
    pipeline.write_json(str(first / 'status.json'), {'stage': 'queued', 'overall': 0})
    time.sleep(0.6)                                                           # wait has locked on to it
    shutil.rmtree(first)                                                      # the upload was interrupted
    time.sleep(0.4)
    second = takes / 'second-drop'
    second.mkdir()
    pipeline.write_json(str(second / 'status.json'), {'stage': 'ready', 'overall': 1})
    pipeline.write_json(str(second / 'take.json'), {'id': 'second-drop'})
    t.join(timeout=20)
    assert not t.is_alive()
    code, out = result['v']
    assert code == 0 and out['take'] == 'second-drop'
