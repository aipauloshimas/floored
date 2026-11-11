#!/bin/sh
# get-python.sh - find a Python 3.10 or newer on a Mac, or download floored's own copy.
#
#   sh get-python.sh            prints  FLOORED_PYTHON=<full path>  (exit 0), or  NO_PYTHON  (exit 3)
#   sh get-python.sh --install  downloads floored's own Python into <home>/tools/python (only what tools.txt pins),
#                               then prints  FLOORED_PYTHON=<full path>  (exit 0); a failure is one sentence on stderr (exit 1)
#
# <home> is $FLOORED_HOME, else ~/.floored. Nothing is written outside <home>/tools: no admin rights, no PATH change.
# Plain POSIX sh (macOS /bin/sh): nothing from bash or zsh.

FLOORED_HOME_DIR="${FLOORED_HOME:-$HOME/.floored}"
TOOLS_DIR="$FLOORED_HOME_DIR/tools"
OWN_PYTHON="$TOOLS_DIR/python/bin/python3"
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

say() { printf '%s\n' "$1"; }
note() { printf '%s\n' "$1" >&2; }

# Apple's /usr/bin/python3 is a stub: when the command line developer tools are missing it opens an install dialog
# instead of answering. It is never run unless xcode-select -p succeeds. Every candidate goes through this one check.
apple_stub_allowed() {
    case "$1" in
        /usr/bin/*) ;;
        *)
            # a link that points into /usr/bin is the same stub
            target=$(readlink "$1" 2>/dev/null)
            case "$target" in
                /usr/bin/*) ;;
                *) return 0 ;;
            esac
            ;;
    esac
    xcode-select -p >/dev/null 2>&1
}

# A candidate counts only when running it proves it is Python 3.10 or newer.
usable() {
    [ -n "$1" ] || return 1
    [ -f "$1" ] && [ -x "$1" ] || return 1
    apple_stub_allowed "$1" || return 1
    "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' >/dev/null 2>&1
}

# first usable program called $1 on PATH (every match is tried, so a stub earlier on PATH hides nothing)
on_path() {
    old_ifs=$IFS
    IFS=:
    for dir in $PATH; do
        IFS=$old_ifs
        case "$dir" in
            /*) ;;
            *) continue ;;
        esac
        if usable "$dir/$1"; then
            say "$dir/$1"
            return 0
        fi
    done
    return 1
}

find_python() {
    if usable "$OWN_PYTHON"; then
        say "$OWN_PYTHON"
        return 0
    fi
    on_path python3 && return 0
    on_path python && return 0
    for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
        if usable "$candidate"; then
            say "$candidate"
            return 0
        fi
    done
    return 1
}

cleanup() {
    rm -rf "$TOOLS_DIR/python.part" "$TOOLS_DIR/python.new"
}

fail() {
    cleanup
    rm -rf "$TOOLS_DIR/python"
    note "$1"
    exit 1
}

file_size() { wc -c < "$1" | tr -d ' '; }

file_sha256() {
    if command -v shasum >/dev/null 2>&1; then
        shasum -a 256 "$1" | awk '{print $1}'
    else
        openssl dgst -sha256 "$1" | awk '{print $NF}'
    fi
}

install_python() {
    if usable "$OWN_PYTHON"; then
        say "FLOORED_PYTHON=$OWN_PYTHON"
        exit 0
    fi

    # a broken leftover is replaced
    rm -rf "$TOOLS_DIR/python"

    if [ "$(sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then
        system=darwin-arm64
    else
        system=darwin-x64
    fi

    pins="${FLOORED_TOOLS_FILE:-$SCRIPT_DIR/tools.txt}"
    line=
    if [ -f "$pins" ]; then
        line=$(awk -v want="$system" '
            /^[ \t]*#/ { next }
            NF >= 5 && $1 == "python" && $2 == want { print $3 " " $4 " " $5; exit }
        ' "$pins")
    fi
    [ -n "$line" ] || fail "This computer's system has no Python download in floored's list."
    want_size=${line%% *}
    rest=${line#* }
    want_sha=${rest%% *}
    url=${rest#* }

    mkdir -p "$TOOLS_DIR" || fail "Couldn't download Python (floored's folder could not be made). Check the internet connection and try again."
    cleanup
    note "Downloading Python for floored..."
    reason=$(curl -fL --retry 2 -sS -o "$TOOLS_DIR/python.part" "$url" 2>&1 >/dev/null) || {
        reason=$(printf '%s' "$reason" | tr '\n' ' ' | sed 's/  */ /g; s/^ //; s/ $//')
        [ -n "$reason" ] || reason="the download failed"
        fail "Couldn't download Python ($reason). Check the internet connection and try again."
    }

    [ -f "$TOOLS_DIR/python.part" ] || fail "Couldn't download Python (nothing was saved). Check the internet connection and try again."
    got_size=$(file_size "$TOOLS_DIR/python.part")
    got_sha=$(file_sha256 "$TOOLS_DIR/python.part" | tr 'A-F' 'a-f')
    want_sha=$(printf '%s' "$want_sha" | tr 'A-F' 'a-f')
    if [ "$got_size" != "$want_size" ] || [ "$got_sha" != "$want_sha" ]; then
        fail "The Python download didn't match the expected file, so it was thrown away. Try again."
    fi

    mkdir -p "$TOOLS_DIR/python.new" || fail "Couldn't download Python (the file could not be unpacked). Check the internet connection and try again."
    if ! /usr/bin/tar -xzf "$TOOLS_DIR/python.part" -C "$TOOLS_DIR/python.new" >/dev/null 2>&1 || [ ! -d "$TOOLS_DIR/python.new/python" ]; then
        fail "Couldn't download Python (the file could not be unpacked). Check the internet connection and try again."
    fi
    rm -rf "$TOOLS_DIR/python"
    mv "$TOOLS_DIR/python.new/python" "$TOOLS_DIR/python" || fail "Couldn't download Python (the file could not be unpacked). Check the internet connection and try again."
    cleanup

    if ! usable "$OWN_PYTHON"; then
        fail "Couldn't download Python (the new copy did not start). Check the internet connection and try again."
    fi
    say "FLOORED_PYTHON=$OWN_PYTHON"
    exit 0
}

if [ "$1" = "--install" ]; then
    install_python
fi

found=$(find_python)
if [ -n "$found" ]; then
    say "FLOORED_PYTHON=$found"
    exit 0
fi
say "NO_PYTHON"
exit 3
