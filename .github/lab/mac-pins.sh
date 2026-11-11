#!/bin/sh
# Lab only: check every pinned download of this Mac's system in tools.txt: size, SHA-256, unpack, run, features.
unset DEVELOPER_DIR SDKROOT
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
SYS="${LAB_SYS:?}"
LAB="${RUNNER_TEMP:-/private/tmp}/lab"
mkdir -p "$LAB"
fails=0
count=0
fail() { echo "PIN FAIL $*"; fails=$((fails+1)); }

grep -v '^[[:space:]]*#' plugin/skills/floored/app/tools.txt | awk -v s="$SYS" 'NF>=5 && $2==s {print $1, $3, $4, $5}' > "$LAB/pins.txt"
echo "pins for $SYS: $(wc -l < "$LAB/pins.txt" | tr -d ' ')"

while read -r tool bytes sha url; do
  count=$((count+1))
  file="$LAB/$(basename "$url")"
  dir="$LAB/$tool-$SYS"
  echo "=== $tool $SYS  $url"
  if ! curl -fL --retry 2 -sS -o "$file" "$url"; then fail "$tool $SYS download"; continue; fi
  size=$(stat -f %z "$file")
  got=$(shasum -a 256 "$file" | cut -d' ' -f1)
  echo "size $size (pinned $bytes), sha256 $got"
  [ "$size" = "$bytes" ] || { fail "$tool $SYS size $size != $bytes"; continue; }
  [ "$got" = "$sha" ] || { fail "$tool $SYS sha $got != $sha"; continue; }
  mkdir -p "$dir"
  case "$file" in
    *.tar.gz) tar -xzf "$file" -C "$dir" || { fail "$tool $SYS tar"; continue; } ;;
    *.zip) /usr/bin/unzip -q -o "$file" -d "$dir" || { fail "$tool $SYS unzip"; continue; } ;;
  esac
  echo "unpacked into $dir"; ls "$dir" | head
  rm -f "$file"
  case "$tool" in
    python)
      py="$dir/python/bin/python3"
      v=$("$py" --version 2>&1); echo "python --version: $v (exit $?)"
      case "$v" in *"${PY_VERSION:?}"*) ;; *) fail "python $SYS version '$v'"; continue ;; esac
      "$py" -m venv "$LAB/venv-test" || { fail "python $SYS venv"; continue; }
      pipv=$("$LAB/venv-test/bin/pip" --version 2>&1) || { fail "python $SYS pip"; continue; }
      echo "venv pip: $pipv"
      echo "PIN ok python $SYS $size bytes sha ok, $v, venv pip ok ($pipv)"
      echo "$py" > "$LAB/python-path.txt"
      ;;
    node)
      nd=$(ls -d "$dir"/node-v*/bin | head -1)
      v=$("$nd/node" --version 2>&1); echo "node --version: $v (exit $?)"
      case "$v" in *"${NODE_VERSION:?}"*) ;; *) fail "node $SYS version '$v'"; continue ;; esac
      npmv=$(PATH="$nd:$PATH" npm --version 2>&1) || { fail "node $SYS npm: $npmv"; continue; }
      echo "npm --version: $npmv"
      echo "PIN ok node $SYS $size bytes sha ok, node $v, npm $npmv"
      ;;
    ffmpeg)
      chmod +x "$dir/ffmpeg"
      l1=$("$dir/ffmpeg" -hide_banner -version 2>&1 | head -1); echo "ffmpeg: $l1"
      case "$l1" in *"${FFMPEG_VERSION:?}"*) ;; *) fail "ffmpeg $SYS version '$l1'"; continue ;; esac
      filters=$("$dir/ffmpeg" -hide_banner -filters 2>&1)
      encs=$("$dir/ffmpeg" -hide_banner -encoders 2>&1)
      missing=""
      for f in zscale tonemap loudnorm ebur128 amix; do echo "$filters" | grep -q "[[:space:]]$f[[:space:]]" || missing="$missing filter:$f"; done
      for e in libx264 libvpx-vp9 aac; do echo "$encs" | grep -q "[[:space:]]$e[[:space:]]" || missing="$missing encoder:$e"; done
      echo "ffmpeg missing:${missing:- (none)}"
      [ -z "$missing" ] || { fail "ffmpeg $SYS missing:$missing"; continue; }
      echo "PIN ok ffmpeg $SYS $size bytes sha ok, $l1; filters zscale tonemap loudnorm ebur128 amix ok; encoders libx264 libvpx-vp9 aac ok"
      echo "$dir" > "$LAB/ffmpeg-dir.txt"
      ;;
    ffprobe)
      chmod +x "$dir/ffprobe"
      l1=$("$dir/ffprobe" -hide_banner -version 2>&1 | head -1); echo "ffprobe: $l1"
      case "$l1" in *"${FFMPEG_VERSION:?}"*) ;; *) fail "ffprobe $SYS version '$l1'"; continue ;; esac
      echo "PIN ok ffprobe $SYS $size bytes sha ok, $l1"
      ;;
    *) fail "unknown tool $tool" ;;
  esac
done < "$LAB/pins.txt"

echo "pins checked: $count, failures: $fails"
[ "$fails" -eq 0 ] && [ "$count" -eq 4 ]
