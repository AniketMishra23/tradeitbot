# chat_engine.py — AI chat engine for Trade It
#
# Provider priority:
#   1. Groq  (llama-3.3-70b) — free, fast  → console.groq.com
#   2. Gemini 2.0 Flash       — free fallback → ai.google.dev
#
# Set keys in .env:
#   GROQ_API_KEY=...
#   GEMINI_API_KEY=...

import os
import requests
from dotenv import load_dotenv

load_dotenv()

GROQ_API_URL   = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL     = "llama-3.3-70b-versatile"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"

# System prompt shared across both providers
SYSTEM_PROMPT = """You are an experienced multi-strategy trader and risk manager covering
global markets — Indian equities (NSE/BSE), US stocks, crypto, and more.

You help users understand:
- Technical analysis: RSI, MACD, EMA, Bollinger Bands, ATR, volume
- Trade signals: entry zones, stop losses, targets, risk/reward ratios
- Fundamental analysis: P/E, ROE, ROCE, earnings, balance sheet
- Macro factors: central bank policy, sector themes, global risk sentiment
- Risk management: position sizing, drawdown control, volatility

Rules:
- Only use data provided to you or widely known facts. Never invent prices.
- State clearly when you don't know something.
- Keep answers concise. Use ₹ for Indian rupees, $ for US.
- Never present a trade recommendation as certain. Always note uncertainty.
- You are a decision-support tool, not a registered investment advisor.

When explaining a signal result, use the context provided — do not re-run analysis."""


def get_provider() -> str:
    """Return 'groq', 'gemini', or 'none' based on available API keys."""
    if os.getenv("GROQ_API_KEY"):   return "groq"
    if os.getenv("GEMINI_API_KEY"): return "gemini"
    return "none"


def provider_label() -> str:
    """Human-readable name of the active AI provider."""
    return {
        "groq":   "Groq (llama-3.3-70b)",
        "gemini": "Gemini 2.0 Flash",
        "none":   "No AI — add API key to .env",
    }[get_provider()]


def _chat_groq(messages: list[dict], max_tokens: int = 1024) -> str:
    """Send messages to Groq and return the reply text."""
    resp = requests.post(
        GROQ_API_URL,
        json={"model": GROQ_MODEL, "messages": messages, "max_tokens": max_tokens},
        headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}", "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _chat_gemini(messages: list[dict], max_tokens: int = 1024) -> str:
    """Send messages to Gemini and return the reply text. Converts from OpenAI format."""
    contents = []
    sys_prompt = SYSTEM_PROMPT
    for m in messages:
        if m["role"] == "system":
            sys_prompt = m["content"]
            continue
        role = "user" if m["role"] == "user" else "model"
        contents.append({"role": role, "parts": [{"text": m["content"]}]})

    if contents and contents[0]["role"] == "user":
        contents[0]["parts"][0]["text"] = (
            f"[System instructions]\n{sys_prompt}\n\n" + contents[0]["parts"][0]["text"]
        )

    resp = requests.post(
        f"{GEMINI_API_URL}?key={os.getenv('GEMINI_API_KEY')}",
        json={"contents": contents, "generationConfig": {"maxOutputTokens": max_tokens}},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()


def chat(
    user_message: str,
    history: list[dict] | None = None,
    context: str | None = None,
) -> str:
    """
    Send a message to the active AI provider and return the reply.

    Parameters
    ----------
    user_message : the user's text
    history      : recent conversation turns [{role, content}, ...]  (last 10 kept)
    context      : optional signal summary injected before the user message

    Returns a reply string, or an error message if no provider is configured.
    """
    provider = get_provider()
    if provider == "none":
        return (
            "No AI API key configured.\n\n"
            "Add one to your .env file:\n"
            "  GROQ_API_KEY=...   (free at console.groq.com)\n"
            "  GEMINI_API_KEY=... (free at ai.google.dev)"
        )

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history[-10:])

    content = user_message
    if context:
        content = f"[Signal context]\n{context}\n\n[User question]\n{user_message}"
    messages.append({"role": "user", "content": content})

    try:
        return _chat_groq(messages) if provider == "groq" else _chat_gemini(messages)

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else "?"
        if status == 401:
            return f"Invalid {provider.title()} API key — check your .env file."
        if status == 429:
            # Rate limited on Groq — try Gemini fallback
            if provider == "groq" and os.getenv("GEMINI_API_KEY"):
                try:
                    return _chat_gemini(messages)
                except Exception:
                    pass
            return "Rate limit hit. Please wait a moment and try again."
        return f"API error ({status}): {e}"

    except requests.exceptions.Timeout:
        return f"{provider.title()} timed out. Please try again."

    except Exception as e:
        return f"Chat error: {e}"


def chat_with_provider(
    prompt: str,
    provider: str | None = None,
    system_prompt: str | None = None,
    max_tokens: int = 1024,
) -> str:
    """
    Stateless single-shot LLM call used by the agent runner.

    Unlike chat(), this has no conversation history or context injection.
    Raises on failure instead of returning an error string — the caller
    (agents/runner.py) handles retries and fallbacks.
    """
    provider = provider or get_provider()
    if provider == "none":
        raise RuntimeError("No AI provider configured — add GROQ_API_KEY or GEMINI_API_KEY to .env")

    messages = [
        {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
        {"role": "user",   "content": prompt},
    ]

    try:
        if provider == "groq":
            return _chat_groq(messages, max_tokens=max_tokens)
        else:
            return _chat_gemini(messages, max_tokens=max_tokens)

    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response else "?"
        if status == 429 and provider == "groq" and os.getenv("GEMINI_API_KEY"):
            return _chat_gemini(messages, max_tokens=max_tokens)
        raise

    except requests.exceptions.Timeout:
        raise
