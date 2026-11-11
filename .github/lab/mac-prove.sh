#!/bin/sh
# Lab only: prove the Mac looks bare, with the system PATH a creator's Terminal has.
unset DEVELOPER_DIR SDKROOT
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
fail=0
echo "PATH=$PATH"
sw_vers; uname -m
echo "--- command -v:"
for t in python python3 node npm ffmpeg ffprobe brew; do
  printf '%s -> ' "$t"
  r=$(command -v "$t" || true)
  if [ -z "$r" ]; then echo "(not found)"; else
    echo "$r"
    if [ "$r" != /usr/bin/python3 ]; then echo "STILL FOUND: $t"; fail=1; fi
  fi
done
echo "--- xcode-select -p:"
xcode-select -p 2>&1; rc=$?
echo "exit $rc"
if [ "$rc" -eq 0 ]; then echo "STILL FOUND: xcode-select -p succeeds"; fail=1; fi
echo "--- /usr/bin/python3 --version (20 s limit):"
ls -la /usr/bin/python3
s=$(date +%s)
perl -e 'alarm 20; exec @ARGV' /usr/bin/python3 --version 2>&1; rc=$?
echo "exit $rc, $(( $(date +%s) - s )) s"
echo "--- which file answered? (20 s limit each)"
perl -e 'alarm 20; exec @ARGV' /usr/bin/python3 -c 'import sys; print("sys.executable =", sys.executable); print("sys.prefix =", sys.prefix); print(sys.version)' 2>&1 || echo "(failed, exit $?)"
perl -e 'alarm 20; exec @ARGV' /usr/bin/xcrun --find python3 2>&1 || echo "(xcrun --find failed, exit $?)"
echo "--- leftovers a developer would have:"
ls -d /Library/Developer/CommandLineTools /Applications/Xcode*.app /opt/homebrew /Library/Frameworks/Python.framework /usr/local/Cellar 2>&1 | sed 's/^/  /'
ls -la /usr/local/bin | sed 's/^/  /'
echo "--- browsers:"
ls -d /Applications/*.app 2>/dev/null | grep -i -E "chrome|edge|brave|arc|firefox|safari" || echo "(none of those)"
exit $fail
