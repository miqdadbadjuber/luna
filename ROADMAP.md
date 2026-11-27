# Roadmap

How Luna grows from a local media downloader into a complete local-first clipping and editing workspace. New to Luna? Read [README.md](README.md) first for setup and usage.

## Where we are

The latest release is [v2.0.0](https://github.com/miqdadbadjuber/luna/releases/tag/v2.0.0). It adds Full Video Studio for non-destructive editing, lossless and GPU-accelerated exports, strict Workspace type isolation, and an updated in-app Guide. See the [release notes](https://github.com/miqdadbadjuber/luna/releases/tag/v2.0.0) for the full list of changes.

## What's next

> **Note:** This roadmap is tentative. Features, priorities, and version numbers may change at any time.

| Version | Item | What it means |
|---------|------|---------------|
| v2.1.0 | Studio for Video Trimmer | Open manually trimmed clips in Luna Studio with the same non-destructive editing, audio, and export workflow. |
| v2.2.0 | Subtitle styles & Full Video captions | Expand curated caption styles alongside Selene and bring subtitle editing into Full Video Studio. |
| v2.3.0 | Batch export & workspace presets | Export multiple clips from one workspace in a single pass and reuse saved Studio export and look presets. |

## Release history

Every version below links to its notes on [GitHub](https://github.com/miqdadbadjuber/luna/releases).

| Version | What shipped |
|---------|--------------|
| [v1.0.0](https://github.com/miqdadbadjuber/luna/releases/tag/v1.0.0) | First public release: local downloads for YouTube, Reels, and TikTok, Media Vault workspaces, AI Short Clips, and the isolated AI Clipper Studio with Selene subtitles and background music export. Full HD Video becomes the default YouTube mode. |
| [v1.1.0](https://github.com/miqdadbadjuber/luna/releases/tag/v1.1.0) | Release-based in-app updater: checks GitHub Releases with ETag caching, displays release notes inside an expandable update dialog, and notifies users on startup with a 5-second toast. |
| [v1.2.0](https://github.com/miqdadbadjuber/luna/releases/tag/v1.2.0) | ElevenLabs Scribe (`scribe_v3`) added as a speech-to-text provider for videos without captions, with word-to-segment grouping, scoped key validation, and MCP status reporting. |
| [v2.0.0](https://github.com/miqdadbadjuber/luna/releases/tag/v2.0.0) | Major release adding Full Video Studio (multi-block timeline cuts, Auto Cut Silence, 2D Speed Curve, aspect ratio reframing, color looks and adjustments, Smart Audio, multi-layer audio with volume keyframes, lossless stream-copy and GPU-accelerated export, and feature-specific full-render confirmation), strict Workspace type isolation with dedicated Audio MP3 labels, an updated in-app Guide, and custom dark tooltips. |
