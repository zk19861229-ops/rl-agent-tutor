"""LLM wrapper — supports Anthropic native API and OpenRouter (OpenAI-compatible)."""
from __future__ import annotations
import json
import re
import time
from typing import Optional
import httpx
from anthropic import Anthropic, APIConnectionError, APITimeoutError, InternalServerError
from .config import (
    LLM_PROVIDER,
    ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL,
    OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL,
    OPENROUTER_REFERER, OPENROUTER_TITLE,
    LLM_REQUEST_TIMEOUT, LLM_CONNECT_TIMEOUT, LLM_MAX_RETRIES,
    LLM_BACKOFF_BASE, LLM_MAX_TOKEN_SCALE,
)


# Transient network errors worth retrying. OpenRouter / cross-provider routes
# occasionally drop the connection mid-response — that's exactly RemoteProtocolError.
_HTTPX_RETRY = (
    httpx.RemoteProtocolError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.ReadError,
    httpx.WriteError,
    httpx.ConnectError,
)
_ANTHROPIC_RETRY = (APIConnectionError, APITimeoutError, InternalServerError)
_MAX_RETRIES = max(0, LLM_MAX_RETRIES)
_BACKOFF_BASE = max(0.1, LLM_BACKOFF_BASE)  # seconds; doubles each retry


def _retry(fn, *, label: str, retry_on: tuple, max_retries: int = _MAX_RETRIES):
    """Call fn(); retry on transient errors with exponential backoff."""
    last_exc = None
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except retry_on as e:
            last_exc = e
            if attempt == max_retries:
                break
            wait = _BACKOFF_BASE * (2 ** attempt)
            print(f"[llm] {label} attempt {attempt+1}/{max_retries+1} failed: "
                  f"{type(e).__name__}: {e}. retrying in {wait:.0f}s...")
            time.sleep(wait)
    raise last_exc


_anthropic_client: Optional[Anthropic] = None
_or_client: Optional[httpx.Client] = None


def _scaled_tokens(max_tokens: int) -> int:
    scale = max(0.2, min(1.5, LLM_MAX_TOKEN_SCALE))
    return max(256, int(max_tokens * scale))


def _get_anthropic() -> Anthropic:
    global _anthropic_client
    if _anthropic_client is None:
        if not ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill it in, "
                "or set LLM_PROVIDER=openrouter to use OpenRouter."
            )
        kwargs = {
            "api_key": ANTHROPIC_API_KEY,
            "max_retries": 0,
            "timeout": httpx.Timeout(LLM_REQUEST_TIMEOUT, connect=LLM_CONNECT_TIMEOUT),
        }  # we do our own retries
        if ANTHROPIC_BASE_URL:
            kwargs["base_url"] = ANTHROPIC_BASE_URL
        _anthropic_client = Anthropic(**kwargs)
    return _anthropic_client


def _get_openrouter() -> httpx.Client:
    global _or_client
    if _or_client is None:
        key = OPENROUTER_API_KEY or ANTHROPIC_API_KEY
        if not key:
            raise RuntimeError(
                "OPENROUTER_API_KEY not set. Copy .env.example to .env and fill it in."
            )
        _or_client = httpx.Client(
            base_url=OPENROUTER_BASE_URL.rstrip("/"),
            headers={
                "Authorization": f"Bearer {key}",
                "HTTP-Referer": OPENROUTER_REFERER,
                "X-Title": OPENROUTER_TITLE,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(LLM_REQUEST_TIMEOUT, connect=LLM_CONNECT_TIMEOUT),
        )
    return _or_client


def _resolve_model(model: Optional[str]) -> str:
    if model:
        return model
    return OPENROUTER_MODEL if LLM_PROVIDER == "openrouter" else ANTHROPIC_MODEL


# ---------- Anthropic native ----------

def _anthropic_chat(system: str, messages: list[dict], *, model: str,
                    max_tokens: int, temperature: float) -> str:
    def _do():
        msg = _get_anthropic().messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=messages,
        )
        parts = []
        for block in msg.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "".join(parts)

    return _retry(_do, label="anthropic", retry_on=_ANTHROPIC_RETRY)


# ---------- OpenRouter (OpenAI-compatible) ----------

def _is_param_unsupported_400(text: str) -> bool:
    """True if a 400 body indicates the model rejected a sampling param
    (temperature / top_p) rather than a genuine auth/payload bug.

    Different upstreams routed via OpenRouter phrase this differently, e.g.:
      - Bedrock-hosted Claude: "`temperature` is deprecated for this model."
      - DeepSeek reasoning models: "Invalid param: not support for model [...]"
    so we match both the explicitly-named-param case and the generic
    "param not supported/invalid" case.
    """
    t = (text or "").lower()
    if "temperature" in t or "top_p" in t or "top-p" in t:
        return True
    if ("param" in t or "parameter" in t) and any(
        w in t for w in ("not support", "unsupported", "deprecated", "invalid")
    ):
        return True
    return False


def _openrouter_chat(system: str, messages: list[dict], *, model: str,
                     max_tokens: int, temperature: float) -> str:
    payload_messages = [{"role": "system", "content": system}]
    payload_messages.extend(messages)

    # Some models routed via OpenRouter (Bedrock-hosted Claude, DeepSeek
    # reasoning models, ...) reject `temperature`. We send it optimistically and,
    # if the model 400s specifically about an unsupported/deprecated sampling
    # param, drop it and retry once. Models that accept temperature are
    # unaffected. The flag persists across network retries within this call.
    state = {"send_temperature": True}

    def _build_payload() -> dict:
        body = {
            "model": model,
            "messages": payload_messages,
            "max_tokens": max_tokens,
        }
        if state["send_temperature"]:
            body["temperature"] = temperature
        return body

    def _do():
        resp = _get_openrouter().post("/chat/completions", json=_build_payload())

        # Model rejected a sampling param: drop `temperature` and retry once,
        # before any other error handling.
        if (resp.status_code >= 400 and state["send_temperature"]
                and _is_param_unsupported_400(resp.text)):
            state["send_temperature"] = False
            print(f"[llm] openrouter: model '{model}' rejected a sampling param "
                  f"(HTTP {resp.status_code}); retrying once without temperature.")
            resp = _get_openrouter().post("/chat/completions", json=_build_payload())

        # 5xx is worth retrying; 4xx isn't (auth/payload bug)
        if 500 <= resp.status_code < 600:
            raise httpx.RemoteProtocolError(
                f"OpenRouter {resp.status_code}: {resp.text[:200]}"
            )
        if resp.status_code >= 400:
            raise RuntimeError(f"OpenRouter error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        if "error" in data:
            # if the server reports an upstream/provider transient, treat as retryable
            err = str(data["error"])
            if any(w in err.lower() for w in ("timeout", "overloaded", "rate", "upstream")):
                raise httpx.RemoteProtocolError(f"OpenRouter upstream: {err[:200]}")
            raise RuntimeError(f"OpenRouter error: {data['error']}")
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"Unexpected OpenRouter response: {data}") from e

    return _retry(_do, label="openrouter", retry_on=_HTTPX_RETRY)


# ---------- Public dispatch ----------

def _dispatch(system: str, messages: list[dict], *, model: Optional[str],
              max_tokens: int, temperature: float) -> str:
    m = _resolve_model(model)
    max_tokens = _scaled_tokens(max_tokens)
    if LLM_PROVIDER == "openrouter":
        return _openrouter_chat(system, messages, model=m,
                                max_tokens=max_tokens, temperature=temperature)
    return _anthropic_chat(system, messages, model=m,
                           max_tokens=max_tokens, temperature=temperature)


def chat(system: str, user: str, *, model: Optional[str] = None,
         max_tokens: int = 4096, temperature: float = 0.3) -> str:
    """Single-turn chat. Returns assistant text."""
    return _dispatch(system, [{"role": "user", "content": user}],
                     model=model, max_tokens=max_tokens, temperature=temperature)


def _escape_control_chars_in_strings(raw: str) -> str:
    """Walk the JSON text and escape raw newlines/tabs/CR that appear INSIDE
    double-quoted strings — a common LLM output bug when the model writes code
    blocks containing real newlines into a JSON string field.
    Outside of strings (whitespace between tokens) we leave control chars alone."""
    out = []
    in_str = False
    escape_next = False
    for ch in raw:
        if escape_next:
            out.append(ch)
            escape_next = False
            continue
        if ch == "\\":
            out.append(ch)
            escape_next = True
            continue
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            continue
        if in_str:
            if ch == "\n":
                out.append("\\n")
                continue
            if ch == "\r":
                out.append("\\r")
                continue
            if ch == "\t":
                out.append("\\t")
                continue
            # other ASCII controls → drop or escape minimal
            if ord(ch) < 0x20:
                out.append(" ")
                continue
        out.append(ch)
    return "".join(out)


def chat_json(system: str, user: str, *, model: Optional[str] = None,
              max_tokens: int = 4096,
              max_attempts: int = 3) -> dict:
    """Chat that expects JSON output.
    Robust to fences, stray prose, unescaped control chars, AND truncated responses.
    Retries the entire LLM call when JSON parse fails (e.g. response cut off mid-string).
    """
    sys = system + (
        "\n\nIMPORTANT: respond with ONLY one valid JSON object."
        " No prose, no ```fences```, no trailing comments."
        " Inside string values: write \\n for line breaks, never real newlines."
        " Keep output compact — total length under ~2500 chars when possible."
    )
    last_err = None
    last_raw = ""
    for attempt in range(1, max_attempts + 1):
        # raise max_tokens slightly on retry so truncation is less likely
        bonus = (attempt - 1) * 1024
        raw = chat(sys, user, model=model, max_tokens=max_tokens + bonus, temperature=0.2)
        last_raw = raw
        candidate = raw
        m = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
        if m:
            candidate = m.group(1)
        candidate = candidate.strip()
        if not candidate.startswith("{"):
            s = candidate.find("{")
            e = candidate.rfind("}")
            if s != -1 and e != -1:
                candidate = candidate[s:e + 1]
        # try 1: as-is
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e1:
            last_err = e1
        # try 2: with control-char escaping
        try:
            return json.loads(_escape_control_chars_in_strings(candidate))
        except json.JSONDecodeError as e2:
            last_err = e2
        print(f"[chat_json] attempt {attempt}/{max_attempts} parse failed: {last_err}")

    # all attempts exhausted — surface raw preview to caller
    preview = (last_raw or "")[:600].replace("\n", "⏎")
    raise json.JSONDecodeError(
        f"{last_err.msg if last_err else 'parse failed'} after {max_attempts} attempts. "
        f"Last raw preview: {preview!r}",
        (last_raw or ""), last_err.pos if last_err else 0,
    )


def chat_multi(system: str, messages: list[dict], *, model: Optional[str] = None,
               max_tokens: int = 4096,
               temperature: float = 0.4) -> str:
    """Multi-turn chat. messages = [{role: 'user'|'assistant', content: '...'}]."""
    return _dispatch(system, messages, model=model,
                     max_tokens=max_tokens, temperature=temperature)


def provider_info() -> str:
    """Human-readable provider/model info for status output."""
    if LLM_PROVIDER == "openrouter":
        return f"OpenRouter · {OPENROUTER_MODEL}"
    return f"Anthropic · {ANTHROPIC_MODEL}"
