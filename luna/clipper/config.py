import os

from dotenv import load_dotenv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1").rstrip("/")
GROQ_WHISPER_MODEL = os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3-turbo")

LOCAL_WHISPER_MODEL = os.getenv("LOCAL_WHISPER_MODEL", "base")
LOCAL_WHISPER_DEVICE = os.getenv("LOCAL_WHISPER_DEVICE", "auto")  # auto / cpu / cuda
_raw_out = os.getenv("LOCAL_OUTPUT_DIR", "output").strip()
if "=" in _raw_out or not _raw_out:
    _raw_out = "output"
LOCAL_OUTPUT_DIR = _raw_out


# VAD (Voice Activity Detection) settings for faster-whisper.
# Disabled by default because VAD is too aggressive on mixed speech/music content.
LOCAL_WHISPER_VAD_FILTER = os.getenv("LOCAL_WHISPER_VAD_FILTER", "false").strip().lower() == "true"
_vad_params_env = os.getenv("LOCAL_WHISPER_VAD_PARAMETERS", "")
if _vad_params_env:
    import json
    LOCAL_WHISPER_VAD_PARAMETERS = json.loads(_vad_params_env)
else:
    # Match faster-whisper defaults when VAD is enabled
    LOCAL_WHISPER_VAD_PARAMETERS = {
        "threshold": 0.5,
        "min_speech_duration_ms": 250,
        "max_speech_duration_s": float("inf"),
        "min_silence_duration_ms": 2000,
        "speech_pad_ms": 400,
    }

TRANSCRIBE_PROVIDER_LABELS = {
    "groq": "Groq Cloud Whisper",
    "gemini": "Gemini AI",
    "whisper": "Faster-Whisper Local",
}


def transcribe_provider() -> str:
    """"groq" uses hosted Whisper, "gemini" the Gemini audio API, "whisper" faster-whisper on this machine."""
    return os.getenv("LOCAL_TRANSCRIBE_PROVIDER", "").strip().lower() or "groq"


def transcribe_provider_label() -> str:
    provider = transcribe_provider()
    return TRANSCRIBE_PROVIDER_LABELS.get(provider, provider)


# These read the environment on each call so a Settings save applies to the next job.
# `or` also covers the blank values .env files carry: the SDK would use "" as a literal base URL.
def llm_provider() -> str:
    """LLM_PROVIDER wins. Left blank, a Gemini-only setup still works without editing .env."""
    configured = os.getenv("LLM_PROVIDER", "").strip().lower()
    if configured:
        return configured
    if not os.getenv("OPENAI_API_KEY", "").strip() and os.getenv("GEMINI_API_KEY", "").strip():
        return "gemini"
    return "openai"


def openai_base_url() -> str:
    return (os.getenv("OPENAI_BASE_URL", "").strip() or DEFAULT_OPENAI_BASE_URL).rstrip("/")


def openai_model() -> str:
    return os.getenv("OPENAI_MODEL", "").strip() or DEFAULT_OPENAI_MODEL


def require_openai_key() -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY is not set. Add a key for your OpenAI-compatible provider in Settings or .env."
        )
    return api_key


def require_gemini_key() -> str:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set. Add it in Settings or .env, or choose another provider.")
    return api_key


def require_groq_key() -> str:
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it in Settings or .env, or set LOCAL_TRANSCRIBE_PROVIDER=whisper."
        )
    return api_key
