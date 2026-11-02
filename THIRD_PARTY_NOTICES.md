# Third-Party Notices

## Clip pipeline

`luna/clipper/` contains code based on [AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) by Anil Chandra Naidu Matcha. The upstream repository distributes that code under the MIT License. Its copyright and permission notice are preserved in [`luna/clipper/LICENSE`](luna/clipper/LICENSE).

Luna contributors have changed this code. They moved it from `AI-Clipper/shorts_generator/` to `luna/clipper/`, removed the MuAPI and CLI backends, and added `subtitles.py`. These changes do not alter the upstream copyright or license, and Luna makes no ownership claim over the upstream code. The MIT copyright notice names the upstream author and has not been edited.

The upstream `shorts_generator/highlights.py` identifies its highlight-selection logic as ported from ViralVadoo's `transcript_analysis/highlight_generator.py`, and `luna/clipper/highlights.py` is a modified copy that keeps that credit. Luna has not confirmed the license of the ViralVadoo original. This notice records the provenance and grants no rights beyond those its authors gave.

## Luna

The root PolyForm Noncommercial License, with its required notice, applies to Luna's original code outside `luna/clipper/`. It does not replace or remove rights granted for the MIT-licensed component.

## Dependencies

Dependencies are installed from `requirements.txt` under their own licenses, and Luna does not relicense them. Published Docker images also include FFmpeg from Debian, under FFmpeg's own license terms.
