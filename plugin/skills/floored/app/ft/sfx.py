"""floored: sound effects, synthesised in numpy (no sample files, no packages beyond numpy).

    synth(events, dur, sr=48000) -> float32 array (frames, 2), stereo, peak-normalised to -3 dBFS
    write_wav(path, audio, sr)   -> 16-bit PCM WAV
    python sfx.py events.json out.wav [--dur 5.04]
        events.json is a list [{t, kind, gain}] (what engine.events() returns) or {"events": [...], "dur": 5.04}

The same events always give the same samples: each event's noise is seeded from its kind, time and index.

Kinds (SPEC "Sound events"): whoosh, swarm, land, pop, tick, riser, hit, boom. Unknown kinds are skipped.
Timing: every sound starts at exactly the event time (its first sample is at t). The transient kinds (land, pop,
tick, hit, boom) are loudest within a few ms of t. whoosh and swarm are noise swells that peak a little after t, and
the riser peaks at its end (it builds up to whatever follows it).
"""
import json
import sys
import wave
import zlib

import numpy as np

SR = 48000
PEAK_DB = -3.0

# Level of each kind at gain 1.0, relative to the others (every sound is first normalised to a peak of 1.0).
# Low sounds are trimmed less because small speakers hardly play them; noise swells sit lower than the thumps.
TRIM = {'whoosh': 0.55, 'swarm': 0.45, 'land': 0.9, 'pop': 0.6, 'tick': 0.5, 'riser': 0.5, 'hit': 1.0, 'boom': 1.0}


# -- building blocks ------------------------------------------------------------------------------------------
def _seed(kind, t, i):
    return zlib.crc32(('%s|%d|%d' % (kind, round(t * 1000), i)).encode('utf-8'))


def _sweep_noise(n, f0, f1, width_oct, sr, rng, channels=1, block=1024):
    """Band-passed white noise whose centre frequency glides f0 -> f1 (exponentially) over n samples.
    A Gaussian band (FWHM = width_oct octaves) applied block by block with Hann overlap-add. Returns (channels, n)."""
    hop = block // 2
    nblocks = (n + block) // hop + 1
    total = (nblocks + 1) * hop + block
    x = rng.standard_normal((channels, total))
    win = np.hanning(block + 1)[:-1]                       # periodic Hann: sums to 1 at 50 % overlap
    freqs = np.fft.rfftfreq(block, 1.0 / sr)
    logf = np.log2(np.maximum(freqs, 1.0))
    sigma = width_oct / 2.355
    out = np.zeros((channels, total))
    for k in range(nblocks):
        centre = k * hop + block / 2 - block               # centre of this block in output coordinates
        u = min(1.0, max(0.0, centre / max(n, 1)))
        fc = f0 * (f1 / f0) ** u
        gain = np.exp(-0.5 * ((logf - np.log2(fc)) / sigma) ** 2)
        spec = np.fft.rfft(x[:, k * hop:k * hop + block] * win, axis=-1) * gain
        out[:, k * hop:k * hop + block] += np.fft.irfft(spec, n=block, axis=-1)
    return out[:, block:block + n]


def _stereo(noise3, width):
    """noise3 = (3, n): common + two independent channels -> (n, 2); width 0 = mono, 1 = fully decorrelated."""
    a, b = np.sqrt(1.0 - width), np.sqrt(width)
    return np.stack([a * noise3[0] + b * noise3[1], a * noise3[0] + b * noise3[2]], axis=1)


def _mono(x):
    return np.stack([x, x], axis=1)


def _tone(n, sr, freq_t):
    """Sine whose instantaneous frequency (Hz) is the array freq_t."""
    return np.sin(2 * np.pi * np.cumsum(freq_t) / sr)


def _fade_out(x, sr, ms=2.0):
    k = min(len(x), max(1, int(sr * ms / 1000)))
    x[-k:] *= np.linspace(1.0, 0.0, k)[:, None]
    return x


def _highpassed_click(n, sr, rng, tau_ms):
    """A short click: differentiated noise with a fast exponential decay."""
    noise = np.diff(rng.standard_normal(n + 1))
    return noise * np.exp(-np.arange(n) / sr / (tau_ms / 1000.0))


# -- the eight sounds (each returns (n, 2), unnormalised) ----------------------------------------------------------
def _whoosh(sr, rng, dur=0.35, f0=500.0, f1=2500.0, width=1.3, spread=0.5):
    n = int(dur * sr)
    u = np.linspace(0.0, 1.0, n)
    env = np.sin(np.pi * u ** 0.5) ** 2                    # fast swell (peak at a quarter), long smooth tail
    return _stereo(_sweep_noise(n, f0, f1, width, sr, rng, channels=3), spread) * env[:, None]


def _swarm(sr, rng):
    return _whoosh(sr, rng, dur=0.7, f0=400.0, f1=3200.0, width=2.2, spread=0.9)


def _land(sr, rng):
    n = int(0.18 * sr)
    t = np.arange(n) / sr
    body = _tone(n, sr, 70.0 + 50.0 * np.exp(-t / 0.02)) * np.exp(-t / 0.045)    # 70 Hz, a small pitch drop for punch
    body += 0.5 * _tone(n, sr, 2 * (70.0 + 50.0 * np.exp(-t / 0.02))) * np.exp(-t / 0.03)   # 2nd partial: small speakers
    k = int(0.005 * sr)
    body[:k] += 0.8 * _highpassed_click(k, sr, rng, 1.2) / 2.0                     # the 5 ms click
    return _mono(body)


def _pop(sr, rng):
    n = int(0.08 * sr)
    t = np.arange(n) / sr
    env = np.minimum(1.0, t / 0.002) * np.exp(-t / 0.025)                          # 2 ms attack, then decay
    return _mono(_tone(n, sr, 600.0 * 0.5 ** (t / 0.08)) * env)                    # 600 -> 300 Hz


def _tick(sr, rng):
    n = int(0.003 * sr)
    t = np.arange(n) / sr
    click = _highpassed_click(n, sr, rng, 0.7) + 2.0 * np.sin(2 * np.pi * 3200.0 * t) * np.exp(-t / 0.001)
    return _mono(click)


def _riser(sr, rng):
    n = int(0.6 * sr)
    t = np.arange(n) / sr
    u = t / 0.6
    noise = _sweep_noise(n, 300.0, 5000.0, 2.2, sr, rng, channels=3)
    tone = _tone(n, sr, 200.0 * (900.0 / 200.0) ** u)
    mix = _stereo(noise / max(np.abs(noise).max(), 1e-9), 0.7) * 0.7 + _mono(tone) * 0.4
    return mix * (u ** 2.0)[:, None]                                               # builds up to its end


def _hit(sr, rng):
    n = int(0.3 * sr)
    t = np.arange(n) / sr
    thump = _tone(n, sr, 50.0 + 60.0 * np.exp(-t / 0.015)) * np.minimum(1.0, t / 0.001) * np.exp(-t / 0.09)
    m = int(0.08 * sr)
    burst = _sweep_noise(m, 2500.0, 800.0, 3.0, sr, rng, channels=1)[0] * np.exp(-np.arange(m) / sr / 0.02)
    out = _mono(thump)
    out[:m] += 0.6 * _mono(burst / max(np.abs(burst).max(), 1e-9))
    return out


def _boom(sr, rng):
    n = int(0.8 * sr)
    t = np.arange(n) / sr
    f = 45.0 + 35.0 * np.exp(-t / 0.05)
    body = _tone(n, sr, f) * np.minimum(1.0, t / 0.003) * np.exp(-t / 0.28)
    body += 0.5 * _tone(n, sr, 2 * f) * np.exp(-t / 0.18)
    rumble = _sweep_noise(n, 120.0, 50.0, 1.5, sr, rng, channels=1)[0]
    body += 0.3 * rumble / max(np.abs(rumble).max(), 1e-9) * np.exp(-t / 0.2)
    return _mono(body)


MAKERS = {'whoosh': _whoosh, 'swarm': _swarm, 'land': _land, 'pop': _pop, 'tick': _tick, 'riser': _riser,
          'hit': _hit, 'boom': _boom}


def render_event(kind, t, gain, i, sr=SR):
    """One event as a (n, 2) float array with a peak of trim * gain (before the final mix normalisation)."""
    wave_ = MAKERS[kind](sr, np.random.default_rng(_seed(kind, t, i)))
    peak = np.abs(wave_).max()
    if peak > 0:
        wave_ = wave_ / peak
    return _fade_out(wave_, sr) * (TRIM[kind] * float(gain))


# -- the mix --------------------------------------------------------------------------------------------------
def _clean(events):
    """Valid events only, sorted by time: [(t, kind, gain, original index)]."""
    out = []
    for i, ev in enumerate(events or []):
        try:
            t, kind, gain = float(ev['t']), str(ev['kind']), float(ev.get('gain', 1.0))
        except (KeyError, TypeError, ValueError):
            continue
        if kind in MAKERS and t >= 0 and gain > 0:
            out.append((t, kind, gain, i))
    return sorted(out)


def synth(events, dur, sr=SR):
    """Mix the events into a stereo float32 array of round(dur * sr) frames, peak-normalised to -3 dBFS."""
    n = int(round(float(dur) * sr))
    mix = np.zeros((n, 2))
    for t, kind, gain, i in _clean(events):
        start = int(round(t * sr))
        if start >= n:
            continue
        w = render_event(kind, t, gain, i, sr)
        w = w[:n - start]
        mix[start:start + len(w)] += w
    peak = np.abs(mix).max()
    if peak > 0:
        mix *= 10 ** (PEAK_DB / 20.0) / peak
    return mix.astype(np.float32)


def write_wav(path, audio, sr=SR):
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).round().astype('<i2')
    with wave.open(path, 'wb') as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# -- the timing check -----------------------------------------------------------------------------------------
def report(events, dur, sr=SR):
    """Rows for the timing check. Each event is rendered alone; onset = first sample above 5 % of its own peak and
    peak = its loudest sample, both in seconds after the event time. Also where the loudest points of the full mix are."""
    rows = []
    for t, kind, gain, i in _clean(events):
        w = render_event(kind, t, gain, i, sr)
        env = np.abs(w).max(axis=1)
        pk = env.max()
        rows.append({'t': t, 'kind': kind, 'gain': gain, 'onset': float(np.argmax(env > 0.05 * pk)) / sr,
                     'peak': float(np.argmax(env)) / sr, 'length': len(w) / sr})
    mix = synth(events, dur, sr)
    return rows, mix


def mix_peaks(mix, sr=SR, top=12, win_ms=10):
    """Local maxima of the 10 ms peak envelope of the mix above 25 % of its maximum: [(time, level 0..1)]."""
    k = max(1, int(sr * win_ms / 1000))
    env = np.abs(mix).max(axis=1)
    m = len(env) // k * k
    blocks = env[:m].reshape(-1, k)
    pk = blocks.max(axis=1)
    idx = blocks.argmax(axis=1) + np.arange(len(pk)) * k
    lim = 0.25 * pk.max() if len(pk) else 0
    found = [(float(idx[j]) / sr, float(pk[j])) for j in range(len(pk))
             if pk[j] >= lim and pk[j] >= (pk[j - 1] if j else 0) and pk[j] >= (pk[j + 1] if j + 1 < len(pk) else 0)]
    return sorted(found, key=lambda p: -p[1])[:top]


def main(argv):
    if len(argv) < 3 or argv[1] in ('-h', '--help'):
        print(__doc__)
        return 2
    src, dst = argv[1], argv[2]
    with open(src, encoding='utf-8') as f:
        data = json.load(f)
    events = data['events'] if isinstance(data, dict) else data
    dur = float(argv[argv.index('--dur') + 1]) if '--dur' in argv else (data.get('dur') if isinstance(data, dict) else None)
    if dur is None:
        dur = max([float(e['t']) for e in events] + [0.0]) + 1.0
    rows, mix = report(events, dur)
    write_wav(dst, mix)
    print('wrote %s  %.3f s  %d Hz stereo  peak %.1f dBFS' % (dst, len(mix) / SR, SR,
                                                             20 * np.log10(max(np.abs(mix).max(), 1e-9))))
    print('%-8s %-7s %5s  %8s %8s  %s' % ('t (s)', 'kind', 'gain', 'onset', 'peak', 'sound length'))
    for r in rows:
        print('%-8.3f %-7s %5.2f  +%6.1f ms +%6.1f ms  %.2f s' % (r['t'], r['kind'], r['gain'], r['onset'] * 1000,
                                                                  r['peak'] * 1000, r['length']))
    print('loudest points of the mix (time s, level):', ', '.join('%.3f (%.2f)' % p for p in mix_peaks(mix)))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
