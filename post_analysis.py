"""
Pick one post from a Reddit user's history (the output of history.py) and ask
Gemini to score two things:

  1. understanding  -- does the user actually grasp the topic of their own
     post, or are they making things up / parroting / posting outside their
     competence?
  2. political_motivation -- does the user have an interest in publishing
     this post even if it isn't strictly true? (i.e. does it serve an agenda
     that already shows up in their profile?)

The analysis leans heavily on <user>_profile.json (produced by
profile_report.py) and uses a sample of the raw history as secondary evidence.

Install:  C:\\python\\python.exe -m pip install google-generativeai
Run:      C:\\python\\python.exe post_analysis.py                 (defaults to spez, picks a post automatically)
          C:\\python\\python.exe post_analysis.py spez --post-index 3
          C:\\python\\python.exe post_analysis.py --pick longest  (default; also: recent | top | random | controversial)
"""
import os
import sys
import json
import random
import argparse

import google.generativeai as genai

from env_loader import load_env, generate_with_retry
load_env()


DEFAULT_USERNAME = "spez"
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "hakaton")
DEFAULT_API_KEY = ""  # set GEMINI_API_KEY in .env instead of hard-coding a key
MODEL_NAME = "gemini-2.5-flash-lite"


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are an OSINT measurement instrument. You receive THREE inputs about a single
Reddit user:

  (A) THE POST: one post (you see it in isolation, with no surrounding thread).
  (B) THE PROFILE: a previously-generated structured profile of who the user is
      (PRIMARY description).
  (C) HISTORY SAMPLE: a sample of their posts and comments (SECONDARY, to qualify
      the profile).

YOUR ONLY JOB IS TO MEASURE. Output objective, descriptive values for each field
below. You are NOT judging whether the post is good, bad, credible, trustworthy,
advocacy, or worth reading. Do NOT weight, combine, gate, or summarize the metrics
into a verdict. Each field is an INDEPENDENT measurement. A separate downstream
system applies weights and decides what the numbers mean.

Banned from every justification: "credible", "trustworthy", "should be trusted",
"should be dismissed", "red flag", "advocacy", "give weight", "negative signal",
"positive signal". Describe only WHAT IS, never what it is worth.

MEASUREMENTS

  1. analyzability (1..10) -- STRUCTURAL ONLY. Does the post ASSERT a proposition
     with a truth value (either true or false about the world)? Independent of
     whether it is supported, true, decent, or sincere.
       10 = asserts one or more truth-evaluable claims (incl. false / unsupported
            / hateful ones).
       5  = a claim-like statement embedded in pure opinion / PR / venting.
       1  = asserts nothing checkable (greeting, personal update, ad, pure
            expression of feeling).

  2. sincerity -- register of the LITERAL proposition: "sincere" | "ironic" |
     "ambiguous". You see the post in isolation, so signal is limited. Use only
     INTERNAL cues (hyperbole, obvious absurdity, scare-quotes). No cue -> output
     "sincere". Weak or conflicting cues -> "ambiguous".

  3. domain_command (1..10 or null) -- MECHANICS of the subject, NOT truth:
     precise terminology, internal nuance, correct framing, awareness of
     counter-arguments. An eloquent, well-structured FALSE argument scores HIGH
     here; a crude, clumsy TRUE one scores LOW. null only if analyzability = 1.

  4. factual_accuracy (1..10 or null) -- Is the asserted claim TRUE, to the best
     of your knowledge? Judge independently of domain_command. null if
     analyzability = 1 or the claim is purely subjective / experiential.

  5. fact_confidence (1..10) -- YOUR OWN confidence in the factual_accuracy
     judgment above. Low for niche, contested, or specialist claims you cannot
     verify with certainty. This prevents penalizing a user for a claim you
     merely suspect is wrong.

  6. interest_engagement (1..10) -- MAGNITUDE ONLY. How central is the post's
     topic / identity to the user's known agenda and interests? 10 = squarely on
     a core topic of theirs; 1 = off-axis. This is NOT about agreement.

  7. stance_alignment -- DIRECTION: "supports" | "opposes" | "orthogonal". Does
     the post's position support, oppose, or run orthogonal to the user's KNOWN
     stance / interest? (High engagement combined with "opposes" is a real,
     meaningful combination -- measure it honestly.)

  8. predictability (1..10) -- How expected is this exact post given the full
     profile (topic + stance + style)? 10 = perfectly predictable, reveals
     nothing new about the user; 1 = highly surprising. Surprising can mean
     genuine change OR anomaly -- you measure only the surprise, not its cause.

RULES:
- Do NOT hallucinate. If evidence is missing, lower the relevant *_confidence,
  not the score.
- Output STRICTLY valid JSON matching the schema below. No markdown fences, no
  commentary outside the JSON.
- Every "*evidence*" field is an array of PLAIN STRINGS only. Each string is ONE
  verbatim quote. No nested objects or arrays. Flatten any structured citation
  into a sentence.
- Escape all double quotes and control characters inside string values.

Schema:
{
  "post_summary": "neutral 1-2 sentence description of what the post asserts.",
  "topic": "short subject label.",
  "content_categories": ["one or more of: political, scientific, religious, historical, economic, factual, technical, opinion, pr_messaging, personal, humor, hate_speech, conspiracy, propaganda, other"],

  "analyzability": 1-10 integer,
  "analyzability_justification": "structural: does it assert a truth-evaluable proposition?",

  "sincerity": "sincere | ironic | ambiguous",
  "sincerity_note": "the cue you used, or 'no contextual cue'.",

  "domain_command": 1-10 integer or null,
  "domain_command_justification": "mechanics only -- terminology, nuance, framing.",

  "factual_accuracy": 1-10 integer or null,
  "fact_confidence": 1-10 integer,
  "factual_justification": "what is true or false, and how sure you are of the ground truth.",

  "interest_engagement": 1-10 integer,
  "stance_alignment": "supports | opposes | orthogonal",
  "alignment_justification": "how the post's topic and position relate to the user's known agenda.",
  "alignment_evidence_from_profile": ["short verbatim quotes from THE PROFILE"],

  "predictability": 1-10 integer,
  "predictability_justification": "how expected this post is given topic, stance, and style.",

  "evidence_from_post": ["short verbatim quotes from THE POST"],
  "evidence_from_history": ["short verbatim quotes from HISTORY SAMPLE"]
}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def setup_gemini() -> None:
    api_key = os.environ.get("GEMINI_API_KEY") or DEFAULT_API_KEY
    if not api_key:
        raise ValueError("GEMINI_API_KEY environment variable is missing and no default key is set.")
    genai.configure(api_key=api_key)


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def pick_post(posts: list, strategy: str, index: int | None) -> tuple[int, dict]:
    """
    Choose which post to analyze.
      - explicit index wins
      - 'longest'      -> richest text (default; gives the model the most to chew on)
      - 'recent'       -> first item (Reddit returns newest first)
      - 'top'          -> highest score
      - 'random'       -> uniform random
      - 'controversial'-> longest body posted to a non-self subreddit
    """
    if not posts:
        raise SystemExit("No posts in history. Nothing to analyze.")

    if index is not None:
        if not (0 <= index < len(posts)):
            raise SystemExit(f"--post-index {index} out of range (0..{len(posts)-1}).")
        return index, posts[index]

    def _len(p: dict) -> int:
        return len((p.get("title") or "")) + len((p.get("body") or ""))

    if strategy == "longest":
        i = max(range(len(posts)), key=lambda k: _len(posts[k]))
    elif strategy == "recent":
        i = 0
    elif strategy == "top":
        i = max(range(len(posts)), key=lambda k: posts[k].get("score", 0) or 0)
    elif strategy == "random":
        i = random.randrange(len(posts))
    elif strategy == "controversial":
        external = [k for k, p in enumerate(posts)
                    if not (p.get("subreddit", "") or "").lower().startswith("u_")]
        pool = external or list(range(len(posts)))
        i = max(pool, key=lambda k: _len(posts[k]))
    else:
        raise SystemExit(f"Unknown --pick strategy: {strategy}")

    return i, posts[i]


def trim_history(data: dict, max_items: int = 60, max_body_chars: int = 600) -> dict:
    """Smaller sample than profile_report.py -- the profile already summarized it."""
    def _trim(item: dict) -> dict:
        out = dict(item)
        for k in ("body", "title"):
            if k in out and isinstance(out[k], str) and len(out[k]) > max_body_chars:
                out[k] = out[k][:max_body_chars] + " ...[truncated]"
        return out

    return {
        "comments": [_trim(c) for c in data.get("comments", [])[:max_items]],
        "posts":    [_trim(p) for p in data.get("posts", [])[:max_items]],
    }


def extract_json(text: str) -> dict:
    s = text.strip()
    if s.startswith("```"):
        s = s.split("\n", 1)[1] if "\n" in s else s
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
    return json.loads(s)


def analyze_post(post: dict, profile: dict, history: dict) -> dict:
    model = genai.GenerativeModel(MODEL_NAME)

    payload = {
        "post": post,
        "profile": profile,
        "history_sample": trim_history(history),
    }

    prompt = (
        SYSTEM_PROMPT
        + "\n\n=== INPUT JSON ===\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )

    response = generate_with_retry(
        model,
        prompt,
        generation_config={
            "temperature": 0.2,
            "response_mime_type": "application/json",
        },
    )

    text = (response.text or "").strip()
    if not text:
        raise RuntimeError("Empty response from Gemini.")
    try:
        return extract_json(text)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Model did not return valid JSON: {e}\n---\n{text}\n---")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    # The Windows console codec can't encode emoji / em-dashes that appear in
    # quoted Reddit text, which would crash the preview print after the result
    # is already saved. Force UTF-8 with replacement so output never aborts.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="Score a single post for understanding and political motivation."
    )
    parser.add_argument("username", nargs="?", help="Reddit username (default: spez).")
    parser.add_argument("--history", help="Path to <user>_history.json (overrides username).")
    parser.add_argument("--profile", help="Path to <user>_profile.json (overrides username).")
    parser.add_argument("--out", help="Where to write the analysis JSON.")
    parser.add_argument("--post-index", type=int, default=None,
                        help="Index of the post to analyze (overrides --pick).")
    parser.add_argument("--pick", default="longest",
                        choices=["longest", "recent", "top", "random", "controversial"],
                        help="How to choose a post when --post-index is not given.")
    parser.add_argument("--post-title", default=None,
                        help="Analyze a synthetic post with this title (overrides history selection).")
    parser.add_argument("--post-body", default=None,
                        help="Body text for the synthetic post. Optional.")
    parser.add_argument("--post-subreddit", default="synthetic",
                        help="Subreddit label to attach to the synthetic post. Default: synthetic.")
    parser.add_argument("--list", action="store_true",
                        help="Just list the available posts and exit.")
    args = parser.parse_args()

    username = args.username or DEFAULT_USERNAME
    history_path = args.history or os.path.join(OUTPUT_DIR, f"{username}_history.json")
    profile_path = args.profile or os.path.join(OUTPUT_DIR, f"{username}_profile.json")
    out_path = args.out or os.path.join(OUTPUT_DIR, f"{username}_post_analysis.json")

    if not os.path.isfile(history_path):
        sys.exit(f"History file not found: {history_path}\nRun history.py first.")
    if not os.path.isfile(profile_path):
        sys.exit(f"Profile file not found: {profile_path}\nRun profile_report.py first.")

    history = load_json(history_path)
    profile = load_json(profile_path)
    posts = history.get("posts", [])

    if args.list:
        print(f"{len(posts)} post(s) for u/{username}:")
        for i, p in enumerate(posts):
            title = (p.get("title") or "").replace("\n", " ")[:90]
            print(f"  [{i}] r/{p.get('subreddit')} | score {p.get('score')} | {title}")
        return

    # Synthetic post mode: caller supplies title (and optionally body) directly.
    # We still load the profile + history for context, but skip selection.
    if args.post_title is not None:
        post = {
            "type": "post",
            "subreddit": args.post_subreddit,
            "created_utc": None,
            "score": None,
            "title": args.post_title,
            "body": args.post_body or "",
        }
        idx = -1  # sentinel: not from the history list
    else:
        idx, post = pick_post(posts, args.pick, args.post_index)
    title_preview = (post.get("title") or "").replace("\n", " ")[:90]
    label = f"[synthetic]" if idx == -1 else f"[{idx}]"
    print(f"Analyzing post {label} r/{post.get('subreddit')} | {title_preview}",
          file=sys.stderr)

    setup_gemini()
    print(f"Calling Gemini ({MODEL_NAME}) ...", file=sys.stderr)
    result = analyze_post(post, profile, history)

    # Stamp which post was analyzed so the output is self-describing.
    result_with_meta = {
        "username": username,
        "post_index": idx,
        "post_subreddit": post.get("subreddit"),
        "post_title": post.get("title"),
        "post_score": post.get("score"),
        "analysis": result,
    }

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result_with_meta, f, ensure_ascii=False, indent=2)

    print(f"\nWrote analysis to {os.path.abspath(out_path)}", file=sys.stderr)
    print("\n--- Preview ---")
    print(json.dumps(result_with_meta, ensure_ascii=False, indent=2)[:2500])


if __name__ == "__main__":
    main()
