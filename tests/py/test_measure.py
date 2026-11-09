"""ft.measure: feet, height and k0 from a cutout, and the take check's warnings."""
import json
import time

import pytest

from conftest import PERSON_FEET, PERSON_FPS, PERSON_FRAMES, PERSON_H, PERSON_TOP, PERSON_W
from ft import calibration as cal
from ft import paths
from ft.measure import measure, take_warnings
from ft.media import PipelineError

W, H = PERSON_W, PERSON_H
GOOD_INFO = {'w': 1080, 'h': 1920, 'dur': 5.0, 'hdr': False}


_CACHE = {}


def _measure(path):
    if path not in _CACHE:                                           # the same clip is measured by several tests
        _CACHE[path] = measure(path, W, H, PERSON_FPS)
    return _CACHE[path]


def _codes(info, fields, diag):
    return [w['code'] for w in take_warnings(info, fields, diag)]


def test_feet_and_k0(person_basic):
    fields, diag = _measure(person_basic)
    assert abs(fields['feet']['x'] - PERSON_FEET[0]) <= 3
    assert abs(fields['feet']['y'] - PERSON_FEET[1]) <= 3
    assert abs(fields['height'] - (PERSON_FEET[1] - PERSON_TOP)) <= 3
    assert fields['k0'] == pytest.approx(cal.K0_SCALE * cal.K0_REF_HEIGHT / fields['height'], rel=1e-3)
    assert fields['edgeFrames'] == []
    assert diag['frames'] == PERSON_FRAMES
    assert diag['people'] == 0


def test_edge_frames(person_edge):
    fields, _ = _measure(person_edge)
    assert fields['edgeFrames'] == list(range(10, 21))


def test_second_person_share(person_two):
    _, diag = _measure(person_two)
    assert diag['people'] == pytest.approx(1.0)


def test_progress_callback(person_basic):
    seen = []
    measure(person_basic, W, H, PERSON_FPS, seen.append)
    assert seen and seen[-1] <= PERSON_FRAMES


@pytest.mark.parametrize("fixture,codes", [("person_edge", {"edge"}), ("person_moving", {"moved"}),
                                           ("person_step", {"moved"}), ("person_glitch", set()),
                                           ("person_two", {"people"}), ("person_empty", {"noperson"}),
                                           ("person_nolegs", {"legs"}), ("person_hand_low", set())])
def test_warnings(fixture, codes, request):
    fields, diag = _measure(request.getfixturevalue(fixture))
    assert set(_codes(GOOD_INFO, fields, diag)) == codes


def test_clean_take_has_no_warnings(person_basic):
    fields, diag = _measure(person_basic)
    assert take_warnings(GOOD_INFO, fields, diag) == []


def test_unreadable_cutout_raises(tmp_path):
    with pytest.raises(PipelineError):
        measure(tmp_path / 'missing.webm', W, H, PERSON_FPS)
    bad = tmp_path / 'corrupt.webm'
    bad.write_bytes(b'this is not a video' * 100)
    with pytest.raises(PipelineError) as e:
        measure(bad, W, H, PERSON_FPS)
    assert "couldn't read" in str(e.value)


def test_empty_cutout_does_not_raise(person_empty):
    fields, diag = _measure(person_empty)
    assert diag['found'] is False and fields['edgeFrames'] == []


def test_edge_message_has_the_times(person_edge):
    fields, diag = _measure(person_edge)
    msg = [w for w in take_warnings(GOOD_INFO, fields, diag) if w['code'] == 'edge'][0]['message']
    assert 'around 0.6 s' in msg                                    # frames 10-20 at 24 fps: the middle is 0.6 s


# --- the info-driven warnings: no cutout needed, a clean measurement stands in ------------------------------------

CLEAN_FIELDS = {'edgeFrames': []}
CLEAN_DIAG = {'drift': 0.0, 'people': 0.0, 'areaMedian': 0.2, 'width': 1080, 'frames': 24}


@pytest.mark.parametrize("override,expected", [
    ({'dur': cal.SHORT_S - 0.5}, ['short']),
    ({'dur': cal.LONG_S + 0.5}, ['long']),
    ({'dur': cal.MAX_S + 1}, ['long']),
    ({'w': 1920, 'h': 1080}, ['landscape', 'lowres', 'aspect']),
    ({'w': 540, 'h': 960}, ['lowres']),
    ({'w': 1080, 'h': 2400}, ['aspect']),
    ({'hdr': True}, ['hdr']),
])
def test_info_warnings(override, expected):
    info = dict(GOOD_INFO, **override)
    assert _codes(info, CLEAN_FIELDS, CLEAN_DIAG) == expected


@pytest.mark.parametrize("dur", [10.02, 10.04, 10.2])
def test_long_message_does_not_contradict_itself(dur):
    msg = [w for w in take_warnings(dict(GOOD_INFO, dur=dur), CLEAN_FIELDS, CLEAN_DIAG) if w['code'] == 'long'][0]['message']
    assert msg == 'This clip is just over 10 seconds. It still works, but 8 seconds or less looks best.'
    assert 'a little over' not in msg and '10.0 s' not in msg


def test_boundaries_do_not_warn():
    for dur in (cal.SHORT_S, cal.LONG_S):
        assert _codes(dict(GOOD_INFO, dur=dur), CLEAN_FIELDS, CLEAN_DIAG) == []
    assert _codes(dict(GOOD_INFO, h=cal.LOWRES_H, w=720), CLEAN_FIELDS, CLEAN_DIAG) == []


def test_moved_threshold_scales_with_width():
    d = dict(CLEAN_DIAG, drift=cal.MOVED_PX * 1.5)
    assert _codes(GOOD_INFO, CLEAN_FIELDS, d) == ['moved']
    assert _codes(GOOD_INFO, CLEAN_FIELDS, dict(d, width=2160)) == []       # the same drift in a 4K proxy is smaller


def test_warning_order():
    info = dict(GOOD_INFO, dur=1.0, w=1920, h=1080, hdr=True)
    diag = dict(CLEAN_DIAG, drift=99, people=0.9, areaMedian=0.0)
    assert _codes(info, {'edgeFrames': [1, 2]}, diag) == ['short', 'landscape', 'lowres', 'aspect', 'hdr', 'edge',
                                                          'moved', 'people', 'noperson']
    # legs lost: 'legs' takes the place of 'moved'
    assert _codes(info, {'edgeFrames': [1, 2]}, dict(diag, legsRatio=1.0)) == [
        'short', 'landscape', 'lowres', 'aspect', 'hdr', 'edge', 'legs', 'people', 'noperson']


def test_lost_legs_hide_the_moved_warning():
    # without legs the feet are guessed, so a drift says nothing about the creator moving: one clear message only
    d = dict(CLEAN_DIAG, drift=cal.MOVED_PX * 3, legsRatio=cal.LEGS_RATIO + 0.1)
    assert _codes(GOOD_INFO, CLEAN_FIELDS, d) == ['legs']
    assert _codes(GOOD_INFO, CLEAN_FIELDS, dict(d, legsRatio=cal.LEGS_RATIO - 0.1)) == ['moved']


def test_hand_at_hip_height_does_not_move_the_feet(person_hand_low):
    fields, diag = _measure(person_hand_low)
    assert abs(fields['feet']['x'] - PERSON_FEET[0]) <= 3 and abs(fields['feet']['y'] - PERSON_FEET[1]) <= 3
    assert diag['drift'] <= 3


def test_messages_are_plain():
    info = dict(GOOD_INFO, dur=1.0, w=1920, h=1080, hdr=True)
    diag = dict(CLEAN_DIAG, drift=99, people=0.9, areaMedian=0.0)
    warnings = take_warnings(info, {'edgeFrames': [1, 2]}, diag)
    warnings += [w for w in take_warnings(info, {'edgeFrames': []}, dict(diag, legsRatio=1.0)) if w['code'] == 'legs']
    assert len(warnings) == 10
    for w in warnings:
        text = w['message']
        assert text and len(text) < 220, w
        for bad in ('matte', 'k0', 'alpha', 'RVM', 'blob', 'px'):
            assert bad not in text, (w['code'], bad)


# --- the shipped sample --------------------------------------------------------------------------------------------

def test_sample_matches_take_json():
    take = json.loads((paths.SAMPLE_DIR / 'take.json').read_text(encoding='utf-8'))
    t0 = time.time()
    fields, diag = measure(paths.SAMPLE_DIR / 'person.webm', take['w'], take['h'], take['fps'])
    print('measure(sample) took %.1f s' % (time.time() - t0))
    assert abs(fields['feet']['x'] - take['feet']['x']) <= 2
    assert abs(fields['feet']['y'] - take['feet']['y']) <= 2
    assert fields['k0'] == pytest.approx(take['k0'], rel=0.01)
    assert fields['edgeFrames'] == take['edgeFrames']
    print('sample drift %.1f px' % diag['drift'])
    info = {'w': take['w'], 'h': take['h'], 'dur': take['dur'], 'fps': take['fps'], 'hdr': False}
    assert 'moved' not in _codes(info, fields, diag)
