#!/bin/sh
# what Claude does on a creator's Mac by SKILL.md, steps 2 to 8. System PATH only, like Terminal.
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
unset DEVELOPER_DIR SDKROOT
set +e
REPO=$(pwd)
APP="$REPO/plugin/skills/floored/app"
CHECK="$REPO/.github/first-contact/fc_check.py"
FH="$HOME/.floored"
WORK="${RUNNER_TEMP:-/private/tmp}/fc"
mkdir -p "$WORK"
now() { date +%s; }
ok() { echo "FC ok $1 $(( $(now) - $2 ))s"; }
die() { echo "FC FAIL $1"; exit 1; }

# 2 the finder
t=$(now)
o=$(sh "$APP/get-python.sh" 2> "$WORK/finder.err"); rc=$?
echo "stdout: [$o] exit $rc"; cat "$WORK/finder.err"
[ "$rc" -eq 3 ] && [ "$o" = NO_PYTHON ] || die "finder: expected NO_PYTHON exit 3"
ok finder-no-python "$t"

# 3 --install
t=$(now)
o=$(sh "$APP/get-python.sh" --install 2> "$WORK/finder.err"); rc=$?
echo "stdout: [$o] exit $rc"; cat "$WORK/finder.err"
[ "$rc" -eq 0 ] || die "finder --install exit $rc"
[ "$(printf '%s\n' "$o" | wc -l | tr -d ' ')" = 1 ] || die "finder --install: more than one line"
case "$o" in "FLOORED_PYTHON=$FH/tools/python"*) ;; *) die "finder --install: unexpected path" ;; esac
PY=${o#FLOORED_PYTHON=}
ok finder-install "$t"
t=$(now)
o2=$(sh "$APP/get-python.sh" 2> "$WORK/finder.err"); rc=$?
echo "stdout: [$o2] exit $rc"
[ "$rc" -eq 0 ] && [ "$o2" = "$o" ] || die "finder again: not the same path"
ok finder-again "$t"
echo "PY=$PY"

dr() { name=$1; shift; "$PY" "$APP/floored.py" "$@" > "$WORK/$name.out" 2> "$WORK/$name.err"; rc=$?; }

# 4 doctor before
t=$(now)
dr doctor-before doctor --json
echo "doctor exit $rc"; tail -n 20 "$WORK/doctor-before.err"
[ "$rc" -eq 1 ] || die "doctor --json expected exit 1, got $rc"
"$PY" "$CHECK" before "$WORK/doctor-before.out" || die "doctor items before"
ok doctor-before "$t"

# 5 installs
WORDS_FAILED=
for item in node ffmpeg venv packages rvm-model renderer words; do
  t=$(now)
  dr "install-$item" doctor --install "$item"
  echo "--- $item exit $rc"
  tail -n 5 "$WORK/install-$item.out"
  echo "stderr tail:"; tail -n 8 "$WORK/install-$item.err"
  if [ "$rc" -ne 0 ]; then
    if [ "$item" = words ] && [ "$LAB_SYS" = darwin-x64 ]; then
      echo "FC NONFATAL words on the Intel Mac exit $rc (a finding, see above)"; WORDS_FAILED=1; continue
    fi
    die "doctor --install $item exit $rc"
  fi
  "$PY" "$CHECK" installed "$WORK/install-$item.out" || die "install $item not ok"
  ok "install-$item" "$t"
done

# 6 doctor after, gpu check
t=$(now)
dr doctor-after doctor --json
echo "doctor exit $rc"
if [ "$rc" -ne 0 ]; then
  tail -n 60 "$WORK/doctor-after.out"
  [ -n "$WORDS_FAILED" ] || die "doctor --json after expected exit 0, got $rc"
else
  "$PY" "$CHECK" after "$WORK/doctor-after.out" || die "doctor items after"
fi
ok doctor-after "$t"
t=$(now)
dr gpu doctor --gpu-check
echo "gpu-check exit $rc (does not fail the job)"; tail -n 15 "$WORK/gpu.out" "$WORK/gpu.err"
ok gpu-check "$t"

# 7 the product flow
t=$(now)
WS="$WORK/ws"; mkdir -p "$WS"
dr add add --workspace "$WS" "$APP/sample/source.mp4"
echo "add exit $rc"; tail -n 10 "$WORK/add.out" "$WORK/add.err"
[ "$rc" -eq 0 ] || die "add exit $rc"
take=$("$PY" "$CHECK" take "$WORK/add.out")
echo "take: $take"
ok add "$t"
t=$(now)
dr wait wait --workspace "$WS" --take "$take" --timeout 1800
echo "wait exit $rc"; tail -n 10 "$WORK/wait.out" "$WORK/wait.err"
[ "$rc" -eq 0 ] || die "wait exit $rc"
ok wait "$t"
t=$(now)
dr status1 status --workspace "$WS"
echo "status (running):"; tail -n 40 "$WORK/status1.out"
[ "$rc" -eq 0 ] || die "status exit $rc"
"$PY" "$CHECK" running "$WORK/status1.out" "$take" || die "status while running"
dr stop stop --workspace "$WS"
echo "stop exit $rc"; tail -n 10 "$WORK/stop.out"
[ "$rc" -eq 0 ] || die "stop exit $rc"
sleep 3
dr status2 status --workspace "$WS"
echo "status (stopped):"; tail -n 40 "$WORK/status2.out"
"$PY" "$CHECK" stopped "$WORK/status2.out" "$take" || die "status after stop"
find "$WS" -name "$take" | head -n 3
[ -n "$(find "$WS" -name "$take" | head -n 1)" ] || die "the take is gone from the workspace"
ok status-stop "$t"

# 8 sizes
for d in tools/python tools/node tools/ffmpeg venv renderer ""; do
  echo "SIZE $FH/$d $(du -sk "$FH/$d" 2>/dev/null | cut -f1) KB"
done
ok sizes "$(now)"
exit 0
