"""
Fetch a Reddit user's comments and submissions from the public PullPush archive.

Reddit's own anonymous .json endpoints now return 403, and creating an API app
requires manual approval under the Responsible Builder Policy. PullPush
(https://pullpush.io) is a public Pushshift successor that serves the same data
with no app, no OAuth, and no proxy. We page backwards through it with the
'before' cursor and emit the exact same {"comments": [...], "posts": [...]}
shape the rest of the pipeline expects.

Install:  C:\\python\\python.exe -m pip install requests
Run:      C:\\python\\python.exe history.py <username>
"""
import os
import sys
import json
import time
import random
import argparse

import requests

from env_loader import load_env
load_env()

HEADERS = {
    "User-Agent": "user-history-fetch/1.0 (personal project; contact: you@example.com)"
}

# PullPush search endpoints. 'comment' and 'submission' mirror Reddit's two
# listing kinds; each caps a page at 100 items.
PULLPUSH_BASE = "https://api.pullpush.io/reddit/search"

# Default account to fetch when no username is passed on the command line
# (e.g. when using the VS Code "Run" button). Change this to any active user.
DEFAULT_USERNAME = "spez"

# Folder where the output JSON is saved (the "hakaton" folder on the Desktop).
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "hakaton")


def _to_int(v):
    """PullPush sometimes returns numeric fields as strings; coerce or drop."""
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _get(url: str, params: dict, max_retries: int = 5) -> dict:
    """GET with exponential backoff that respects rate limits instead of evading them."""
    for attempt in range(max_retries):
        resp = requests.get(url, headers=HEADERS, params=params, timeout=40)

        if resp.status_code == 200:
            try:
                return resp.json()
            except ValueError as e:
                snippet = resp.text[:200]
                raise RuntimeError(f"Non-JSON 200 from {url}: {e}\n{snippet}")

        if resp.status_code == 429:  # rate limited -- back off, don't hammer
            wait = float(resp.headers.get("Retry-After", 2 ** attempt))
            print(f"  429 rate-limited; sleeping {wait:.1f}s", file=sys.stderr)
            time.sleep(wait)
            continue

        if resp.status_code in (500, 502, 503, 504):  # transient archive hiccup
            wait = 2 ** attempt
            print(f"  {resp.status_code} from archive; retrying in {wait}s", file=sys.stderr)
            time.sleep(wait)
            continue

        resp.raise_for_status()

    raise RuntimeError(f"Gave up after {max_retries} retries: {url}")


def fetch_listing(username: str, kind: str, limit: int = 100) -> list:
    """
    kind: 'comment' or 'submission'.
    PullPush caps each page at 100 items; page backwards in time with the
    'before' cursor (the oldest created_utc seen so far).
    """
    url = f"{PULLPUSH_BASE}/{kind}/"
    items, before = [], None

    while len(items) < limit:
        page_size = min(100, limit - len(items))
        params = {
            "author": username,
            "size": page_size,
            "sort": "desc",
            "sort_type": "created_utc",
        }
        if before is not None:
            params["before"] = before

        data = _get(url, params)
        children = data.get("data", [])
        if not children:
            break

        for d in children:
            if kind == "comment":
                items.append({
                    "type": "comment",
                    "subreddit": d.get("subreddit"),
                    "created_utc": _to_int(d.get("created_utc")),
                    "score": _to_int(d.get("score")),
                    "body": d.get("body", ""),
                })
            else:  # submission
                items.append({
                    "type": "post",
                    "subreddit": d.get("subreddit"),
                    "created_utc": _to_int(d.get("created_utc")),
                    "score": _to_int(d.get("score")),
                    "title": d.get("title", ""),
                    "body": d.get("selftext", ""),
                })

        # Advance the cursor to the oldest item on this page. If it doesn't move
        # backwards, the archive has nothing older -- stop to avoid looping.
        stamps = [s for s in (_to_int(d.get("created_utc")) for d in children) if s is not None]
        if not stamps:
            break
        oldest = min(stamps)
        if before is not None and oldest >= before:
            break
        before = oldest

        if len(children) < page_size:
            break

        # Human-paced, polite delay between pages (reduces load; not for evasion):
        time.sleep(random.uniform(1.0, 2.0))

    return items[:limit]


def main():
    # The Windows console codec (cp1255 here) can't encode emoji / em-dashes
    # that show up in Reddit text, which would crash the preview prints. Force
    # UTF-8 with replacement so output never aborts the run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Fetch a Reddit user's public history.")
    parser.add_argument("username", nargs="?", help="Reddit username (without u/)")
    parser.add_argument("--limit", type=int, default=1000,
                        help="max items per kind")
    parser.add_argument("--out", help="write combined results to this JSON file")
    args = parser.parse_args()

    # If no username was passed on the command line (e.g. the VS Code "Run"
    # button), fall back to the default set at the top of the file.
    if not args.username:
        args.username = DEFAULT_USERNAME

    # Always save the full results to a file. The terminal only shows a short
    # preview, so without this you'd never see everything that was fetched.
    # Save into OUTPUT_DIR (the Desktop "hakaton" folder) so the location is
    # predictable no matter where the script was launched from.
    if not args.out:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        args.out = os.path.join(OUTPUT_DIR, f"{args.username}_history.json")

    print(f"Fetching up to {args.limit} comments for u/{args.username} ...",
          file=sys.stderr)
    comments = fetch_listing(args.username, "comment", limit=args.limit)

    print(f"Fetching up to {args.limit} posts for u/{args.username} ...",
          file=sys.stderr)
    posts = fetch_listing(args.username, "submission", limit=args.limit)

    print(f"\nGot {len(comments)} comments and {len(posts)} posts "
          f"(showing first 3 of each as a preview; full data in the output file):",
          file=sys.stderr)

    for c in comments[:3]:
        print(f"\n[comment r/{c['subreddit']} | score {c['score']}]")
        print((c["body"] or "")[:300])
    for p in posts[:3]:
        print(f"\n[post r/{p['subreddit']} | score {p['score']}] {p['title']}")
        if p["body"]:
            print(p["body"][:300])

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"comments": comments, "posts": posts}, f,
                      ensure_ascii=False, indent=2)
        print(f"\nWrote results to {os.path.abspath(args.out)}", file=sys.stderr)


if __name__ == "__main__":
    main()
