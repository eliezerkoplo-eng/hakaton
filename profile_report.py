"""
Generate an OSINT-style profiling report from a Reddit user history JSON file
(the output of history.py) using Google's Gemini API.

Install:  C:\\python\\python.exe -m pip install google-generativeai
Run:      C:\\python\\python.exe profile_report.py <username>
          C:\\python\\python.exe profile_report.py --in spez_history.json

The input is the JSON file produced by history.py (e.g. spez_history.json),
which contains {"comments": [...], "posts": [...]}.

The output is a JSON file (e.g. spez_profile.json) holding a structured
profiling report produced by the model.

Note on the API key
-------------------
For convenience the key can be hard-coded below, but the safer pattern is to
set the environment variable GEMINI_API_KEY and leave DEFAULT_API_KEY empty.
The script prefers the env var when both are present.
"""
import os
import sys
import json
import argparse

import google.generativeai as genai


# Default account to analyze when no username is passed on the command line.
DEFAULT_USERNAME = "spez"

# Folder where history.py wrote its output, and where this script will write
# the profiling report.
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "hakaton")

# Hard-coded fallback key (you said it was OK to embed it). Prefer env var.
DEFAULT_API_KEY = "AIzaSyBvXR-W9nLHAcgkI76rsl39FiMxVCGqmyI"

# Gemini model to use. 2.5-flash is fast and reliable on the free tier; switch
# to "gemini-2.5-pro" for stronger reasoning (subject to higher quota limits).
MODEL_NAME = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are an expert OSINT analyst and psychological profiler. Analyze the
following Reddit user data (provided in JSON format) and generate a
comprehensive profiling report IN ENGLISH.

CRITICAL RULE: Do not hallucinate data to fill the structure. If there is
insufficient evidence in the provided data for any specific field, you MUST
explicitly state that the data is missing by outputting "N/A" for string
values, null for numerical values, and [] for arrays.

You must output the report STRICTLY as a valid JSON object matching the exact
structure below. Do not include markdown formatting like ```json or any
conversational text outside the JSON structure.

Structure:
{
  "demographics": "Summary of age, gender, and family status, or 'N/A' if unknown.",
  "geography": "Inferred locations, current and past, or 'N/A' if unknown.",
  "education_profession": "Academic background, industry, estimated socioeconomic status, or 'N/A' if unknown.",
  "ideology_politics": {
    "economic_axis": "Score from -10 (Marxist Left) to +10 (Anarcho-Capitalist Right), or null if no data.",
    "social_axis": "Score from -10 (Libertarian) to +10 (Authoritarian), or null if no data.",
    "hot_button_issues": ["List", "of", "triggering", "topics"],
    "confidence_score": "Score from 1 to 10, or null if no data.",
    "justification": "Provide concrete textual evidence to back up the scores, or 'N/A'."
  },
  "psychology_ocean": {
    "openness": "Score from 1 to 10, or null if no data.",
    "conscientiousness": "Score from 1 to 10, or null if no data.",
    "extraversion": "Score from 1 to 10, or null if no data.",
    "agreeableness": "Score from 1 to 10, or null if no data.",
    "neuroticism": "Score from 1 to 10, or null if no data.",
    "justification": "Concrete textual evidence supporting the scores, or 'N/A'."
  },
  "interests_hobbies": ["List of recurring interests, communities, or hobbies, or [] if no data."],
  "communication_style": "Describe tone, formality, vocabulary, sarcasm, emotional register, or 'N/A'.",
  "behavioral_patterns": {
    "active_hours_utc": "Typical posting hours in UTC (e.g. '14:00-22:00'), or 'N/A'.",
    "active_subreddits": ["Top subreddits the user engages in, or []"],
    "engagement_style": "How they engage (long-form essays, short replies, debate, support, etc.), or 'N/A'."
  },
  "risk_indicators": ["Any flags such as harassment, self-disclosure of sensitive info, extreme views, or [] if none."],
  "summary": "A 3-5 sentence overall portrait of the user, or 'N/A' if no data."
}

Reddit data follows.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def setup_gemini() -> None:
    """Configure the Gemini SDK with the API key (env var preferred)."""
    api_key = os.environ.get("GEMINI_API_KEY") or DEFAULT_API_KEY
    if not api_key:
        raise ValueError(
            "GEMINI_API_KEY environment variable is missing and no default key is set."
        )
    genai.configure(api_key=api_key)


def load_reddit_data(path: str) -> dict:
    """Load the JSON output produced by history.py."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def trim_for_prompt(data: dict, max_items: int = 200, max_body_chars: int = 1500) -> dict:
    """
    Keep the prompt within reasonable token bounds: cap the number of items per
    kind and the length of any single body / title. Items are kept in original
    order (the API returns newest first), so we keep the most recent activity.
    """
    def _trim_item(item: dict) -> dict:
        out = dict(item)
        for k in ("body", "title"):
            if k in out and isinstance(out[k], str) and len(out[k]) > max_body_chars:
                out[k] = out[k][:max_body_chars] + " ...[truncated]"
        return out

    return {
        "comments": [_trim_item(c) for c in data.get("comments", [])[:max_items]],
        "posts":    [_trim_item(p) for p in data.get("posts", [])[:max_items]],
    }


def extract_json(text: str) -> dict:
    """
    The model is instructed to return raw JSON, but sometimes it wraps the
    answer in ```json ... ``` fences. Strip them and parse.
    """
    s = text.strip()
    if s.startswith("```"):
        # remove leading fence (``` or ```json) and trailing fence
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[: -3]
        s = s.strip()
    return json.loads(s)


def generate_osint_profile(reddit_data: dict) -> dict:
    """Send the Reddit data to Gemini and return the parsed profiling report."""
    model = genai.GenerativeModel(MODEL_NAME)

    payload = json.dumps(trim_for_prompt(reddit_data), ensure_ascii=False, indent=2)
    prompt = SYSTEM_PROMPT + "\n\n" + payload

    response = model.generate_content(
        prompt,
        generation_config={
            "temperature": 0.2,             # keep it analytical, not creative
            "response_mime_type": "application/json",
        },
    )

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Empty response from Gemini.")

    try:
        return extract_json(text)
    except json.JSONDecodeError as e:
        # Surface the raw text so the user can see what came back.
        raise RuntimeError(f"Model did not return valid JSON: {e}\n---\n{text}\n---")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate an OSINT-style profile from a Reddit history JSON."
    )
    parser.add_argument("username", nargs="?",
                        help="Reddit username (used to locate <user>_history.json in the hakaton folder).")
    parser.add_argument("--in", dest="in_path",
                        help="Path to the input JSON (overrides --username).")
    parser.add_argument("--out", dest="out_path",
                        help="Where to write the profile JSON.")
    args = parser.parse_args()

    username = args.username or DEFAULT_USERNAME

    in_path = args.in_path or os.path.join(OUTPUT_DIR, f"{username}_history.json")
    out_path = args.out_path or os.path.join(OUTPUT_DIR, f"{username}_profile.json")

    if not os.path.isfile(in_path):
        sys.exit(f"Input file not found: {in_path}\n"
                 f"Run history.py first to generate it.")

    print(f"Loading Reddit data from {in_path} ...", file=sys.stderr)
    reddit_data = load_reddit_data(in_path)
    n_comments = len(reddit_data.get("comments", []))
    n_posts = len(reddit_data.get("posts", []))
    print(f"  {n_comments} comments, {n_posts} posts", file=sys.stderr)

    print(f"Calling Gemini ({MODEL_NAME}) ...", file=sys.stderr)
    setup_gemini()
    profile = generate_osint_profile(reddit_data)

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    # Short preview to the terminal so the user can sanity-check the result.
    print(f"\nWrote profile to {os.path.abspath(out_path)}", file=sys.stderr)
    print("\n--- Preview ---")
    print(json.dumps(profile, ensure_ascii=False, indent=2)[:2000])


if __name__ == "__main__":
    main()
