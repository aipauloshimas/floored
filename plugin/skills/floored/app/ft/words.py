"""floored: the words in a take's speech, with their times (faster-whisper, optional).

The default text on the floor is the creator's own speech, and the word times drive the "On your voice" pace. This is
the optional part: when faster-whisper or its model is not installed, available() is False and a take simply gets
no words (typed and suggested text still work). Task "doctor" installs both on consent.

  available()                  cheap: the package imports and the model file exists (nothing is loaded)
  transcribe(media_path, log)  {"transcript", "language", "words": [{"word", "start", "end"}]}  (seconds, 3 decimals)

Model: "base", CPU, int8, language auto-detected. It is read from  <user dir>/models/faster-whisper-base/  with
local_files_only, so nothing touches the network after setup. The model loads on the first call and stays for the process.
"""
import importlib.util
import threading

from ft import paths

MODEL_NAME = 'base'
MODEL_FOLDER = 'faster-whisper-base'
NO_SPEECH_MAX = 0.6              # a stretch the model rates more likely silence than speech is dropped (calibration, Task 22)

_model = None
_lock = threading.Lock()


def model_dir():
    return paths.user_dir() / 'models' / MODEL_FOLDER


def available() -> bool:
    """True when faster_whisper can be imported and the model file is in place. Does not import it or load the model."""
    try:
        if importlib.util.find_spec('faster_whisper') is None:
            return False
    except (ImportError, ValueError):               # a None entry in sys.modules makes find_spec raise ValueError
        return False
    return (model_dir() / 'model.bin').is_file()


def _load(log):
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            log('loading the speech model')
            _model = WhisperModel(str(model_dir()), device='cpu', compute_type='int8', local_files_only=True)
        return _model


def empty():
    return {'transcript': '', 'language': None, 'words': []}


def transcribe(media_path, log) -> dict:
    """Word timestamps of the speech in a video or audio file. The empty result when speech recognition is not set up."""
    if not available():
        log('speech recognition is not installed: words = []')
        return empty()
    model = _load(log)
    # voice detection first: on a take with no speech the model otherwise invents text ("1.5% 1.5% 1.5%")
    segments, info = model.transcribe(str(media_path), word_timestamps=True, language=None, vad_filter=True)
    words, pieces = [], []
    for seg in segments:                            # a generator: the decoding happens as it is read
        # voice detection has already cut the silences; this catches what it lets through. Whisper's own rule also asks
        # for a low avg_logprob, but the invented text scored -0.55, so the probability alone decides (speech under
        # loud music could be dropped: then the take simply has no words, and typed text still works).
        if seg.no_speech_prob > NO_SPEECH_MAX:
            log('skipped a stretch that is probably not speech: %r' % seg.text.strip())
            continue
        pieces.append(seg.text.strip())
        for w in seg.words or []:
            text = (w.word or '').strip()
            if text:
                words.append({'word': text, 'start': round(float(w.start), 3), 'end': round(float(w.end), 3)})
    if not words:
        return empty()
    return {'transcript': ' '.join(p for p in pieces if p), 'language': info.language, 'words': words}
