# SPDX-License-Identifier: MIT
# This file is part of Luna's clip pipeline. See luna/clipper/LICENSE and
# THIRD_PARTY_NOTICES.md for the upstream notice.

"""Clip ranking through an OpenAI-compatible endpoint or Gemini."""
import threading
import time
from typing import Optional

from .config import gemini_model, llm_provider, openai_base_url, openai_model, require_gemini_key, require_openai_key

# Default HTTP timeouts (ms) for google-genai so hung 504/overload calls fail fast instead of stalling 10+ minutes.
GEMINI_TEXT_TIMEOUT_MS = 45_000
GEMINI_AUDIO_TIMEOUT_MS = 120_000


class GeminiFallbackExhaustedError(RuntimeError):
    """Raised when every Gemini model in the fallback cascade has already failed."""

# Some self-hosted OpenAI-compatible endpoints return 400 for response_format.
# Remember the first rejection so later calls skip JSON mode instead of paying
# for a failed round trip every time.
_OPENAI_JSON_MODE_SUPPORTED = True


def _response_format_rejected(exc: Exception) -> bool:
    """True when an endpoint refuses response_format itself, not the request."""
    if isinstance(exc, TypeError):
        return True
    message = str(exc).lower()
    return "response_format" in message or "json_object" in message


def call_openai_llm(prompt: str) -> str:
    from openai import OpenAI  # imported here because it adds about 0.3 s to app startup

    global _OPENAI_JSON_MODE_SUPPORTED
    client = OpenAI(api_key=require_openai_key(), base_url=openai_base_url(), timeout=60, max_retries=2)
    request = {
        "model": openai_model(),
        "temperature": 0.7,
        "messages": [{"role": "user", "content": prompt}],
    }
    if _OPENAI_JSON_MODE_SUPPORTED:
        try:
            response = client.chat.completions.create(**request, response_format={"type": "json_object"})
            return response.choices[0].message.content or ""
        except Exception as e:
            if not _response_format_rejected(e):
                raise
            _OPENAI_JSON_MODE_SUPPORTED = False
            print(
                f"[llm/openai] endpoint rejected response_format ({e}), continuing without JSON mode",
                flush=True,
            )
    response = client.chat.completions.create(**request)
    return response.choices[0].message.content or ""


GEMINI_FALLBACK_MODELS = (
    "gemini-3.8-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.7-flash",
    "gemini-3.6-flash",
)
_GEMINI_UNSUPPORTED_MODEL_TOKENS = ("tts", "image", "embedding", "live", "native-audio", "veo", "imagen", "omni")


def build_gemini_client(api_key: str, *, timeout_ms: int = GEMINI_TEXT_TIMEOUT_MS):
    """Create a google-genai Client with an explicit HTTP timeout and SDK retries disabled.

    Disabling hidden SDK retries (attempts=1) keeps failover under our cascade's control
    instead of multiplying 5x SDK retries across every model and highlight window.
    """
    try:
        from google import genai  # type: ignore
        from google.genai import types as genai_types  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for LLM_PROVIDER=gemini. Install it with:\n"
            "    pip install -r requirements.txt"
        ) from e

    try:
        http_options = genai_types.HttpOptions(
            timeout=timeout_ms,
            retry_options=genai_types.HttpRetryOptions(attempts=1),
        )
        return genai.Client(api_key=api_key, http_options=http_options)
    except Exception:
        return genai.Client(api_key=api_key)


def _is_transient_gemini_error(err_str: str) -> bool:
    low = err_str.lower()
    return any(
        tok in low
        for tok in (
            "503",
            "unavailable",
            "504",
            "deadline_exceeded",
            "deadline expired",
            "429",
            "resource_exhausted",
            "timeout",
            "timed out",
        )
    )


def _discover_gemini_flash_models(client, excluded: set) -> list[str]:
    """Query active generateContent Flash models as a last-resort fallback on 404/503."""
    found = []
    try:
        for m in client.models.list():
            name = (getattr(m, "name", None) or "").removeprefix("models/")
            if not name or name in excluded or "flash" not in name.lower():
                continue
            if any(tok in name.lower() for tok in _GEMINI_UNSUPPORTED_MODEL_TOKENS):
                continue
            actions = getattr(m, "supported_actions", None) or []
            if actions and "generateContent" not in actions:
                continue
            found.append(name)
    except Exception:
        return []
    # Prefer stable flash models over preview variants, newest version first.
    stable = sorted((n for n in found if "preview" not in n.lower()), reverse=True)
    previews = sorted((n for n in found if "preview" in n.lower()), reverse=True)
    return (stable + previews)[:3]


def gemini_generate_with_fallback(
    client,
    *,
    contents,
    config,
    log_prefix: str = "[llm/gemini]",
    cancel_event: Optional[threading.Event] = None,
):
    """Call Gemini generate_content with fast model failover on 503/504/429/timeout and 404 discovery."""
    models_to_try = []
    for m in (gemini_model(), *GEMINI_FALLBACK_MODELS):
        if m and m not in models_to_try:
            models_to_try.append(m)

    transient_err = None
    last_err = None
    transient_models = []
    discovered_added = False
    idx = 0

    def _check_cancel():
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("CANCELLED_BY_USER")

    # Pass 1: try each model once so a 503/504 spike fails over immediately to a healthy model.
    while idx < len(models_to_try):
        _check_cancel()
        model_name = models_to_try[idx]
        idx += 1
        try:
            print(f"{log_prefix} requesting model={model_name} (attempt 1)...", flush=True)
            response = client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )
            if response and getattr(response, "text", None):
                return response
            last_err = RuntimeError(f"Empty response from model={model_name}")
        except Exception as e:
            if str(e) == "CANCELLED_BY_USER":
                raise
            err_str = str(e)
            last_err = e
            print(f"{log_prefix} model={model_name} attempt 1 failed: {err_str}", flush=True)
            if "400" in err_str or "401" in err_str or "403" in err_str:
                raise e
            if _is_transient_gemini_error(err_str):
                transient_err = e
                transient_models.append(model_name)
        if idx == len(models_to_try) and not discovered_added:
            discovered_added = True
            for extra in _discover_gemini_flash_models(client, set(models_to_try)):
                models_to_try.append(extra)

    # Pass 2: if every model failed and at least one hit a transient 503/504/429, do one short retry.
    if transient_models:
        _check_cancel()
        time.sleep(2)
        for model_name in transient_models[:2]:
            _check_cancel()
            try:
                print(f"{log_prefix} retrying model={model_name} (attempt 2)...", flush=True)
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config,
                )
                if response and getattr(response, "text", None):
                    return response
            except Exception as e:
                if str(e) == "CANCELLED_BY_USER":
                    raise
                err_str = str(e)
                transient_err = e
                last_err = e
                print(f"{log_prefix} model={model_name} attempt 2 failed: {err_str}", flush=True)
                if "400" in err_str or "401" in err_str or "403" in err_str:
                    raise e

    final_err = transient_err or last_err or RuntimeError("Failed to generate content from Gemini API.")
    raise GeminiFallbackExhaustedError(str(final_err)) from final_err


def call_gemini_llm(prompt: str, cancel_event: Optional[threading.Event] = None) -> str:
    """Gemini backend with explicit timeout and fast model failover for 503/504/429 spikes."""
    client = build_gemini_client(require_gemini_key(), timeout_ms=GEMINI_TEXT_TIMEOUT_MS)
    response = gemini_generate_with_fallback(
        client,
        contents=prompt,
        config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "max_output_tokens": 8192,
        },
        log_prefix="[llm/gemini]",
        cancel_event=cancel_event,
    )
    return response.text or ""


def call_llm(prompt: str, cancel_event: Optional[threading.Event] = None) -> str:
    provider = llm_provider()
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt, cancel_event=cancel_event)
    raise RuntimeError(f"Unknown LLM_PROVIDER={provider!r}. Use 'openai' or 'gemini'.")
