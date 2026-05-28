"""Tiny .env loader so we don't add a python-dotenv dependency.

Loads KEY=VALUE lines from a .env file in the same folder into os.environ,
without overwriting variables that are already set.
"""
import os
import re
import sys
import time


def load_env(path: str | None = None) -> None:
    if path is None:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)


def generate_with_retry(model, prompt, generation_config, max_retries: int = 6):
    """Call Gemini's generate_content, backing off on 429 / quota errors.

    The free tier enforces a short rolling request window; without this the
    pipeline silently drops a user the moment it hits the limit. We honor the
    'retry in Ns' hint the API returns when present, else back off gently.
    """
    for attempt in range(max_retries):
        try:
            return model.generate_content(prompt, generation_config=generation_config)
        except Exception as e:
            msg = str(e)
            rate_limited = "429" in msg or "quota" in msg.lower() or "exhaust" in msg.lower()
            if not rate_limited or attempt == max_retries - 1:
                raise
            m = re.search(r"retry in ([0-9.]+)s", msg)
            wait = (float(m.group(1)) + 2) if m else min(60, 2 ** attempt + 5)
            print(f"  Gemini rate-limited; sleeping {wait:.0f}s "
                  f"(attempt {attempt + 1}/{max_retries})", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError("Gemini still rate-limited after retries")
