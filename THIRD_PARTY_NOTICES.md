# Third-Party Notices

Luna itself is licensed under the GNU Affero General Public License, version 3 or later.
See [LICENSE](LICENSE) and [NOTICE](NOTICE). This file records the third-party code and
licenses that ship with it.

## Clip pipeline (MIT)

`luna/clipper/` contains code based on [AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) by Anil Chandra Naidu Matcha. The upstream repository distributes that code under the MIT License. Its copyright and permission notice are preserved in [`luna/clipper/LICENSE`](luna/clipper/LICENSE), and each file in that directory carries an `SPDX-License-Identifier: MIT` header, except `highlights.py`.

Luna contributors have changed this code. They moved it from `AI-Clipper/shorts_generator/` to `luna/clipper/`, removed the MuAPI and CLI backends, and added `subtitles.py`. These changes do not alter the upstream copyright or license, and Luna makes no ownership claim over the upstream code. The MIT copyright notice names the upstream author and has not been edited.

MIT is compatible with the AGPL: the combined work is distributed under AGPL-3.0-or-later while the MIT-licensed component keeps its own terms. Anyone receiving Luna also receives the MIT notice, so the rights MIT grants cannot be withdrawn.

`luna/clipper/highlights.py` is the exception. The upstream copy credited its selection logic to ViralVadoo's `transcript_analysis/highlight_generator.py`, whose license Luna could not confirm, so Luna replaced it with its own implementation, written without reference to that code. The file is Luna original code under AGPL-3.0-or-later and carries that header.

## Luna original code (AGPL-3.0-or-later)

Everything outside `luna/clipper/`, plus `luna/clipper/highlights.py`, is Copyright (C) 2026 Miqdad and licensed under the GNU Affero General Public License, version 3 or later. Source files carry an `SPDX-License-Identifier: AGPL-3.0-or-later` header. The AGPL requires anyone who distributes a modified version, or lets others use one over a network, to offer the corresponding source under the same license.

The license does not grant trademark rights. The Luna name and logo remain with the project and may not be used to promote a modified version or to suggest endorsement.

## Dependencies

Dependencies are installed from `requirements.txt` under their own licenses, and Luna does not relicense them. Published Docker images also include FFmpeg and FFprobe from Debian, under FFmpeg's own license terms. The optional local Whisper provider installs `faster-whisper` from `requirements-whisper.txt`, also under its own license.

## Icons and media

The platform logos in `luna/assets/` are trademarks of their respective owners (YouTube/Google, Instagram/Meta, TikTok/ByteDance) and are used only to identify the supported services. They are not covered by Luna's license.
