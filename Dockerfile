# The tag is used for convenience only; pin by digest in production.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="Luna" \
      org.opencontainers.image.description="Local media downloader and AI shorts studio" \
      org.opencontainers.image.licenses="AGPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/miqdadbadjuber/luna"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app
COPY requirements.txt requirements-whisper.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Local Whisper is optional and heavy: build with --build-arg WITH_WHISPER=1 to enable it.
ARG WITH_WHISPER=0
RUN if [ "$WITH_WHISPER" = "1" ]; then pip install --no-cache-dir -r requirements-whisper.txt; fi
COPY . .

RUN useradd --uid 1000 --create-home luna \
    && mkdir -p output media-vault static \
    && chown -R luna:luna /app
USER luna

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=30s --retries=6 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4)"]

# One process only: job state lives in memory, so extra workers would lose track of jobs.
CMD ["python", "-m", "uvicorn", "luna.app:app", "--host", "0.0.0.0", "--port", "8000"]
