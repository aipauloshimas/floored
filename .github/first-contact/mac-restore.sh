#!/bin/sh
# put back what mac-strip.sh moved, so the runner's own end-of-job steps still work.
MANIFEST=/private/tmp/lab-away/manifest.txt
[ -f "$MANIFEST" ] || exit 0
# newest first, so /usr/local/bin's empty stand-in is removed before the real one returns
sed '1!G;h;$!d' "$MANIFEST" | while IFS='|' read -r orig dest; do
  [ -e "$dest" ] || [ -L "$dest" ] || continue
  if [ -d "$orig" ] && [ ! -L "$orig" ]; then sudo rmdir "$orig" 2>/dev/null || true; fi
  sudo mv "$dest" "$orig" && echo "restored $orig"
done
exit 0
