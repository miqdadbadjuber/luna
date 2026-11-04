# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

"""Find FFmpeg, or download a private copy so users do not have to install it."""
import shutil


def ensure_ffmpeg() -> bool:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True
    try:
        import static_ffmpeg

        static_ffmpeg.add_paths()
    except Exception as e:
        # Downloads still work without it for some formats, and Settings shows what is missing.
        print(f"Could not set up FFmpeg automatically: {e}", flush=True)
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
