"""
llm_client.py
-------------
Async-compatible OpenRouter API wrapper using urllib (standard library) +
asyncio thread pool executor — no aiohttp dependency required.

Uses asyncio.to_thread to run blocking urllib calls concurrently, keeping
the same async interface expected by generator.py.
"""

import asyncio
import json
import logging
import re
import urllib.error
import urllib.request
from typing import List, Optional

import config

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """Raised when the LLM call fails after all retries."""



def extract_json(text: str) -> Optional[str]:
    """
    Extract a JSON object from LLM output.
    Handles three common patterns:
      1. Pure JSON
      2. ```json ... ``` markdown fence
      3. First { ... } block found by brace matching
    """
    text = text.strip()

    if text.startswith("{") and text.endswith("}"):
        return text

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()

    start = text.find("{")
    if start != -1:
        depth = 0
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start: i + 1]

    return None



def _sync_call(payload: dict) -> str:
    """
    Blocking urllib POST to OpenRouter.
    Returns the assistant message content string.
    Raises LLMError on non-retryable errors, or specific HTTP codes for
    the async wrapper to decide whether to retry.
    """
    url  = f"{config.OPENROUTER_BASE_URL}/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    req  = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
            "Content-Type":  "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read())
            return body["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
            msg  = body.get("error", {}).get("message", str(body))
        except Exception:
            msg = str(e)
        raise LLMError(f"HTTP {e.code}: {msg}") from e
    except urllib.error.URLError as e:
        raise LLMError(f"URLError: {e.reason}") from e



async def call_llm(
    messages: List[dict],
    semaphore: asyncio.Semaphore,
    max_retries: int = config.MAX_RETRIES,
) -> str:
    """
    Send a chat completion request and return the assistant message text.
    Runs urllib in a thread-pool executor so it is non-blocking.
    Retries on transient errors with exponential back-off.
    """
    payload = {
        "model":       config.MODEL,
        "messages":    messages,
        "max_tokens":  config.MAX_TOKENS,
        "temperature": config.TEMPERATURE,
    }

    async with semaphore:
        for attempt in range(1, max_retries + 1):
            try:
                content = await asyncio.to_thread(_sync_call, payload)
                return content

            except LLMError as exc:
                msg = str(exc)
                # Retryable: rate limit or server error
                retryable = any(
                    code in msg for code in ("429", "500", "502", "503", "504")
                )
                if retryable and attempt < max_retries:
                    wait = config.RETRY_DELAY * (2 ** (attempt - 1))
                    logger.warning(
                        "Attempt %d/%d failed (%s) – retrying in %.1fs",
                        attempt, max_retries, msg[:80], wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                # Non-retryable or last attempt
                if attempt == max_retries:
                    raise LLMError(f"All {max_retries} attempts failed. Last error: {msg}") from exc
                raise

        raise LLMError(f"All {max_retries} attempts failed.")
