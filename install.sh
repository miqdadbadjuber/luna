#!/bin/sh
# One-command install for macOS and Linux: uv, Python 3.12, dependencies and FFmpeg.
set -eu

REPO_URL="${LUNA_REPO_URL:-https://github.com/miqdadbadjuber/luna}"

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || pwd)
if [ -f "$SCRIPT_DIR/app.py" ] && [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    LUNA_DIR="$SCRIPT_DIR"
else
    # Run through `curl | sh`, so there is no checkout yet.
    LUNA_DIR="${LUNA_DIR:-$HOME/Luna}"
    command -v git >/dev/null 2>&1 || { echo "git is required to download Luna." >&2; exit 1; }
    if [ -d "$LUNA_DIR/.git" ]; then
        git -C "$LUNA_DIR" pull --ff-only
    elif ! git clone "$REPO_URL" "$LUNA_DIR"; then
        echo "Could not download Luna from $REPO_URL." >&2
        echo "If the repository is private, clone it yourself and run ./install.sh there." >&2
        exit 1
    fi
fi
cd "$LUNA_DIR"

if ! command -v uv >/dev/null 2>&1; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
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
.venv/bin/python -c "from ffmpeg_setup import ensure_ffmpeg; ensure_ffmpeg()"
chmod +x start.sh

echo "Luna is installed in $LUNA_DIR. Start it again later with ./start.sh"
[ "${LUNA_NO_START:-}" = "1" ] || exec ./start.sh
