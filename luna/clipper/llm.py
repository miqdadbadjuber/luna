# SPDX-License-Identifier: MIT
# This file is part of Luna's clip pipeline. See luna/clipper/LICENSE and
# THIRD_PARTY_NOTICES.md for the upstream notice.

"""Clip ranking through an OpenAI-compatible endpoint or Gemini."""
import time

from .config import gemini_model, llm_provider, openai_base_url, openai_model, require_gemini_key, require_openai_key

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


def call_gemini_llm(prompt: str) -> str:
    """Gemini backend with automatic model fallback & retry for 503/429 spikes."""
    try:
        from google import genai  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for LLM_PROVIDER=gemini. Install it with:\n"
            "    pip install -r requirements.txt"
        ) from e

    api_key = require_gemini_key()
    client = genai.Client(api_key=api_key)

    # Priority cascade: user's configured model first, followed by reliable fallbacks
    models_to_try = []
    for m in [gemini_model(), "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
        if m and m not in models_to_try:
            models_to_try.append(m)

    last_err = None
    for model_name in models_to_try:
        for attempt in range(1, 3):
            try:
                print(f"[llm/gemini] requesting model={model_name} (attempt {attempt})...", flush=True)
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        "temperature": 0.2,
                        "response_mime_type": "application/json",
                        "max_output_tokens": 8192,
                    },
                )
                if response.text:
                    return response.text
            except Exception as e:
                err_str = str(e)
                last_err = e
                print(f"[llm/gemini] model={model_name} attempt {attempt} failed: {err_str}", flush=True)
                if "400" in err_str or "401" in err_str or "403" in err_str:
                    # bad key or bad request: retrying and switching models cannot fix it
                    raise e
                if "503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    time.sleep(2 * attempt)
                    continue
                else:
                    break

    raise last_err or RuntimeError("Failed to generate content from Gemini API.")


def call_llm(prompt: str) -> str:
    provider = llm_provider()
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt)
    raise RuntimeError(f"Unknown LLM_PROVIDER={provider!r}. Use 'openai' or 'gemini'.")
