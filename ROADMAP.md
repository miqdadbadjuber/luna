# Roadmap

How Luna grows from a local media downloader into a complete local-first clipping and editing workspace. New to Luna? Read [README.md](README.md) first for setup and usage.

## Where we are

The latest release is [v1.2.0](https://github.com/miqdadbadjuber/luna/releases/tag/v1.2.0): local downloads for YouTube, Reels, and TikTok, AI Short Clips with four transcription providers, a built-in AI Clipper Studio, and a release-based in-app updater. What changed is in the [release notes](https://github.com/miqdadbadjuber/luna/releases/tag/v1.2.0), and the queue below is what comes next.

## What's next

| Version | Item | What it means |
|---------|------|---------------|
| v1.3.0 | Studio for Full Video | Open downloaded Full HD videos in Luna Studio to add subtitles, background music, and export without leaving the workspace. |
| v1.4.0 | Studio for Video Trimmer | Open manually trimmed clips in Luna Studio with the same non-destructive subtitle, audio, and export workflow. |
| v1.5.0 | Inline subtitle editing & extra styles | Fix transcript typos directly in Studio before exporting, and choose from a small curated set of caption styles alongside Selene. |
| v1.6.0 | Timeline trim & batch export | Adjust clip start and end points inside Studio and export multiple clips from one workspace in a single pass. |

## Release history

Every version below links to its notes on [GitHub](https://github.com/miqdadbadjuber/luna/releases).

| Version | What shipped |
|---------|--------------|
| [v1.0.0](https://github.com/miqdadbadjuber/luna/releases/tag/v1.0.0) | First public release: local downloads for YouTube, Reels, and TikTok, Media Vault workspaces, AI Short Clips, and the isolated AI Clipper Studio with Selene subtitles and background music export. Full HD Video becomes the default YouTube mode. |
| [v1.1.0](https://github.com/miqdadbadjuber/luna/releases/tag/v1.1.0) | Release-based in-app updater: checks GitHub Releases with ETag caching, displays release notes inside an expandable update dialog, and notifies users on startup with a 5-second toast. |
| [v1.2.0](https://github.com/miqdadbadjuber/luna/releases/tag/v1.2.0) | ElevenLabs Scribe (`scribe_v3`) added as a speech-to-text provider for videos without captions, with word-to-segment grouping, scoped key validation, and MCP status reporting. |
