"""Lab only: small JSON checks for the first-contact jobs. Usage: fc_check.py <check> <file>"""
import json
import sys


def last_json(path):
    text = open(path, encoding='utf-8', errors='replace').read()
    try:
        return json.loads(text)
    except ValueError:
        pass
    for line in reversed([l for l in text.splitlines() if l.strip()]):
        try:
            return json.loads(line)
        except ValueError:
            continue
    raise SystemExit('FC FAIL no JSON in ' + path)


def show(d, found=False):
    for i in d['items']:
        extra = (' found=%s' % i.get('found')) if found else ''
        print('ITEM', i['id'], 'ok=%s' % i['ok'], 'how=%s' % i.get('how'), 'mb=%s' % i.get('mb') + extra)


def main():
    check, path = sys.argv[1], sys.argv[2]
    d = last_json(path)
    if check == 'before':
        items = {i['id']: i for i in d['items']}
        bad = []
        show(d)
        if d.get('ok') is not False:
            bad.append('report ok is not false')
        if not items['python']['ok']:
            bad.append('python not ok')
        for k in ('node', 'ffmpeg'):
            i = items[k]
            if i['ok'] or i.get('how') != 'auto' or not str(i.get('command', '')).startswith('download '):
                bad.append('%s: ok=%s how=%s command=%r' % (k, i['ok'], i.get('how'), i.get('command')))
        if bad:
            print('FC FAIL', '; '.join(bad))
            sys.exit(1)
    elif check == 'installed':
        if d.get('ok') is not True:
            print('FC FAIL install line not ok:', d)
            sys.exit(1)
        print('install line ok')
    elif check == 'after':
        show(d, True)
        if d.get('ok') is not True:
            print('FC FAIL doctor ok is not true')
            sys.exit(1)
    elif check in ('running', 'stopped'):
        take = sys.argv[3]
        listed = [t for t in d.get('takes', []) if take in json.dumps(t)]
        print('url=%s takes=%d listed=%d' % (d.get('url'), len(d.get('takes', [])), len(listed)))
        if check == 'running' and not (d.get('url') and listed and 'ready' in json.dumps(listed[0])):
            print('FC FAIL status while running: need a url and the take ready')
            sys.exit(1)
        if check == 'stopped' and d.get('url'):
            print('FC FAIL status after stop still has a url')
            sys.exit(1)
    elif check == 'take':
        print(d['take'])
    else:
        sys.exit(2)


main()
