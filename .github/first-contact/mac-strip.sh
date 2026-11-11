#!/bin/sh
# strip a GitHub Mac runner until it looks like a Mac with no developer software.
# Everything moved goes to /private/tmp/lab-away and is put back by mac-restore.sh at the end of the job.
AWAY=/private/tmp/lab-away
sudo mkdir -p "$AWAY"
sudo chmod 777 "$AWAY"
MANIFEST="$AWAY/manifest.txt"
: > "$MANIFEST"
n=0
away() {
  p="$1"
  if [ -e "$p" ] || [ -L "$p" ]; then
    n=$((n+1))
    dest="$AWAY/$n"
    if sudo mv "$p" "$dest"; then echo "moved  $p"; printf '%s|%s\n' "$p" "$dest" >> "$MANIFEST"; else echo "FAILED to move $p"; fi
  else
    echo "absent $p"
  fi
}
echo "--- before: DEVELOPER_DIR=${DEVELOPER_DIR:-(unset)} SDKROOT=${SDKROOT:-(unset)}"
for p in /opt/homebrew /usr/local/Homebrew /usr/local/Cellar /usr/local/opt /usr/local/Caskroom \
         /Library/Frameworks/Python.framework /Library/Developer/CommandLineTools \
         "$HOME/hostedtoolcache" /Users/runner/hostedtoolcache "${RUNNER_TOOL_CACHE:-/nonexistent}" \
         "$HOME/.nvm" "$HOME/.volta" "$HOME/.fnm" "$HOME/.pyenv" "$HOME/.asdf" "$HOME/Library/Python" "$HOME/.local/bin"; do
  away "$p"
done
for x in /Applications/Xcode*.app /Applications/Python*; do away "$x"; done
# /usr/local/bin holds Homebrew's links and the Python framework's links: take the whole folder, leave an empty one.
if [ -d /usr/local/bin ]; then
  away /usr/local/bin
  sudo mkdir -p /usr/local/bin
fi
echo "--- manifest:"; cat "$MANIFEST"
exit 0
