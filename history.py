"""
Fetch a Reddit user's recent comments and submissions from the public .json endpoints.

Polite by design: one honest User-Agent, conservative rate limiting, and backoff
that *respects* 429s rather than evading them. No headless browser needed -- the
JSON endpoint already returns clean structured data.

Install:  C:\\python\\python.exe -m pip install requests
Run:      C:\\python\\python.exe reddit_user_history.py <username>
"""
import os
import sys
import json
import time
import random
import argparse

import requests

# One honest User-Agent with a contact. NOT rotated/spoofed -- that's a detection
# signal and a ToS issue. Reddit blocks the default python-requests UA, so set a
# real descriptive string here:
HEADERS = {
    "User-Agent": "user-history-fetch/1.0 (personal project; contact: you@example.com)"
}

BASE = "https://www.reddit.com"

# Default account to fetch when no username is passed on the command line
# (e.g. when using the VS Code "Run" button). Change this to any active user.
DEFAULT_USERNAME = "spez"

# Folder where the output JSON is saved (the "hakaton" folder on the Desktop).
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "hakaton")


def _get(url: str, params: dict, max_retries: int = 5) -> dict:
    """GET with exponential backoff that respects rate limits instead of evading them."""
    for attempt in range(max_retries):
        resp = requests.get(url, headers=HEADERS, params=params, timeout=30)

        if resp.status_code == 200:
            return resp.json()

        if resp.status_code == 429:  # rate limited -- back off, don't hammer
            wait = float(resp.headers.get("Retry-After", 2 ** attempt))
            print(f"  429 rate-limited; sleeping {wait:.1f}s", file=sys.stderr)
            time.sleep(wait)
            continue

        if resp.status_code in (403, 404):
            raise RuntimeError(
                f"{resp.status_code} for {url} (private/suspended user, or typo?)"
            )

        resp.raise_for_status()

    raise RuntimeError(f"Gave up after {max_retries} retries: {url}")


def fetch_listing(username: str, kind: str, limit: int = 100) -> list:
    """
    kind: 'comments' or 'submitted'.
    Reddit caps each page at 100 items; paginate with the 'after' cursor.
    """
    url = f"{BASE}/user/{username}/{kind}.json"
    items, after, fetched = [], None, 0

    while fetched < limit:
        page_size = min(100, limit - fetched)
        params = {"limit": page_size, "raw_json": 1}
        if after:
            params["after"] = after

        data = _get(url, params)
        children = data["data"]["children"]
        if not children:
            break

        for child in children:
            d = child["data"]
            if child["kind"] == "t1":        # comment
                items.append({
                    "type": "comment",
                    "subreddit": d["subreddit"],
                    "created_utc": d["created_utc"],
                    "score": d["score"],
                    "body": d["body"],
                })
            elif child["kind"] == "t3":      # submission
                items.append({
                    "type": "post",
                    "subreddit": d["subreddit"],
                    "created_utc": d["created_utc"],
                    "score": d["score"],
                    "title": d["title"],
                    "body": d.get("selftext", ""),
                })

        fetched += len(children)
        after = data["data"].get("after")
        if not after:
            break

        # Human-paced, polite delay between pages (reduces load; not for evasion):
        time.sleep(random.uniform(1.5, 3.0))

    return items[:limit]


def main():
    parser = argparse.ArgumentParser(description="Fetch a Reddit user's public history.")
    parser.add_argument("username", nargs="?", help="Reddit username (without u/)")
    parser.add_argument("--limit", type=int, default=1000,
                        help="max items per kind (Reddit caps at ~1000)")
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
    comments = fetch_listing(args.username, "comments", limit=args.limit)

    print(f"Fetching up to {args.limit} posts for u/{args.username} ...",
          file=sys.stderr)
    posts = fetch_listing(args.username, "submitted", limit=args.limit)

    print(f"\nGot {len(comments)} comments and {len(posts)} posts "
          f"(showing first 3 of each as a preview; full data in the output file):",
          file=sys.stderr)

    for c in comments[:3]:
        print(f"\n[comment r/{c['subreddit']} | score {c['score']}]")
        print(c["body"][:300])
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
