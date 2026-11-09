"""ft.words: words and their times from the speech (faster-whisper, optional)."""
import time

import pytest

from ft import paths, pipeline, words
from ft.words import available, transcribe

SAMPLE = paths.SAMPLE_DIR
slow = pytest.mark.slow
needs_words = pytest.mark.skipif(not available(), reason='faster-whisper or its "base" model is not installed')


@slow
@needs_words
def test_sample_words():
    t0 = time.time()
    r = transcribe(SAMPLE / 'audio.m4a', print)
    print('wall time: %.1f s' % (time.time() - t0))
    assert r['language'] == 'en'
    assert [w['word'].lower().strip('.,') for w in r['words']][:3] == ["here's", 'how', 'you']
    assert 1.2 <= r['words'][0]['start'] <= 1.7
    for w in r['words']:
        assert w['word'] == w['word'].strip()
        assert w['end'] >= w['start'] >= 0
        assert round(w['start'], 3) == w['start'] and round(w['end'], 3) == w['end']
    assert r['transcript'].lower().startswith("here's how you")


def test_unavailable_gives_empty_words(monkeypatch, tmp_path):
    monkeypatch.setattr(words, 'available', lambda: False)
    logged = []
    assert transcribe(tmp_path / 'nothing.m4a', logged.append) == {'transcript': '', 'language': None, 'words': []}


def test_available_is_false_without_the_model_file(monkeypatch, tmp_path):
    monkeypatch.setenv('FLOORED_HOME', str(tmp_path))
    assert words.available() is False
    assert words.model_dir() == tmp_path / 'models' / 'faster-whisper-base'


def test_available_is_false_without_the_package(monkeypatch, tmp_path):
    model = tmp_path / 'models' / 'faster-whisper-base'
    model.mkdir(parents=True)
    (model / 'model.bin').write_bytes(b'x')
    monkeypatch.setenv('FLOORED_HOME', str(tmp_path))
    monkeypatch.setitem(__import__('sys').modules, 'faster_whisper', None)       # makes `import faster_whisper` fail
    assert words.available() is False


def test_available_does_not_load_the_model(monkeypatch, tmp_path):
    model = tmp_path / 'models' / 'faster-whisper-base'
    model.mkdir(parents=True)
    (model / 'model.bin').write_bytes(b'not a real model')
    monkeypatch.setenv('FLOORED_HOME', str(tmp_path))
    monkeypatch.setattr(words, '_model', None)
    pytest.importorskip('faster_whisper')
    assert words.available() is True
    assert words._model is None


def test_words_stage_without_whisper_stores_nothing_and_no_warning(monkeypatch, tmp_path):
    monkeypatch.setattr(words, 'available', lambda: False)
    logged = []
    fields = pipeline.words_fields(tmp_path / 'source.mp4', True, logged.append)
    assert fields == {'transcript': '', 'language': None, 'words': []}
    assert 'warnings' not in fields


def test_words_stage_without_sound_skips_the_model(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise AssertionError('must not transcribe a clip with no sound')
    monkeypatch.setattr(words, 'available', lambda: True)
    monkeypatch.setattr(words, 'transcribe', boom)
    assert pipeline.words_fields(tmp_path / 'source.mp4', False, print) == {'transcript': '', 'language': None, 'words': []}


def test_words_stage_maps_the_result(monkeypatch, tmp_path):
    result = {'transcript': 'Hi there.', 'language': 'en',
              'words': [{'word': 'Hi', 'start': 0.1, 'end': 0.3}, {'word': 'there.', 'start': 0.3, 'end': 0.6}]}
    monkeypatch.setattr(words, 'available', lambda: True)
    monkeypatch.setattr(words, 'transcribe', lambda p, log: result)
    assert pipeline.words_fields(tmp_path / 'source.mp4', True, print) == result


def test_words_stage_survives_a_failed_transcription(monkeypatch, tmp_path):
    def broken(p, log):
        raise RuntimeError('decoder fell over')
    logged = []
    monkeypatch.setattr(words, 'available', lambda: True)
    monkeypatch.setattr(words, 'transcribe', broken)
    assert pipeline.words_fields(tmp_path / 'source.mp4', True, logged.append) == {'transcript': '', 'language': None, 'words': []}
    assert any('decoder fell over' in m for m in logged)


class _Seg:
    def __init__(self, text, no_speech_prob, words=()):
        self.text, self.no_speech_prob = text, no_speech_prob
        self.words = [type('W', (), {'word': w, 'start': 0.1, 'end': 0.4})() for w in words]


class _Model:
    def __init__(self, segs):
        self.segs, self.calls = segs, []

    def transcribe(self, path, **kw):
        self.calls.append(kw)
        return iter(self.segs), type('I', (), {'language': 'en'})()


def test_transcribe_skips_silence_and_unlikely_speech(monkeypatch, tmp_path):
    # a take with no speech made the model invent "1.5% 1.5% 1.5%": voice detection on, and doubtful segments dropped
    fake = _Model([_Seg('1.5%', 0.69, ['1.5%']), _Seg('Steal this trick.', 0.05, ['Steal', 'this', 'trick.'])])
    monkeypatch.setattr(words, 'available', lambda: True)
    monkeypatch.setattr(words, '_load', lambda log: fake)
    r = transcribe(tmp_path / 'take.m4a', print)
    assert fake.calls[0].get('vad_filter') is True
    assert r['transcript'] == 'Steal this trick.'
    assert [w['word'] for w in r['words']] == ['Steal', 'this', 'trick.']


def test_transcribe_all_doubtful_gives_no_language(monkeypatch, tmp_path):
    fake = _Model([_Seg('1.5%', 0.69, ['1.5%'])])
    monkeypatch.setattr(words, 'available', lambda: True)
    monkeypatch.setattr(words, '_load', lambda log: fake)
    assert transcribe(tmp_path / 'take.m4a', print) == {'transcript': '', 'language': None, 'words': []}


def test_model_loads_from_the_local_folder_only(monkeypatch, tmp_path):
    """The privacy promise: the speech model is read from <user dir>/models/..., with local_files_only, never fetched."""
    import sys
    import types
    monkeypatch.setenv('FLOORED_HOME', str(tmp_path))
    calls = []

    class FakeWhisperModel:
        def __init__(self, *args, **kw):
            calls.append((args, kw))

    fake_module = types.ModuleType('faster_whisper')
    fake_module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, 'faster_whisper', fake_module)
    monkeypatch.setattr(words, '_model', None)
    model = words._load(lambda text: None)
    assert isinstance(model, FakeWhisperModel) and len(calls) == 1
    args, kw = calls[0]
    assert kw.get('local_files_only') is True
    target = args[0] if args else kw.get('model_size_or_path')
    assert target == str(tmp_path / 'models' / 'faster-whisper-base')       # a folder path, not a model name to download
