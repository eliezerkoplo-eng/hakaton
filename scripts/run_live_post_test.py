"""
REDITRUE - Live Post Integration Test
=======================================

Fetches a real Reddit post's comment tree, flattens it, runs it through
the MainOrchestrator pipeline, and prints the full analysis payload.

Usage:
    python scripts/run_live_post_test.py <reddit_post_url>

Example:
    python scripts/run_live_post_test.py https://www.reddit.com/r/technology/comments/abc123/some_title/
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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
}

REQUEST_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Reddit Fetching
# ---------------------------------------------------------------------------

def fetch_post_json(url: str) -> list:
    """
    Fetch the Reddit post JSON data.

    Tries two methods:
      1. Reddit OAuth API (if REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET are set)
      2. Direct .json endpoint (may be blocked by Reddit without auth)

    Returns the parsed JSON (a list of two listings: post + comments).
    """
    # Normalize URL
    clean_url = url.rstrip("/")

    # Remove query params if any
    if "?" in clean_url:
        clean_url = clean_url.split("?")[0]

    # Extract the path portion for OAuth API
    # e.g., /r/Python/comments/1kqxbhf/title
    from urllib.parse import urlparse
    parsed = urlparse(clean_url)
    path = parsed.path.rstrip("/")

    # Try OAuth first
    client_id = os.environ.get("REDDIT_CLIENT_ID", "")
    client_secret = os.environ.get("REDDIT_CLIENT_SECRET", "")

    if client_id and client_secret:
        print("  Using Reddit OAuth API...")
        token = _get_oauth_token(client_id, client_secret)
        oauth_url = f"https://oauth.reddit.com{path}.json"
        resp = requests.get(
            oauth_url,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": HEADERS["User-Agent"],
            },
            params={"raw_json": 1},
            timeout=REQUEST_TIMEOUT,
        )
    else:
        # Fallback: direct .json (may fail with 403 on Reddit's new policy)
        print("  No OAuth credentials found. Trying direct .json endpoint...")
        print("  (Set REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET env vars for reliable access)")
        json_url = clean_url + ".json"
        print(f"  Fetching: {json_url}")
        resp = requests.get(
            json_url,
            headers=HEADERS,
            params={"raw_json": 1},
            timeout=REQUEST_TIMEOUT,
        )

    if resp.status_code == 429:
        wait = float(resp.headers.get("Retry-After", 5))
        print(f"  Rate limited (429). Waiting {wait}s...")
        time.sleep(wait)
        resp = requests.get(
            json_url if not (client_id and client_secret) else oauth_url,
            headers=HEADERS,
            params={"raw_json": 1},
            timeout=REQUEST_TIMEOUT,
        )

    if resp.status_code == 403:
        raise RuntimeError(
            "403 Forbidden - Reddit blocks unauthenticated .json requests.\n"
            "  Fix: Set environment variables REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET\n"
            "  Or: Save a post's JSON manually and use --file mode (see below)."
        )

    if resp.status_code == 404:
        raise RuntimeError("404 Not Found - post does not exist or was deleted.")

    if resp.status_code != 200:
        raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")

    data = resp.json()

    if not isinstance(data, list) or len(data) < 2:
        raise RuntimeError("Unexpected JSON structure - not a valid Reddit post response.")

    return data


def _get_oauth_token(client_id: str, client_secret: str) -> str:
    """Obtain a Reddit OAuth bearer token using app-only (client_credentials) flow."""
    resp = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(client_id, client_secret),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": HEADERS["User-Agent"]},
        timeout=10,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"OAuth token request failed: {resp.status_code} {resp.text[:100]}")
    return resp.json()["access_token"]


def load_from_file(filepath: str) -> list:
    """Load a previously saved Reddit JSON file for offline testing."""
    print(f"  Loading from file: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or len(data) < 2:
        raise RuntimeError("File does not contain valid Reddit post JSON structure.")
    return data


# ---------------------------------------------------------------------------
# Comment Tree Flattening
# ---------------------------------------------------------------------------

def flatten_comment_tree(node: dict, comments: list) -> None:
    """
    Recursively traverse a Reddit comment tree node and extract all t1 comments.

    Args:
        node: A single Reddit "thing" dict (with "kind" and "data" keys).
        comments: Accumulator list to append Comment objects to.
    """
    if not isinstance(node, dict):
        return

    kind = node.get("kind")
    data = node.get("data", {})

    if kind == "t1":
        # This is a comment
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

        # Recurse into replies
        replies = data.get("replies")
        if isinstance(replies, dict):
            children = replies.get("data", {}).get("children", [])
            for child in children:
                flatten_comment_tree(child, comments)

    elif kind == "Listing":
        # A listing contains multiple children
        children = data.get("children", [])
        for child in children:
            flatten_comment_tree(child, comments)

    elif kind == "more":
        # "Load more comments" stub - skip (would require additional API calls)
        pass


def extract_all_comments(post_json: list) -> list:
    """
    Extract all comments from the Reddit post JSON response.

    Args:
        post_json: The full JSON response (list of two listings).

    Returns:
        List of Comment objects.
    """
    comments = []

    # The second element in the list is the comment tree
    comment_listing = post_json[1]
    flatten_comment_tree(comment_listing, comments)

    return comments


# ---------------------------------------------------------------------------
# Mock Author Profiles
# ---------------------------------------------------------------------------

def generate_mock_profiles(authors: list) -> dict:
    """
    Generate mock author profiles for all unique authors.

    In production, these would come from the Reddit API or a cache.
    For testing, we assign random but plausible values.

    Args:
        authors: List of unique author usernames.

    Returns:
        Dict mapping username -> profile dict.
    """
    profiles = {}
    for author in authors:
        if author in ("[deleted]", "[removed]", "AutoModerator", ""):
            continue

        # Use a hash-based seed for deterministic results per username
        seed = hash(author) % 10000
        rng = random.Random(seed)

        # Assign random account age (30 - 2000 days) and karma
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
# Main
# ---------------------------------------------------------------------------

def run_live_test(url_or_path: str, from_file: bool = False):
    print("=" * 70)
    print("  REDITRUE - Live Post Analysis")
    print("=" * 70)
    print()

    # Step 1: Fetch
    print("[1/4] Fetching post data...")
    try:
        if from_file:
            post_json = load_from_file(url_or_path)
        else:
            post_json = fetch_post_json(url_or_path)
    except RuntimeError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        print(f"  NETWORK ERROR: {e}")
        sys.exit(1)

    # Extract post metadata
    post_data = post_json[0]["data"]["children"][0]["data"]
    post_title = post_data.get("title", "Unknown")
    post_author = post_data.get("author", "Unknown")
    post_created_utc = float(post_data.get("created_utc", 0))
    post_score = post_data.get("score", 0)
    subreddit = post_data.get("subreddit", "Unknown")

    print(f"  Subreddit: r/{subreddit}")
    print(f"  Title: {post_title[:80]}")
    print(f"  Author: u/{post_author}")
    print(f"  Score: {post_score}")
    print()

    # Step 2: Flatten comment tree
    print("[2/4] Flattening comment tree...")
    comments = extract_all_comments(post_json)
    print(f"  Extracted {len(comments)} comments")

    if len(comments) == 0:
        print("  WARNING: No comments found. The post may be new or locked.")
        print("  Running analysis with empty comment list...")

    # Get unique authors
    unique_authors = list(set(c.author for c in comments if c.author != "[deleted]"))
    print(f"  Unique authors: {len(unique_authors)}")
    print()

    # Step 3: Generate mock profiles
    print("[3/4] Generating mock author profiles...")
    author_profiles = generate_mock_profiles(unique_authors)
    print(f"  Generated {len(author_profiles)} profiles")
    print()

    # Step 4: Run orchestrator
    print("[4/4] Running MainOrchestrator pipeline...")
    start_time = time.time()

    comment_list = CommentList(comments)
    orchestrator = MainOrchestrator(
        comment_list=comment_list,
        author_profiles=author_profiles,
        post_created_utc=post_created_utc,
    )

    payload = orchestrator.get_extension_payload()
    elapsed = time.time() - start_time

    print(f"  Analysis complete in {elapsed:.2f}s")
    print()

    # Print results
    print("=" * 70)
    print("  ANALYSIS RESULTS")
    print("=" * 70)
    print()
    print(f"  VERDICT:    {payload['verdict']}")
    print(f"  SCORE:      {payload['confidence_score']}")
    print(f"  COMMENTS:   {payload['metadata']['total_comments']}")
    print(f"  AUTHORS:    {payload['metadata']['unique_authors']}")
    print()

    if payload.get("flags"):
        print("  FLAGS:")
        for flag in payload["flags"]:
            print(f"    - {flag}")
        print()

    print("-" * 70)
    print("  FULL JSON PAYLOAD:")
    print("-" * 70)
    print(json.dumps(payload, indent=4, default=str))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python run_live_post_test.py <reddit_post_url>")
        print("  python run_live_post_test.py --file <path_to_saved_json>")
        print()
        print("Environment variables (for live fetching):")
        print("  REDDIT_CLIENT_ID     - Reddit app client ID")
        print("  REDDIT_CLIENT_SECRET - Reddit app client secret")
        print()
        print("Example:")
        print("  python run_live_post_test.py https://www.reddit.com/r/technology/comments/abc123/title/")
        print("  python run_live_post_test.py --file saved_post.json")
        sys.exit(1)

    if sys.argv[1] == "--file" and len(sys.argv) >= 3:
        # Offline mode: load from saved JSON file
        run_live_test(sys.argv[2], from_file=True)
    else:
        target_url = sys.argv[1]
        run_live_test(target_url)
