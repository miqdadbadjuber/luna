"""Local LLM backend — OpenAI, Gemini, or Groq, selected by LLM_PROVIDER."""
from ..config import (
    GEMINI_MODEL,
    GROQ_BASE_URL,
    GROQ_MODEL,
    LLM_PROVIDER,
    OPENAI_MODEL,
    require_gemini_key,
    require_groq_key,
    require_openai_key,
)


def call_openai_llm(prompt: str) -> str:
    """OpenAI Chat Completions backend used by --mode local."""
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai is required for --mode local. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    client = OpenAI(api_key=require_openai_key())
    response = client.chat.completions.create(
        model=OPENAI_MODEL,
        temperature=0.7,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def call_gemini_llm(prompt: str) -> str:
    """Gemini backend with automatic model fallback & retry for 503/429 spikes."""
    try:
        from google import genai  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "google-genai is required for LLM_PROVIDER=gemini. Install it with:\n"
            "    pip install -r requirements-local.txt"
        ) from e

    import time
    api_key = require_gemini_key()
    client = genai.Client(api_key=api_key)

    # Priority cascade: user's configured model first, followed by reliable fallbacks
    models_to_try = []
    for m in [GEMINI_MODEL, "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
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
                if "503" in err_str or "UNAVAILABLE" in err_str or "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    time.sleep(2 * attempt)
                    continue
                else:
                    break

    # If all Gemini models failed and Groq API key is present in environment, fallback to Groq
    import os
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    if groq_key:
        print("[llm/gemini] all Gemini models failed, falling back to Groq...", flush=True)
        try:
            return call_groq_llm(prompt)
        except Exception as ge:
            print(f"[llm/gemini] groq fallback failed: {ge}", flush=True)

    raise last_err or RuntimeError("Failed to generate content from Gemini API.")


def call_groq_llm(prompt: str) -> str:
    """Groq backend used by --mode local when LLM_PROVIDER=groq.

    Groq's API is OpenAI-compatible, so we reuse the openai SDK pointed at
    Groq's base URL instead of adding a new dependency.
    """
    try:
        from openai import OpenAI  # type: ignore
    except ImportError as e:
        raise RuntimeError(
            "openai is required for --mode local (also used for the Groq backend). "
            "Install it with:\n    pip install -r requirements-local.txt"
        ) from e

    client = OpenAI(api_key=require_groq_key(), base_url=GROQ_BASE_URL)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        temperature=0.2,
        max_tokens=4096,
        response_format={"type": "json_object"},
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


def call_local_llm(prompt: str) -> str:
    """Dispatch to the configured local LLM provider."""
    provider = (LLM_PROVIDER or "openai").strip().lower()
    if provider == "openai":
        return call_openai_llm(prompt)
    if provider == "gemini":
        return call_gemini_llm(prompt)
    if provider == "groq":
        return call_groq_llm(prompt)
    raise RuntimeError(
        f"Unknown LLM_PROVIDER={provider!r}. Use 'openai', 'gemini', or 'groq'."
    )