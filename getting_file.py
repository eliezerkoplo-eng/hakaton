import os
import sys
import json
import time
import random
import argparse
import requests
import numpy as np

from CommentAnalyzer import Comment, CommentList, MainOrchestrator
from CommentAnalyzer.analyzers.account_profiler import AuthorProfile

HEADERS = {
    "User-Agent": "reditrue-subreddit-tester/1.0 (contact: huji-project@gmail.com)"
}

BASE_URL = "https://www.reddit.com"


def _get_json(url: str) -> dict:
    resp = requests.get(url, headers=HEADERS, timeout=15)
    if resp.status_code == 200:
        return resp.json()
    raise RuntimeError(f"Reddit returned status {resp.status_code} for {url}")


def _get_top_post_url(subreddit_url: str) -> str:
    clean_url = subreddit_url.rstrip("/")
    json_url = f"{clean_url}.json?limit=5"
    data = _get_json(json_url)

    posts = data.get("data", {}).get("children", [])
    if not posts:
        raise RuntimeError("No posts found in this Subreddit.")

    for post in posts:
        post_data = post.get("data", {})
        if not post_data.get("stickied", False):
            permalink = post_data.get("permalink")
            return f"{BASE_URL}{permalink}"

    permalink = posts[0].get("data", {}).get("permalink")
    return f"{BASE_URL}{permalink}"


def _flatten_comments(children_data: list, comments_list: list) -> None:
    for child in children_data:
        kind = child.get("kind")
        data = child.get("data", {})

        if kind == "t1":
            comments_list.append(
                Comment(
                    id=data.get("id", ""),
                    parent_id=data.get("parent_id", ""),
                    text=data.get("body", ""),
                    author=data.get("author", ""),
                    created_utc=float(data.get("created_utc", 0))
                )
            )
            replies = data.get("replies")
            if isinstance(replies, dict):
                replies_children = replies.get("data", {}).get("children", [])
                _flatten_comments(replies_children, comments_list)


def fetch_post_comments(post_url: str) -> tuple[list[Comment], float]:
    clean_url = post_url.rstrip("/")
    json_url = f"{clean_url}.json"

    data = _get_json(json_url)

    post_data = data[0].get("data", {}).get("children", [{}])[0].get("data", {})
    post_created_utc = float(post_data.get("created_utc", time.time()))

    comment_tree = data[1].get("data", {}).get("children", [])
    flat_comments = []
    _flatten_comments(comment_tree, flat_comments)

    return flat_comments, post_created_utc


def _generate_mock_profiles(comments: list[Comment]) -> dict[str, AuthorProfile]:
    profiles = {}
    for c in comments:
        if c.author and c.author not in profiles:
            profiles[c.author] = {
                "account_created_utc": 1600000000.0,
                "comment_karma": 4500,
                "link_karma": 800,
                "cached_at": time.time()
            }
    return profiles


def main():
    parser = argparse.ArgumentParser(description="Run REDITRUE analysis on the top post of a Subreddit.")
    parser.add_argument("subreddit_url", nargs="?", default="https://www.reddit.com/r/intel/")
    args = parser.parse_args()

    print(f"Sourcing top post from Subreddit: {args.subreddit_url} ...")

    try:
        post_url = _get_top_post_url(args.subreddit_url)
        print(f"Top Post Identified: {post_url}\n")

        print("Fetching and flattening comment thread...")
        comments, post_created_utc = fetch_post_comments(post_url)
        print(f"Extracted {len(comments)} total comments from thread.\n")

        if not comments:
            print("No comments found to analyze.")
            return

        comment_list = CommentList(comments)
        author_profiles = _generate_mock_profiles(comments)

        print("Executing 3-Pillar Multi-Modal Orchestration...")
        orchestrator = MainOrchestrator(
            comment_list=comment_list,
            author_profiles=author_profiles,
            post_created_utc=post_created_utc
        )

        payload = orchestrator.get_extension_payload()
        print("\n" + "=" * 50)
        print("REDITRUE VERIFICATION RESULT")
        print("=" * 50)
        print(json.dumps(payload, indent=4, ensure_ascii=False))

    except Exception as e:
        print(f"\nExecution Failed: {str(e)}")


if __name__ == "__main__":
    main()