# Luna Media Studio

A local web app for downloading video and audio from YouTube, Instagram, and TikTok, organizing files in Media Vault, and generating AI-assisted short clips.

## Requirements

- Python 3.12 or newer, which the installer provides.
- FFmpeg and FFprobe for merging streams, audio extraction, and clip rendering. The installer adds them if they are missing.
- Internet access for downloads and AI providers.
- API keys are only required for AI Clip. Provider quotas and terms apply.

## Requirements by feature

| Feature | API keys | Other requirements |
|---|---|---|
| Download video/audio from YouTube, TikTok, or Instagram | None | Internet. FFmpeg/FFprobe are needed for merged formats and audio. Some sources may require cookies or restrict downloads. |
| AI Clip | OpenAI-compatible or Gemini key, plus Groq or Gemini for videos without subtitles | FFmpeg/FFprobe and internet. The OpenAI-compatible provider ranks clips. YouTube subtitles are used first, then Groq Whisper transcribes the audio. |
| Transcribe with local Whisper | None for transcription | Install `pip install -r requirements-whisper.txt`, then set `LOCAL_TRANSCRIBE_PROVIDER=whisper`. Whisper downloads its model on first use. |
| Cookies for restricted videos | None | Optional. Add your own cookies in Settings. Treat `cookies.txt` as a secret. |

`.env.example` uses an OpenAI-compatible provider for clip ranking and Groq Whisper for transcription. Gemini is an alternative for both. Choose providers in Settings, or with `LLM_PROVIDER` and `LOCAL_TRANSCRIBE_PROVIDER` in `.env`. Luna sends the audio or transcript needed for these tasks to the selected provider. Avoid using private content if you do not want it processed by a third party.

## Install

macOS and Linux:

```bash
git clone https://github.com/miqdadbadjuber/luna && cd luna && ./install.sh
```

Windows PowerShell:

```powershell
git clone https://github.com/miqdadbadjuber/luna; cd luna; powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The installer sets up [uv](https://docs.astral.sh/uv/), Python 3.12, the dependencies, FFmpeg if it is missing, and a default `.env`, then opens Luna at [http://localhost:8000](http://localhost:8000). Nothing is installed system-wide except uv. Add your API keys in Settings, with no file to edit. Downloads need no keys. Start Luna again later with `./start.sh` or `start.bat`.

To install by hand, create a Python 3.12+ virtual environment, run `pip install -r requirements.txt`, copy `.env.example` to `.env`, install FFmpeg and FFprobe, then run `python -m luna`. `npm run dev` and `npm start` only wrap those Python commands from `package.json`; npm is optional sugar, not a Node toolchain, and neither script installs anything.

Media downloads need no API keys. AI Clip needs `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `OPENAI_MODEL` and `GROQ_API_KEY`. Settings saves them to `.env` and applies them to the next job. `GET /api/settings` masks saved keys, so they are not returned in plain text. Never commit `.env` or `cookies.txt`.

Luna is intended for local use. Do not expose its port to a public network without adding authentication and deployment security controls.

## Development

```
luna/            web app: API, storage, Media Vault, templates, assets
luna/clipper/    clip pipeline, under its own MIT license
tests/           unittest suite
```

Python code reloads on save with `python -m luna`. `luna/templates/*.html` are read on every request, so refresh the browser. Set `MEDIA_STORAGE_DIR=media-vault` in `.env` to keep test downloads apart from your real library. `.python-version` pins the version CI uses (3.12).

## AI agents (MCP)

`luna/mcp_server.py` lets an MCP client such as Claude Code start clip jobs, follow them and collect the clips. Install `requirements-mcp.txt`, then register it:

```bash
claude mcp add luna -e LUNA_URL=http://127.0.0.1:8000 -- /path/to/luna/.venv/bin/python /path/to/luna/luna/mcp_server.py
```

See [MCP.md](MCP.md) for the tools, running Luna on another machine and a simulated session.

## Docker

Docker replaces the local Python and FFmpeg install. It needs these host files first, because Compose would otherwise create the missing mounts itself, as root-owned directories:

```bash
cp .env.example .env
touch cookies.txt
mkdir -p output media-vault
```

On Linux, also run `export LUNA_UID=$(id -u) LUNA_GID=$(id -g)` so the container can write to them.

```bash
docker compose up -d --build                                      # production mode
docker compose -f compose.yaml -f compose.dev.yaml up --build     # development, reloads on save
```

Inside a container, the Settings folder picker and the Open Folder button cannot reach your desktop. Open `media-vault/` on the host instead. Media Vault stays at that path: changing the storage folder in Settings has no effect inside the container, because Compose fixes `MEDIA_STORAGE_DIR` to the mounted volume, and the new value is lost on restart.

## Production

Luna has no authentication, and its API can read settings, overwrite API keys and move files. Keep it on `127.0.0.1`, or put an authenticating proxy in front of it before exposing it. Luna only answers requests addressed to `localhost` or `127.0.0.1`; add the proxy's host name to `LUNA_ALLOWED_HOSTS` in `.env`. Run a single process, because job state is held in memory.

- Without Docker: `./start.sh`, `start.bat` or `npm start`.
- With Docker: pushing a `v*` tag publishes `ghcr.io/miqdadbadjuber/luna`. Run it with `LUNA_IMAGE=ghcr.io/miqdadbadjuber/luna:<tag> docker compose up -d --no-build`, after creating the host files above. The image is built for amd64 only.

## Storage

Temporary downloads go to `output/`. Media Vault uses `MEDIA_STORAGE_DIR` when set. The Windows default is `D:\\Luna-Media`; on macOS/Linux it defaults to the project's `output/` directory. Choose a writable location with enough free space.

## Notes

- Site changes or access restrictions can affect `yt-dlp` downloads.
- Cookies are optional and sensitive. Do not share or commit exported cookie files.
- You are responsible for having the rights to the videos you download, cut and publish. The platforms' terms and copyright apply regardless of Luna's license.

## License

Luna is free software under the [GNU Affero General Public License, version 3 or later](LICENSE) (AGPL-3.0-or-later). Copyright (C) 2026 Miqdad.

You may run, study, modify, redistribute, and even sell copies. Two conditions matter:

- **Share the source.** If you distribute a modified version, or let other people use one over a network, you must offer them the complete corresponding source under the same license. The network clause is what keeps a hosted copy from being closed.
- **Keep the notices.** You must keep the copyright and license notices, and say what you changed. The AGPL does not grant trademark rights: the Luna name and logo stay with the project, so you cannot present a modified copy as the original project.

`luna/clipper/` is based on [AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) and stays under its upstream MIT License, included at [`luna/clipper/LICENSE`](luna/clipper/LICENSE). MIT is compatible with the AGPL: the combined work ships under AGPL-3.0-or-later and the MIT notices are preserved. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the full attribution and [CONTRIBUTING.md](CONTRIBUTING.md) if you want to send changes.

A commercial license without the AGPL conditions is available on request through the repository issue tracker.

## Tests

Install test dependencies and run the suite:

```bash
pip install -r requirements-dev.txt
python -m unittest discover -v
```
