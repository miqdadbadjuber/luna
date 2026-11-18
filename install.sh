#!/bin/sh
# One-command install for macOS and Linux: uv, Python 3.12, dependencies and FFmpeg.
set -eu

REPO_URL="${LUNA_REPO_URL:-https://github.com/miqdadbadjuber/luna}"

IS_UPDATE=0
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || pwd)
if [ -f "$SCRIPT_DIR/luna/app.py" ] && [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    LUNA_DIR="$SCRIPT_DIR"
    [ -x "$LUNA_DIR/.venv/bin/python" ] && IS_UPDATE=1
else
    # Run through `curl | sh`, so there is no checkout yet.
    LUNA_DIR="${LUNA_DIR:-$HOME/Luna}"
    REF="${LUNA_REF:-main}"
    if [ -d "$LUNA_DIR/.git" ]; then
        IS_UPDATE=1
        echo "Updating Luna in $LUNA_DIR..."
        git -C "$LUNA_DIR" pull --ff-only
    elif command -v git >/dev/null 2>&1 && [ ! -e "$LUNA_DIR/luna/app.py" ]; then
        if ! git clone --branch "$REF" "$REPO_URL" "$LUNA_DIR"; then
            echo "Could not download Luna from $REPO_URL." >&2
            echo "If the repository is private, clone it yourself and run ./install.sh there." >&2
            exit 1
        fi
    else
        # No git: unpack the source archive over $LUNA_DIR. .env, .venv and media are not in it, so they survive.
        # shortcut: files removed upstream stay behind on an update, switch to git if that ever matters.
        [ -f "$LUNA_DIR/luna/app.py" ] && IS_UPDATE=1
        if [ "$IS_UPDATE" -eq 1 ]; then
            echo "Updating Luna in $LUNA_DIR..."
        else
            echo "Downloading Luna..."
        fi
        mkdir -p "$LUNA_DIR"
        ARCHIVE="$(mktemp)"
        if ! curl -fsSL "$REPO_URL/archive/$REF.tar.gz" -o "$ARCHIVE" \
            || ! tar -xzf "$ARCHIVE" -C "$LUNA_DIR" --strip-components=1; then
            echo "Could not download Luna from $REPO_URL." >&2
            rm -f "$ARCHIVE"
            exit 1
        fi
        rm -f "$ARCHIVE"
    fi
fi
cd "$LUNA_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv..."
    # Download first, then execute: `curl | sh` runs an empty script when curl fails
    # and cannot report a clear error. Pin UV_VERSION and verify a checksum for a
    # fully reproducible install.
    UV_INSTALLER="$(mktemp)"
    if ! curl -fsSL https://astral.sh/uv/install.sh -o "$UV_INSTALLER"; then
        echo "Could not download the uv installer from astral.sh." >&2
        rm -f "$UV_INSTALLER"
        exit 1
    fi
    sh "$UV_INSTALLER"
    rm -f "$UV_INSTALLER"
    PATH="$HOME/.local/bin:$PATH"
    export PATH
fi

echo "Installing Python and dependencies..."
uv venv .venv --python 3.12 --allow-existing
uv pip install --python .venv/bin/python -r requirements.txt

# Keys are entered in Settings. Never overwrite a file that may already hold them.
if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env
fi

echo "Checking FFmpeg..."
.venv/bin/python -c "from luna.ffmpeg_setup import ensure_ffmpeg; ensure_ffmpeg()"
chmod +x start.sh

ACTION_WORD="installation"
[ "$IS_UPDATE" -eq 1 ] && ACTION_WORD="update"

printf "\n============================================================\n"
printf "  Luna %s complete!\n" "$ACTION_WORD"
printf "============================================================\n"
printf "  Location : %s\n" "$LUNA_DIR"
printf "  Launcher : ./start.sh\n"
printf "  Settings : .env and saved Workspace media are kept across updates.\n"
printf "  Update   : Close Luna first, then re-run the same install command.\n"
printf "============================================================\n\n"

if [ "${LUNA_NO_START:-}" != "1" ]; then
    SHOULD_LAUNCH=1
    if [ -t 1 ] && [ -r /dev/tty ] && [ "${LUNA_AUTO_START:-}" != "1" ]; then
        printf "Press Enter to launch Luna now (or type n to exit): " > /dev/tty
        IFS= read -r REPLY < /dev/tty || REPLY=""
        case "$REPLY" in
            [nN]|[nN][oO]) SHOULD_LAUNCH=0 ;;
        esac
    fi
    if [ "$SHOULD_LAUNCH" -eq 1 ]; then
        echo "Starting Luna..."
        exec ./start.sh
    else
        echo "Launch skipped. Start Luna anytime with ./start.sh"
    fi
fi
