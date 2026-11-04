# SPDX-License-Identifier: MIT
# This file is part of Luna's clip pipeline. See luna/clipper/LICENSE and
# THIRD_PARTY_NOTICES.md for the upstream notice.

"""Burn transcript segments into clips as rendered images.

Common FFmpeg builds, including Homebrew's, ship without the subtitles, ass and drawtext
filters. The overlay filter is always there, so the text is drawn with Pillow instead.
"""
import math
import os
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

MAX_LINES_PER_CUE = 2

# Windows caps a command line at ~32k chars and every rendered cue costs one
# -i plus a filter term, so past this the graph goes into a script file instead.
MAX_INLINE_OVERLAY_SCREENS = 40

# Pillow's bundled font only covers Latin. Prefer a system TrueType face with
# wider coverage; the path is resolved once and reused for every clip.
_FONT_CANDIDATES = [
    r"C:\Windows\Fonts\segoeui.ttf",
    r"C:\Windows\Fonts\arialuni.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_RESOLVED_FONT_PATH: Optional[str] = None
_FONT_PATH_RESOLVED = False


def _resolve_font_path() -> Optional[str]:
    """Find a usable system font once, including fonts Pillow reports itself."""
    global _RESOLVED_FONT_PATH, _FONT_PATH_RESOLVED
    if _FONT_PATH_RESOLVED:
        return _RESOLVED_FONT_PATH
    _FONT_PATH_RESOLVED = True
    for candidate in _FONT_CANDIDATES:
        try:
            ImageFont.truetype(candidate, 16)
            _RESOLVED_FONT_PATH = candidate
            return _RESOLVED_FONT_PATH
        except (OSError, ValueError):
            continue
    try:
        # matplotlib ships DejaVu on platforms without a path we can hardcode
        from matplotlib import font_manager  # type: ignore
        resolved = font_manager.findfont("DejaVu Sans", fallback_to_default=False)
        ImageFont.truetype(resolved, 16)
        _RESOLVED_FONT_PATH = resolved
    except Exception:
        _RESOLVED_FONT_PATH = None
    return _RESOLVED_FONT_PATH


def _load_font(size: int) -> ImageFont.ImageFont:
    """Return a font with CJK/emoji coverage, falling back to Pillow's default."""
    path = _resolve_font_path()
    if path:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, ValueError):
            pass
    return ImageFont.load_default(size=size)


def segments_for_clip(segments: List[Dict], clip_start: float, clip_end: float) -> List[Dict]:
    """Return segments overlapping the clip, as cues timed from the start of the clip."""
    cues = []
    for seg in sorted(segments, key=lambda s: float(s["start"])):
        text = " ".join(str(seg.get("text", "")).split())
        start = max(float(seg["start"]), clip_start) - clip_start
        end = min(float(seg["end"]), clip_end) - clip_start
        if text and end > start:
            cues.append({"start": start, "end": end, "text": text})
    # Auto-captions overlap, and two cues on screen at once would be drawn on top of each other.
    for current, following in zip(cues, cues[1:]):
        current["end"] = min(current["end"], following["start"])
    return [c for c in cues if c["end"] > c["start"]]


def _wrap(text: str, font: ImageFont.ImageFont, max_width: int) -> List[str]:
    lines: List[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    return lines + [current] if current else lines


def split_cue(cue: Dict, lines: List[str]) -> List[Tuple[float, float, List[str]]]:
    """Split a long cue into two-line screens, timed in proportion to their length."""
    screens = [lines[i:i + MAX_LINES_PER_CUE] for i in range(0, len(lines), MAX_LINES_PER_CUE)]
    total_chars = sum(len(line) for line in lines) or 1
    duration = cue["end"] - cue["start"]
    result = []
    start = cue["start"]
    for screen in screens:
        end = start + duration * sum(len(line) for line in screen) / total_chars
        result.append((start, end, screen))
        start = end
    return result


def _draw_screen(lines: List[str], font: ImageFont.ImageFont, stroke: int) -> Image.Image:
    text = "\n".join(lines)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    left, top, right, bottom = probe.multiline_textbbox((0, 0), text, font=font, align="center", stroke_width=stroke)
    image = Image.new("RGBA", (math.ceil(right - left) + 2, math.ceil(bottom - top) + 2), (0, 0, 0, 0))
    ImageDraw.Draw(image).multiline_text(
        (1 - left, 1 - top), text, font=font, fill="white", align="center",
        stroke_width=stroke, stroke_fill="black",
    )
    return image


def render_cues(cues: List[Dict], frame_w: int, frame_h: int, out_dir: str) -> List[Tuple[float, float, str]]:
    """Render cues to PNG files and return (start, end, path) for each screen."""
    size = max(12, int(min(frame_w, frame_h) * 0.055))
    # Pillow's bundled default has no CJK or emoji glyphs; _load_font finds a
    # system face that does, or falls back to the default when none exists
    font = _load_font(size)
    stroke = max(1, size // 10)
    rendered = []
    for cue in cues:
        lines = _wrap(cue["text"], font, int(frame_w * 0.9))
        for start, end, screen in split_cue(cue, lines):
            path = os.path.join(out_dir, f"cue_{len(rendered):04d}.png")
            _draw_screen(screen, font, stroke).save(path)
            rendered.append((start, end, path))
    return rendered


def overlay_args(rendered: List[Tuple[float, float, str]], base_filter: str) -> List[str]:
    """Build the FFmpeg inputs and filter graph, with the video source already as input 0."""
    inputs: List[str] = []
    graph = [f"[0:v]{base_filter or 'null'}[v0]"]
    for i, (start, end, path) in enumerate(rendered, 1):
        inputs += ["-i", path]
        graph.append(
            f"[v{i - 1}][{i}:v]overlay=x=(W-w)/2:y=H*0.86-h:"
            f"enable='between(t,{start:.3f},{end:.3f})'[v{i}]"
        )
    return [*inputs, "-filter_complex", ";".join(graph), "-map", f"[v{len(rendered)}]", "-map", "0:a?"]


def overlay_args_script(rendered: List[Tuple[float, float, str]], base_filter: str, script_path: str) -> List[str]:
    """Like overlay_args, but write the filtergraph to a file ffmpeg reads itself."""
    args = overlay_args(rendered, base_filter)
    graph_index = args.index("-filter_complex")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(args[graph_index + 1])
    return [*args[:graph_index], "-filter_complex_script", script_path, *args[graph_index + 2:]]
