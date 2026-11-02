# Luna Media Studio

A local web app for downloading video and audio from YouTube, Instagram, and TikTok, organizing files in Media Vault, and generating AI-assisted short clips.

## Requirements

- Python 3.10 or newer.
- FFmpeg and FFprobe installed and available on `PATH` for merging streams, audio extraction, and clip rendering.
- Internet access for downloads and AI providers.
- API keys are only required for AI Clip. Provider quotas and terms apply.

## Requirements by feature

| Feature | API keys | Other requirements |
|---|---|---|
| Download video/audio from YouTube, TikTok, or Instagram | None | Internet. FFmpeg/FFprobe are needed for merged formats and audio. Some sources may require cookies or restrict downloads. |
| AI Clip with the default configuration | Gemini and Groq | FFmpeg/FFprobe and internet. Groq transcribes audio; Gemini selects and ranks clips. |
| Rank clips with OpenAI | OpenAI | Set `OPENAI_API_KEY` and `LLM_PROVIDER=openai` in `.env`. |
| Transcribe with local Whisper | None for transcription | Install `pip install -r AI-Clipper/requirements-local.txt`, then set `LOCAL_TRANSCRIBE_PROVIDER=whisper`. Whisper downloads its model on first use. Clip ranking still needs an LLM API key. |
| Cookies for restricted videos | None | Optional. Add your own cookies in Settings. Treat `cookies.txt` as a secret. |

The default `.env.example` uses Groq for transcription and Gemini for clip ranking. Luna sends the audio or transcript needed for these tasks to the selected provider. Avoid using private content if you do not want it processed by a third party.

## Install

```bash
git clone <REPOSITORY_URL>
cd <REPOSITORY_FOLDER>
python -m venv .venv
```

Activate the environment:

```powershell
# Windows PowerShell
.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Install Python dependencies:

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Copy `.env.example` to `.env`. Media downloads do not need API keys. To use AI Clip, add `GEMINI_API_KEY` and `GROQ_API_KEY`; you can also enter them in the app's Settings page. Saving or validating a key in Settings updates `.env` and applies to the next job. Never commit `.env` or `cookies.txt`.

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

```bash
# macOS / Linux
cp .env.example .env
```

Install FFmpeg and FFprobe for your operating system and confirm both commands work in a terminal. Start Luna:

```bash
python app.py
```

Open [http://localhost:8000](http://localhost:8000). After completing the setup above, you can also use `npm run dev` (same as `python app.py`, with auto-reload) or `npm start` (no reload). Neither creates a virtual environment or installs anything.

Luna is intended for local use. Do not expose its port to a public network without adding authentication and deployment security controls.

## Development

Python code reloads on save with `python app.py`. `templates/*.html` are read on every request, so refresh the browser. Set `MEDIA_STORAGE_DIR=media-vault` in `.env` to keep test downloads apart from your real library. `.python-version` pins the version CI uses (3.12).

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

Inside a container, the Settings folder picker and the Open Folder button cannot reach your desktop. Open `media-vault/` on the host instead. Media Vault stays at that path, and changing the storage folder in Settings does not survive a restart.

## Production

Luna has no authentication, and its API can read settings, overwrite API keys and move files. Keep it on `127.0.0.1`, or put an authenticating proxy in front of it before exposing it. Run a single process, because job state is held in memory.

- Without Docker: `npm start`.
- With Docker: pushing a `v*` tag publishes `ghcr.io/fajarhide/luna`. Run it with `LUNA_IMAGE=ghcr.io/fajarhide/luna:<tag> docker compose up -d --no-build`, after creating the host files above. The image is built for amd64 only.

## Storage

Temporary downloads go to `output/`. Media Vault uses `MEDIA_STORAGE_DIR` when set. The Windows default is `D:\\Luna-Media`; on macOS/Linux it defaults to the project's `output/` directory. Choose a writable location with enough free space.

## Notes

- Site changes or access restrictions can affect `yt-dlp` downloads.
- Cookies are optional and sensitive. Do not share or commit exported cookie files.

## License

Luna's original code outside `AI-Clipper/` is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). It permits noncommercial use and modifications under its terms; commercial use is not permitted. This makes Luna source-available, not Open Source under the Open Source Definition.

The `AI-Clipper/` component is based on [AI-Youtube-Shorts-Generator](https://github.com/Anil-matcha/AI-Youtube-Shorts-Generator) and remains under its upstream MIT License, included at `AI-Clipper/LICENSE`. The MIT license permits commercial use of that component and cannot be withdrawn by Luna's license. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for scope and attribution details.

## Tests

Install test dependencies and run the suite:

```bash
pip install -r requirements-dev.txt
python -m unittest discover -v
```
