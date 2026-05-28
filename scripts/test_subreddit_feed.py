"""
REDITRUE - Subreddit Feed Diagnostics Tool
============================================

Scans the top 4 non-stickied posts from a subreddit, analyzes their
comment sections, and produces a consolidated authenticity report.

Usage:
    python scripts/test_subreddit_feed.py [subreddit_name]
    python scripts/test_subreddit_feed.py --file feed.json

Examples:
    python scripts/test_subreddit_feed.py intel
    python scripts/test_subreddit_feed.py technology
    python scripts/test_subreddit_feed.py --file saved_feed.json

Environment variables (for live fetching):
    REDDIT_CLIENT_ID     - Reddit app client ID
    REDDIT_CLIENT_SECRET - Reddit app client secret
"""

import sys
import os
import json
import time
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import requests
from CommentAnalyzer import Comment, CommentList, MainOrchestrator


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HEADERS = {
    "User-Agent": "REDITRUE-SubredditDiag/1.0 (hackathon; contact: team@reditrue.dev)"
}

REQUEST_TIMEOUT = 30
MAX_POSTS = 4
POLITE_DELAY = 1.5


# ---------------------------------------------------------------------------
# OAuth Helper
# ---------------------------------------------------------------------------

def get_oauth_token(client_id: str, client_secret: str) -> str:
    """Obtain a Reddit OAuth bearer token using app-only flow."""
    resp = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": HEADERS["User-Agent"]},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"OAuth failed: {resp.status_code} {resp.text[:100]}")
    return resp.json()["access_token"]


def make_request(url: str, token: str = None) -> dict:
    """Make an authenticated or unauthenticated GET request to Reddit."""
    if token:
        resp = requests.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": HEADERS["User-Agent"],
            },
            params={"raw_json": 1},
            timeout=REQUEST_TIMEOUT,
        )
    else:
        resp = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            params={"raw_json": 1},
            timeout=REQUEST_TIMEOUT,
        )

    if resp.status_code == 429:
        wait = float(resp.headers.get("Retry-After", 5))
        print(f"    Rate limited. Waiting {wait}s...")
        time.sleep(wait)
        return make_request(url, token)

    if resp.status_code == 403:
        raise RuntimeError(
            "403 Forbidden. Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET env vars."
        )

    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:150]}")

    return resp.json()


# ---------------------------------------------------------------------------
# Feed Fetching
# ---------------------------------------------------------------------------

def fetch_subreddit_feed(subreddit: str, token: str = None) -> list:
    """
    Fetch the subreddit's hot feed and return non-stickied post metadata.

    Returns list of dicts: [{title, url, permalink, created_utc, num_comments, author}, ...]
    """
    if token:
        url = f"https://oauth.reddit.com/r/{subreddit}/hot.json?limit=8"
    else:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=8"

    data = make_request(url, token)
    children = data.get("data", {}).get("children", [])

    posts = []
    for child in children:
        if child.get("kind") != "t3":
            continue
        post = child["data"]

        # Skip stickied/pinned posts
        if post.get("stickied", False):
            continue

        posts.append({
            "title": post.get("title", "Untitled"),
            "permalink": post.get("permalink", ""),
            "created_utc": float(post.get("created_utc", 0)),
            "num_comments": post.get("num_comments", 0),
            "author": post.get("author", "Unknown"),
            "score": post.get("score", 0),
        })

        if len(posts) >= MAX_POSTS:
            break

    return posts


def fetch_post_comments(permalink: str, token: str = None) -> list:
    """Fetch and return the raw JSON for a single post's comment tree."""
    if token:
        url = f"https://oauth.reddit.com{permalink}.json"
    else:
        url = f"https://www.reddit.com{permalink}.json"

    data = make_request(url, token)

    if not isinstance(data, list) or len(data) < 2:
        return []

    return data


# ---------------------------------------------------------------------------
# Comment Tree Flattening
# ---------------------------------------------------------------------------

def flatten_comment_tree(node: dict, comments: list) -> None:
    """Recursively traverse a Reddit comment tree and extract all t1 comments."""
    if not isinstance(node, dict):
        return

    kind = node.get("kind")
    data = node.get("data", {})

    if kind == "t1":
        author = data.get("author", "[deleted]")
        body = data.get("body", "")
        comment_id = data.get("id", "")
        parent_id = data.get("parent_id", "")
        created_utc = float(data.get("created_utc", 0))

        comment = Comment(
            id=comment_id,
            parent_id=parent_id,
            text=body,
            author=author,
            created_utc=created_utc,
        )
        comments.append(comment)

        replies = data.get("replies")
        if isinstance(replies, dict):
            children = replies.get("data", {}).get("children", [])
            for child in children:
                flatten_comment_tree(child, comments)

    elif kind == "Listing":
        children = data.get("children", [])
        for child in children:
            flatten_comment_tree(child, comments)

    elif kind == "more":
        pass


def extract_comments_from_json(post_json: list) -> list:
    """Extract all Comment objects from a post's JSON response."""
    comments = []
    if len(post_json) >= 2:
        flatten_comment_tree(post_json[1], comments)
    return comments


# ---------------------------------------------------------------------------
# Mock Author Profiles
# ---------------------------------------------------------------------------

def generate_mock_profiles(authors: list) -> dict:
    """Generate deterministic mock profiles for all unique authors."""
    profiles = {}
    skip = {"[deleted]", "[removed]", "AutoModerator", ""}
    for author in authors:
        if author in skip:
            continue
        seed = hash(author) % 10000
        rng = random.Random(seed)
        account_age_days = rng.randint(30, 2000)
        comment_karma = rng.randint(50, 50000)
        link_karma = rng.randint(10, 15000)
        profiles[author] = {
            "account_created_utc": time.time() - (account_age_days * 86400),
            "comment_karma": comment_karma,
            "link_karma": link_karma,
        }
    return profiles


# ---------------------------------------------------------------------------
# Analysis Pipeline
# ---------------------------------------------------------------------------

def analyze_post(comments: list, post_created_utc: float) -> dict:
    """Run the full orchestrator pipeline on a list of Comment objects."""
    comment_list = CommentList(comments)
    unique_authors = list(set(c.author for c in comments if c.author != "[deleted]"))
    author_profiles = generate_mock_profiles(unique_authors)

    orchestrator = MainOrchestrator(
        comment_list=comment_list,
        author_profiles=author_profiles,
        post_created_utc=post_created_utc,
    )

    return orchestrator.get_extension_payload()


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(subreddit: str, results: list):
    """Print a consolidated ASCII report of all analyzed posts."""
    print()
    print("=" * 90)
    print(f"  REDITRUE - SUBREDDIT FEED DIAGNOSTICS: r/{subreddit}")
    print("=" * 90)
    print()

    # Table header
    print(f"  {'#':<3} {'Title':<40} {'Comments':<10} {'Score':<8} {'Verdict':<20} {'Flags'}")
    print(f"  {'-'*2}  {'-'*38}  {'-'*8}  {'-'*6}  {'-'*18}  {'-'*20}")

    scores = []
    for i, r in enumerate(results, 1):
        title = r["title"][:38]
        num_comments = r["num_comments"]
        score = r["payload"]["confidence_score"]
        verdict = r["payload"]["verdict"]
        flags = r["payload"].get("flags", [])
        flag_summary = flags[0][:30] + "..." if flags else "None"

        scores.append(score)
        print(f"  {i:<3} {title:<40} {num_comments:<10} {score:<8.4f} {verdict:<20} {flag_summary}")

    # Overall index
    avg_score = sum(scores) / len(scores) if scores else 0.0
    print()
    print(f"  {'-'*88}")
    print(f"  {'SUBREDDIT AUTHENTICITY INDEX:':<55} {avg_score:.4f}")
    print(f"  {'-'*88}")
    print()

    # Editorial verdict
    if avg_score <= 0.15:
        editorial = f"r/{subreddit} is currently experiencing healthy, organic discussions."
        emoji = "[SAFE]"
    elif avg_score <= 0.35:
        editorial = f"r/{subreddit} shows minor anomalies but appears mostly authentic."
        emoji = "[LOW RISK]"
    elif avg_score <= 0.55:
        editorial = f"r/{subreddit} has moderate suspicious activity. Manual review recommended."
        emoji = "[MODERATE]"
    elif avg_score <= 0.75:
        editorial = f"WARNING: r/{subreddit} is showing significant signs of coordinated manipulation."
        emoji = "[HIGH RISK]"
    else:
        editorial = f"ALERT: r/{subreddit} is currently under heavy bot-farm or astroturfing activity."
        emoji = "[CRITICAL]"

    print(f"  {emoji} {editorial}")
    print()
    print("=" * 90)


# ---------------------------------------------------------------------------
# File Mode (Offline Testing)
# ---------------------------------------------------------------------------

def run_from_file(filepath: str):
    """
    Run analysis from a saved subreddit feed JSON file.

    Expected format: list of post objects, each with a "comments_json" key
    containing the full Reddit comment tree JSON.
    """
    print(f"  Loading feed from file: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        feed_data = json.load(f)

    if not isinstance(feed_data, list):
        print("  ERROR: File must contain a JSON array of post objects.")
        sys.exit(1)

    results = []
    for post_entry in feed_data[:MAX_POSTS]:
        title = post_entry.get("title", "Unknown")
        created_utc = float(post_entry.get("created_utc", 0))
        comments_json = post_entry.get("comments_json", [])

        comments = extract_comments_from_json(comments_json)
        payload = analyze_post(comments, created_utc)

        results.append({
            "title": title,
            "num_comments": len(comments),
            "payload": payload,
        })

    print_report("offline", results)


# ---------------------------------------------------------------------------
# Live Mode
# ---------------------------------------------------------------------------

def run_live(subreddit: str):
    """Fetch and analyze the top posts from a live subreddit."""
    print("=" * 90)
    print(f"  REDITRUE - Scanning r/{subreddit} feed...")
    print("=" * 90)
    print()

    # Authenticate
    client_id = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    token = None

    if client_id and client_secret:
        print("  [AUTH] Using Reddit OAuth...")
        try:
            token = get_oauth_token(client_id, client_secret)
            print("  [AUTH] Token acquired.")
        except RuntimeError as e:
            print(f"  [AUTH] OAuth failed: {e}")
            print("  [AUTH] Falling back to unauthenticated mode...")
    else:
        print("  [AUTH] No credentials. Using unauthenticated mode.")
        print("  [AUTH] Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET for reliable access.")

    print()

    # Step 1: Fetch feed
    print(f"  [1/3] Fetching r/{subreddit} hot feed...")
    try:
        posts = fetch_subreddit_feed(subreddit, token)
    except RuntimeError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)

    if not posts:
        print("  ERROR: No non-stickied posts found.")
        sys.exit(1)

    print(f"  Found {len(posts)} organic posts to analyze:")
    for i, p in enumerate(posts, 1):
        print(f"    {i}. [{p['score']} pts] {p['title'][:60]}")
    print()

    # Step 2: Fetch comments for each post
    print(f"  [2/3] Fetching comment trees (with {POLITE_DELAY}s delay between requests)...")
    results = []

    for i, post in enumerate(posts):
        print(f"    Fetching comments for post {i+1}/{len(posts)}: {post['title'][:50]}...")

        try:
            post_json = fetch_post_comments(post["permalink"], token)
            comments = extract_comments_from_json(post_json)
        except RuntimeError as e:
            print(f"    WARNING: Failed to fetch - {e}")
            comments = []

        print(f"    -> {len(comments)} comments extracted")

        # Analyze
        payload = analyze_post(comments, post["created_utc"])

        results.append({
            "title": post["title"],
            "num_comments": len(comments),
            "payload": payload,
        })

        # Polite delay between requests
        if i < len(posts) - 1:
            time.sleep(POLITE_DELAY)

    print()
    print(f"  [3/3] Analysis complete.")

    # Step 3: Report
    print_report(subreddit, results)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python test_subreddit_feed.py <subreddit_name>")
        print("  python test_subreddit_feed.py --file <saved_feed.json>")
        print()
        print("Examples:")
        print("  python test_subreddit_feed.py intel")
        print("  python test_subreddit_feed.py technology")
        print("  python test_subreddit_feed.py --file saved_feed.json")
        print()
        print("Environment variables:")
        print("  REDDIT_CLIENT_ID     - Reddit app client ID")
        print("  REDDIT_CLIENT_SECRET - Reddit app client secret")
        sys.exit(1)

    if sys.argv[1] == "--file" and len(sys.argv) >= 3:
        run_from_file(sys.argv[2])
    else:
        subreddit_name = sys.argv[1].strip("/").replace("r/", "")
        run_live(subreddit_name)
