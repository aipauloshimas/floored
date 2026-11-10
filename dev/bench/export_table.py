#!/usr/bin/env python3
"""Export table (design 15.4): for every exported mp4 in a folder, check it against the take it came from and print a
markdown table, one row per file, pass/fail per row. Exit code 1 when any row fails.

    python dev/bench/export_table.py FOLDER [--take take.json|video] [--out table.md]

FOLDER is searched recursively for *.mp4 (an export folder's work files, `render.mp4` and `video.mp4`, are skipped, and so is
anything in an export folder that is not the named final `<name> - floored.mp4`). The take each file
is judged against is, in order: --take (a take.json, or the source video itself); the `takeId` in a sibling job.json
(looked up in FOLDER/../../takes/<id>/take.json, a workspace's exports/<stamp>/ layout); the repo's sample take.

What a row must satisfy (the approved plan's export check, the same rule the app applies in ft/export.py check_output):
  size        = the take's out size (1080x1920, or 2160x3840 for a 4K take)
  fps         = the take's fps, and the same frame count
  video rate  >= 0.98 x max(take bitrate, 8 Mbps); the raw Mbps is always printed too
  loudness    = -14 LUFS +- 1 integrated, true peak <= -1.0 dBTP (+0.1 dB of measuring slack); a file with no audio is judged
                on size, fps and bitrate only and its audio columns say "none" (reported, not a failure, when the take has none)
  audio       = AAC at 48 kHz
Needs ffmpeg and ffprobe on PATH; the standard library only.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from fractions import Fraction

MIN_MBPS = 8.0
BITRATE_TOLERANCE = 0.98          # the share of max(take, 8 Mbps) this table counts as reached (the export itself never stops on the bitrate)
LUFS, LUFS_TOL, TP_MAX, TP_SLACK = -14.0, 1.0, -1.0, 0.1
SR = 48000
HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE_TAKE = os.path.normpath(os.path.join(HERE, '..', '..', 'plugin', 'skills', 'floored', 'app', 'sample', 'take.json'))


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr


def rate_of(text):
    """'24', '24/1', '30000/1001', and a plain number as take.json's `fps` may hold it (24, 23.976, '29.97', a string)
    -> Fraction. A decimal that is an NTSC rate snaps to its exact ratio (23.976 -> 24000/1001). Anything unreadable -> 0."""
    text = str(text if text not in (None, '') else '0/1').strip()
    try:
        if '/' in text:
            num, _, den = text.partition('/')
            return Fraction(int(num), int(den)) if int(den) else Fraction(0)
        value = Fraction(text)
    except (ValueError, ZeroDivisionError):
        return Fraction(0)
    for n in (24000, 30000, 60000):
        if value.denominator != 1 and abs(float(value) - n / 1001.0) < 0.005:
            return Fraction(n, 1001)
    return value


def probe(path):
    """Size, r_frame_rate, decoded frame count, video bitrate (packet bytes over the stream's own duration), audio streams."""
    code, out, err = run(['ffprobe', '-v', 'error', '-count_frames', '-show_entries',
                          'stream=index,codec_type,codec_name,width,height,r_frame_rate,nb_read_frames,sample_rate,channels'
                          ':packet=size,stream_index', '-of', 'json', path])
    if code:
        raise RuntimeError('ffprobe: ' + err.strip()[-200:])
    j = json.loads(out)
    streams = j.get('streams') or []
    v = next((s for s in streams if s.get('codec_type') == 'video'), {})
    a = [s for s in streams if s.get('codec_type') == 'audio']
    rate = rate_of(v.get('r_frame_rate'))
    frames = int(v.get('nb_read_frames') or 0)
    vbytes = sum(int(p.get('size') or 0) for p in (j.get('packets') or []) if p.get('stream_index') == v.get('index', 0))
    dur = float(frames / rate) if rate and frames else 0.0
    return {'w': v.get('width'), 'h': v.get('height'), 'rate': rate, 'frames': frames, 'codec': v.get('codec_name'),
            'bitrate': vbytes * 8 / dur if dur else 0.0,
            'audio': [{'codec': s.get('codec_name'), 'rate': int(s.get('sample_rate') or 0)} for s in a]}


def loudness(path):
    code, out, err = run(['ffmpeg', '-hide_banner', '-nostdin', '-nostats', '-i', path, '-vn', '-af', 'ebur128=peak=true',
                          '-f', 'null', '-'])
    tail = err[err.rfind('Summary:'):] if 'Summary:' in err else err
    i = re.search(r'\bI:\s+(-?[\d.]+)\s+LUFS', tail)
    p = re.search(r'\bPeak:\s+(-?[\d.]+)\s+dBFS', tail)
    return (float(i.group(1)) if i else None, float(p.group(1)) if p else None)


def expected_from_json(path):
    t = json.load(open(path, encoding='utf-8'))
    out = t.get('out') or {}
    return {'name': t.get('name') or t.get('id') or os.path.basename(path), 'w': out.get('w') or t['w'], 'h': out.get('h') or t['h'],
            'rate': rate_of(out.get('fpsStr') or t.get('fps')), 'frames': int(t.get('frames') or 0),
            'bitrate': float(out.get('bitrate') or t.get('bitrate') or 0), 'audio': bool(t.get('hasAudio'))}


def expected_from_video(path):
    p = probe(path)
    return {'name': os.path.basename(path), 'w': p['w'], 'h': p['h'], 'rate': p['rate'], 'frames': p['frames'],
            'bitrate': p['bitrate'], 'audio': bool(p['audio'])}


def expected_for(mp4, take_arg):
    if take_arg:
        return expected_from_json(take_arg) if take_arg.lower().endswith('.json') else expected_from_video(take_arg)
    folder = os.path.dirname(mp4)
    job = os.path.join(folder, 'job.json')
    if os.path.isfile(job):
        tid = json.load(open(job, encoding='utf-8')).get('takeId')
        cand = os.path.normpath(os.path.join(folder, '..', '..', 'takes', str(tid), 'take.json')) if tid else ''
        if cand and os.path.isfile(cand):
            return expected_from_json(cand)
    return expected_from_json(SAMPLE_TAKE)


WORK_FILES = ('video.mp4', 'render.mp4')       # an export folder's work files: the picture-only encode and the intermediate render
FINAL_SUFFIX = ' - floored.mp4'              # the name of an export's final file


def find_mp4s(folder):
    """The mp4s to judge: in an export folder (one with a job.json) only the final `<name> - floored.mp4`; in any other
    folder every mp4 except the work files."""
    found = []
    for root, _, files in os.walk(folder):
        is_export = 'job.json' in files
        for f in sorted(files):
            low = f.lower()
            if not low.endswith('.mp4') or low in WORK_FILES:
                continue
            if is_export and not low.endswith(FINAL_SUFFIX):
                continue
            found.append(os.path.join(root, f))
    return sorted(found)


def judge(mp4, take_arg):
    exp = expected_for(mp4, take_arg)
    got = probe(mp4)
    need = max(exp['bitrate'], MIN_MBPS * 1e6)
    lufs, peak = loudness(mp4) if got['audio'] else (None, None)
    a = got['audio'][0] if got['audio'] else None
    fails = []
    if (got['w'], got['h']) != (exp['w'], exp['h']):
        fails.append('size')
    if got['rate'] != exp['rate'] or (exp['frames'] and got['frames'] != exp['frames']):
        fails.append('fps/frames')
    if got['bitrate'] < need * BITRATE_TOLERANCE:
        fails.append('bitrate')
    if exp['audio'] or a:
        if not a or a['codec'] != 'aac' or a['rate'] != SR:
            fails.append('audio codec/rate')
        if lufs is None or abs(lufs - LUFS) > LUFS_TOL:
            fails.append('LUFS')
        if peak is not None and peak > TP_MAX + TP_SLACK:
            fails.append('true peak')
    return {'file': mp4, 'exp': exp, 'got': got, 'need': need, 'lufs': lufs, 'peak': peak, 'audio': a, 'fails': fails}


def mbps(x):
    return '%.2f' % (x / 1e6)


def row(r, base):
    e, g = r['exp'], r['got']
    size = '%sx%s' % (g['w'], g['h']) + ('' if (g['w'], g['h']) == (e['w'], e['h']) else ' (want %sx%s)' % (e['w'], e['h']))
    fps = '%g fps, %d fr' % (float(g['rate']), g['frames']) + ('' if r['fails'].count('fps/frames') == 0 else
                                                                 ' (want %g, %d)' % (float(e['rate']), e['frames']))
    rate = '%s (need %s, min %s)' % (mbps(g['bitrate']), mbps(r['need']), mbps(r['need'] * BITRATE_TOLERANCE))
    lufs = 'none' if r['lufs'] is None else '%.1f' % r['lufs']
    peak = 'none' if r['peak'] is None else '%.1f' % r['peak']
    a = r['audio']
    audio = 'none' if not a else '%s %g kHz' % (a['codec'], a['rate'] / 1000.0)
    size_mb = os.path.getsize(r['file']) / 1e6
    verdict = 'PASS' if not r['fails'] else 'FAIL: ' + ', '.join(r['fails'])
    return '| %s | %s | %s | %s | %s | %s | %s | %s | %.1f MB | %s |' % (
        os.path.relpath(r['file'], base).replace('\\', '/'), e['name'], size, fps, rate, lufs, peak, audio, size_mb, verdict)


def main(argv=None):
    ap = argparse.ArgumentParser(description='Markdown table of the exports in a folder, checked against their takes.')
    ap.add_argument('folder')
    ap.add_argument('--take', help='a take.json, or the source video, to judge every file against')
    ap.add_argument('--out', help='also write the table to this file')
    args = ap.parse_args(argv)
    files = find_mp4s(args.folder)
    if not files:
        print('No exports (*.mp4) in %s' % args.folder, file=sys.stderr)
        return 2
    lines = ['| file | take | size | fps, frames | video Mbps (raw, need, min = 0.98 x need) | LUFS (-14 +-1) | true peak dBTP | audio | size | result |',
             '|---|---|---|---|---|---|---|---|---|---|']
    bad = 0
    for f in files:
        try:
            r = judge(f, args.take)
        except Exception as ex:                     # a file that cannot be read is a failed row, not a crash
            lines.append('| %s | | | | | | | | | FAIL: %s |' % (os.path.relpath(f, args.folder).replace('\\', '/'), ex))
            bad += 1
            continue
        bad += bool(r['fails'])
        lines.append(row(r, args.folder))
    lines.append('')
    lines.append('%d of %d rows pass.' % (len(files) - bad, len(files)))
    text = '\n'.join(lines)
    print(text)
    if args.out:
        with open(args.out, 'w', encoding='utf-8') as fh:
            fh.write(text + '\n')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
