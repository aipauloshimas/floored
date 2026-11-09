"""Preferences, "my looks" and per-take settings: kept by the server, in the user folder / the project workspace (never in
the browser, whose storage is per port)."""
import json
import threading

import pytest

from conftest import kill_tree
from ft import paths
from ft.prefs import Prefs, PrefsError


def test_defaults(tmp_path):
    p = Prefs(tmp_path).get()
    assert p == {'lastLook': None, 'brand': None, 'small': {'on': False, 'text': ''}, 'looks': []}


def test_put_patch_and_persist(tmp_path):
    p = Prefs(tmp_path)
    p.put({'lastLook': 'neon', 'brand': {'floor': '#112233', 'ink': '#ffffff'}})
    p.put({'small': {'on': True, 'text': 'hi'}})
    again = Prefs(tmp_path).get()
    assert again['lastLook'] == 'neon' and again['brand'] == {'floor': '#112233', 'ink': '#ffffff'}
    assert again['small'] == {'on': True, 'text': 'hi'}
    p.put({'brand': None})
    assert Prefs(tmp_path).get()['brand'] is None
    assert Prefs(tmp_path).get()['lastLook'] == 'neon'                      # untouched keys stay


@pytest.mark.parametrize('patch', [
    {'looks': []}, {'nope': 1}, {'lastLook': 3}, {'brand': 'red'}, {'brand': {'floor': '#112233'}},
    {'brand': {'floor': 'red', 'ink': '#fff'}}, {'brand': {'floor': '#112233', 'ink': '#ffffff', 'x': 1}},
    {'small': {'on': 'yes'}}, {'small': {'text': 'x' * 41}}, {'small': {'text': 5}}, {'small': {'color': 'red'}}, {'small': 1},
    'text', [],
])
def test_put_refuses_bad_input(tmp_path, patch):
    p = Prefs(tmp_path)
    with pytest.raises(PrefsError):
        p.put(patch)
    assert p.get()['small'] == {'on': False, 'text': ''}


def test_small_text_40_ok(tmp_path):
    assert Prefs(tmp_path).put({'small': {'on': True, 'text': 'x' * 40}})['small']['text'] == 'x' * 40


def test_same_name_replaces_look(tmp_path):
    p = Prefs(tmp_path)
    a = p.add_look('Neon night', {'k': 1})
    b = p.add_look('Other', {'k': 2})
    a2 = p.add_look('  neon NIGHT ', {'k': 3})
    assert a2 == a and a != b
    looks = p.get()['looks']
    assert len(looks) == 2
    mine = next(l for l in looks if l['id'] == a)
    assert mine['settings'] == {'k': 3} and mine['name'] == 'neon NIGHT'
    assert mine['created'].endswith('Z') and 'T' in mine['created']
    assert p.delete_look(a) is True and p.delete_look(a) is False
    assert [l['id'] for l in p.get()['looks']] == [b]


def test_look_validation(tmp_path):
    p = Prefs(tmp_path)
    for name, settings in [('', {}), ('   ', {}), ('x' * 31, {}), (5, {}), ('ok', []), ('ok', 'x'), ('ok', {'a': 'x' * 70000})]:
        with pytest.raises(PrefsError):
            p.add_look(name, settings)
    assert p.add_look('x' * 30, {'a': 'x' * 60000})
    assert len({p.add_look('look %d' % i, {}) for i in range(50)}) == 50           # unique ids


def test_corrupt_prefs_recovered(tmp_path):
    (tmp_path / 'prefs.json').write_text('{ not json', encoding='utf-8')
    p = Prefs(tmp_path)
    assert p.get()['looks'] == [] and p.get()['small'] == {'on': False, 'text': ''}
    bad = [f for f in tmp_path.iterdir() if f.name.startswith('prefs.json.bad-')]
    assert len(bad) == 1 and bad[0].read_text(encoding='utf-8') == '{ not json'
    p.put({'lastLook': 'a'})                                                       # and it works again
    assert Prefs(tmp_path).get()['lastLook'] == 'a'


def test_wrong_shape_is_corrupt_too(tmp_path):
    (tmp_path / 'prefs.json').write_text('[1, 2]', encoding='utf-8')
    assert Prefs(tmp_path).get()['looks'] == []
    assert any(f.name.startswith('prefs.json.bad-') for f in tmp_path.iterdir())


def test_partly_wrong_file_keeps_the_good_parts(tmp_path):
    (tmp_path / 'prefs.json').write_text(json.dumps({'lastLook': 'a', 'small': 'x', 'looks': [{'id': 'q'}, 4,
                                         {'id': 'z', 'name': 'N', 'settings': {}, 'created': '2026-01-01T00:00:00Z'}]}), encoding='utf-8')
    g = Prefs(tmp_path).get()
    assert g['lastLook'] == 'a' and g['small'] == {'on': False, 'text': ''}
    assert [l['id'] for l in g['looks']] == ['z']


def test_concurrent_looks_all_kept(tmp_path):
    p = Prefs(tmp_path)
    ts = [threading.Thread(target=p.add_look, args=('look %d' % i, {'i': i})) for i in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(Prefs(tmp_path).get()['looks']) == 20


# ------------------------------------------------------------------------------------------------------- the API
def test_prefs_survive_another_port(tmp_path, server_factory):
    home, ws = tmp_path / 'home', tmp_path / 'proj'
    a = server_factory(ws, {'FLOORED_HOME': str(home)})
    assert a.request('/api/prefs', 'PUT', {'lastLook': 'neon', 'brand': {'floor': '#101010', 'ink': '#eeeeee'},
                                           'small': {'on': True, 'text': 'by me'}}).status == 200
    lid = a.post_json('/api/looks', {'name': 'Mine', 'settings': {'palette': 'x'}}).json()['id']
    assert a.request('/api/takes/sample/settings', 'PUT', {'zoom': 2}).status == 200
    kill_tree(a.proc)
    b = server_factory(ws, {'FLOORED_HOME': str(home)})
    assert b.base != a.base
    got = b.get_json('/api/prefs')
    assert got['lastLook'] == 'neon' and got['brand'] == {'floor': '#101010', 'ink': '#eeeeee'}
    assert got['small'] == {'on': True, 'text': 'by me'}
    assert [l['id'] for l in b.get_json('/api/looks')] == [lid]
    assert b.get_json('/api/takes/sample/settings') == {'zoom': 2}


def test_prefs_api_validation(tmp_path, server_factory):
    srv = server_factory(tmp_path)
    r = srv.request('/api/prefs', 'PUT', {'bogus': 1})
    assert r.status == 400 and 'bogus' in r.json()['error']
    assert srv.request('/api/prefs', 'PUT', {'small': {'text': 'x' * 41}}).status == 400
    assert srv.request('/api/prefs', 'PUT', b'not json').status == 400
    assert srv.request('/api/prefs', 'PUT', []).status == 400
    assert srv.get_json('/api/prefs')['small'] == {'on': False, 'text': ''}
    assert srv.request('/api/prefs', 'POST', {}).status == 404


def test_looks_api(tmp_path, server_factory):
    srv = server_factory(tmp_path)
    assert srv.get_json('/api/looks') == []
    assert srv.post_json('/api/looks', {'name': '', 'settings': {}}).status == 400
    assert srv.post_json('/api/looks', {'name': 'a', 'settings': []}).status == 400
    assert srv.post_json('/api/looks', {'name': 'a'}).status == 400
    a = srv.post_json('/api/looks', {'name': 'A', 'settings': {'v': 1}}).json()['id']
    assert srv.post_json('/api/looks', {'name': 'a', 'settings': {'v': 2}}).json()['id'] == a
    looks = srv.get_json('/api/looks')
    assert len(looks) == 1 and looks[0]['settings'] == {'v': 2}
    assert srv.get_json('/api/prefs')['looks'] == looks
    assert srv.request('/api/looks/nope', 'DELETE').status == 404
    assert srv.request('/api/looks/..%2Fx', 'DELETE').status == 404
    assert srv.request('/api/looks/' + a, 'DELETE').status == 200
    assert srv.get_json('/api/looks') == []


def test_prefs_routes_are_guarded(tmp_path, server_factory):
    srv = server_factory(tmp_path)
    evil = {'Origin': 'https://evil.example'}
    assert srv.request('/api/prefs', 'PUT', {'lastLook': 'x'}, headers=evil).status == 403
    assert srv.request('/api/looks', 'POST', {'name': 'a', 'settings': {}}, headers=evil).status == 403
    assert srv.request('/api/looks/x', 'DELETE', headers=evil).status == 403
    assert srv.request('/api/takes/sample/settings', 'PUT', {'a': 1}, headers=evil).status == 403
    assert srv.get('/api/prefs', headers={'Host': 'evil.example'}).status == 403
    assert srv.get_json('/api/prefs')['lastLook'] is None
    assert srv.get_json('/api/takes/sample/settings') == {}


def test_take_settings_roundtrip(tmp_path, server_factory):
    srv = server_factory(tmp_path)
    ws = paths.Workspace(tmp_path)
    tid = '260101-000000-abcd'
    (ws.takes / tid).mkdir(parents=True)
    (ws.takes / tid / 'take.json').write_text(json.dumps({'id': tid, 'name': 'T'}), encoding='utf-8')
    assert srv.get_json('/api/takes/%s/settings' % tid) == {}
    body = {'palette': {'id': 'brand', 'floor': '#000000'}, 'words': ['é', 'b']}
    assert srv.request('/api/takes/%s/settings' % tid, 'PUT', body).status == 200
    assert srv.get_json('/api/takes/%s/settings' % tid) == body
    assert json.loads((ws.root / 'settings' / (tid + '.json')).read_text(encoding='utf-8')) == body
    assert srv.request('/api/takes/%s/settings' % tid, 'PUT', {'x': 1}).status == 200       # replaces
    assert srv.get_json('/api/takes/%s/settings' % tid) == {'x': 1}
    assert srv.request('/api/takes/%s/settings' % tid, 'PUT', []).status == 400
    assert srv.request('/api/takes/%s/settings' % tid, 'PUT', b'{bad').status == 400


def test_take_settings_unknown_or_unsafe_take(tmp_path, server_factory):
    srv = server_factory(tmp_path)
    ws = paths.Workspace(tmp_path)
    for bad in ('nope', '..', '%2e%2e', '..%2f..%2fx', 'a%5Cb', '.hidden'):
        assert srv.get('/api/takes/%s/settings' % bad).status in (400, 404), bad
        assert srv.request('/api/takes/%s/settings' % bad, 'PUT', {'a': 1}).status in (400, 404), bad
    assert not (ws.root / 'settings').exists() or not any((ws.root / 'settings').iterdir())
    assert not (tmp_path / 'x.json').exists()


def test_sample_settings_go_to_workspace(tmp_path, server_factory):
    before = sorted(p.name for p in paths.SAMPLE_DIR.iterdir())
    srv = server_factory(tmp_path)
    assert srv.request('/api/takes/sample/settings', 'PUT', {'k': 1}).status == 200
    f = paths.Workspace(tmp_path).root / 'settings' / 'sample.json'
    assert json.loads(f.read_text(encoding='utf-8')) == {'k': 1}
    assert sorted(p.name for p in paths.SAMPLE_DIR.iterdir()) == before             # the sample is never written
    assert not (paths.SAMPLE_DIR / 'settings').exists() and not (paths.SAMPLE_DIR / 'sample.json').exists()
