#!/bin/sh
# Lab only: which file answers when /usr/bin/python3 runs after only Xcode and the command line tools are gone
# (the state of the first probe, which still printed a Python version)? Everything is put back right after.
unset DEVELOPER_DIR SDKROOT
AWAY=/private/tmp/lab-exp
sudo mkdir -p "$AWAY"; sudo chmod 777 "$AWAY"
: > "$AWAY/m"; n=0
mv_away() { [ -e "$1" ] || return 0; n=$((n+1)); sudo mv "$1" "$AWAY/$n" && printf '%s|%s\n' "$1" "$AWAY/$n" >> "$AWAY/m"; }
mv_away /Library/Developer/CommandLineTools
for x in /Applications/Xcode*.app; do mv_away "$x"; done
export PATH=/usr/bin:/bin:/usr/sbin:/sbin
echo "xcode-select -p: $(xcode-select -p 2>&1)"
for i in 1 2; do
  echo "--- run $i: /usr/bin/python3 -c ..."
  perl -e 'alarm 20; exec @ARGV' /usr/bin/python3 -c 'import sys; print("sys.executable =", sys.executable); print("sys.prefix =", sys.prefix); print(sys.version)' 2>&1
  echo "exit $?"
done
echo "--- xcrun --find python3:"; perl -e 'alarm 20; exec @ARGV' /usr/bin/xcrun --find python3 2>&1; echo "exit $?"
echo "--- /usr/bin/python3 --version:"; perl -e 'alarm 20; exec @ARGV' /usr/bin/python3 --version 2>&1; echo "exit $?"
sed '1!G;h;$!d' "$AWAY/m" | while IFS='|' read -r o d; do sudo mv "$d" "$o"; done
exit 0
