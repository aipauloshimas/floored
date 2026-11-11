#!/bin/sh
# Lab only: floored's doctor on the bare Mac, started with the freshly unpacked Python by its full path.
unset DEVELOPER_DIR SDKROOT
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
LAB="${RUNNER_TEMP:-/private/tmp}/lab"
PY=$(cat "$LAB/python-path.txt")
FLOORED_HOME=$(mktemp -d)
export FLOORED_HOME
echo "python: $PY"
"$PY" plugin/skills/floored/app/floored.py doctor --json > "$LAB/doctor.json" 2> "$LAB/doctor.err"
echo "doctor exit code: $? (1 is expected today)"
cat "$LAB/doctor.json"
echo "--- stderr:"; cat "$LAB/doctor.err"
echo "--- items (id, ok, found):"
"$PY" -c "import json,sys; d=json.load(open(sys.argv[1])); [print('ITEM', i['id'], 'ok=%s' % i['ok'], 'found=%s' % i.get('found')) for i in d['items']]" "$LAB/doctor.json"
exit 0
