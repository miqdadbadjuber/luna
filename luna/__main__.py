# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

"""Development entry point (python -m luna) with auto-reload.

For daily use prefer start.sh / start.bat: the reloader restarts the process, and
job state lives in memory, so a reload drops in-flight jobs.
"""
import os

import uvicorn

# Deliberately does not import luna.app: the reloader parent must not load .env into its
# environment, or workers inherit stale values and an edited .env never takes effect.
def main() -> None:
    host = os.getenv("LUNA_HOST", "127.0.0.1")
    try:
        port = int(os.getenv("LUNA_PORT", "8000"))
    except ValueError:
        port = 8000
    uvicorn.run("luna.app:app", host=host, port=port, reload=True, reload_dirs=["luna"])


if __name__ == "__main__":
    main()
