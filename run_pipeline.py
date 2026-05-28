"""
End-to-end driver: for each username, run history -> profile -> post_analysis
on a single shared synthetic post, then print a side-by-side comparison.

Run:  C:\\python\\python.exe run_pipeline.py
"""
import os
import sys
import json
import importlib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

USERS = ["spez", "thisisbillgates", "PoppinKream", "Unidan", "GovSchwarzenegger"]

POST_TITLE = "Intel's stock is expected to soar next year due to the increasing demand for chips."
POST_BODY = ""
POST_SUBREDDIT = "synthetic"


def run_module(module_name: str, argv: list[str]) -> None:
    """Invoke a script's main() by faking sys.argv."""
    saved = sys.argv
    try:
        sys.argv = [f"{module_name}.py"] + argv
        # Reload so each call sees a fresh argparse state.
        if module_name in sys.modules:
            mod = importlib.reload(sys.modules[module_name])
        else:
            mod = importlib.import_module(module_name)
        mod.main()
    finally:
        sys.argv = saved


def step_history(username: str) -> str:
    out = os.path.join(HERE, f"{username}_history.json")
    if os.path.isfile(out):
        print(f"  [history] already exists, skipping fetch ({out})", file=sys.stderr)
        return out
    print(f"  [history] fetching for u/{username} ...", file=sys.stderr)
    # Cap items per kind so the run is reasonably fast across 3 users.
    run_module("history", [username, "--limit", "200"])
    return out


def step_profile(username: str) -> str:
    out = os.path.join(HERE, f"{username}_profile.json")
    if os.path.isfile(out):
        print(f"  [profile] already exists, skipping ({out})", file=sys.stderr)
        return out
    print(f"  [profile] generating ...", file=sys.stderr)
    run_module("profile_report", [username])
    return out


def step_analysis(username: str) -> str:
    out = os.path.join(HERE, f"{username}_post_analysis_intel.json")
    print(f"  [analysis] running synthetic post ...", file=sys.stderr)
    run_module("post_analysis", [
        username,
        "--post-title", POST_TITLE,
        "--post-body", POST_BODY,
        "--post-subreddit", POST_SUBREDDIT,
        "--out", out,
    ])
    return out


def fmt(v) -> str:
    return "n/a" if v is None else str(v)


def comparison_table(results: list[dict]) -> str:
    """Return a small text table of the four scores per user."""
    cols = ["analyzability", "understanding", "political_motivation", "consistency"]
    keys = ["analyzability_score", "understanding_score",
            "political_motivation_score", "consistency_with_profile"]
    width = max(len(u) for u in [r["username"] for r in results] + ["user"])
    header = f"{'user'.ljust(width)} | " + " | ".join(c.rjust(20) for c in cols)
    lines = [header, "-" * len(header)]
    for r in results:
        a = r["analysis"]
        row = f"{r['username'].ljust(width)} | " + " | ".join(
            fmt(a.get(k)).rjust(20) for k in keys
        )
        lines.append(row)
    return "\n".join(lines)


def main() -> None:
    # The Windows console codec can't encode emoji / em-dashes that appear in
    # model narratives, which would crash the final print. Force UTF-8 with
    # replacement so output never aborts the run.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    results = []
    for u in USERS:
        print(f"\n=== {u} ===", file=sys.stderr)
        try:
            step_history(u)
            step_profile(u)
            out_path = step_analysis(u)
            with open(out_path, "r", encoding="utf-8") as f:
                results.append(json.load(f))
        except SystemExit as e:
            print(f"  pipeline aborted for {u}: {e}", file=sys.stderr)
        except Exception as e:
            print(f"  pipeline failed for {u}: {e}", file=sys.stderr)

    print("\n\n========== COMPARISON ==========")
    print(f"Synthetic post: {POST_TITLE}\n")
    if results:
        print(comparison_table(results))
        print("\n--- Verdicts ---")
        for r in results:
            a = r["analysis"]
            print(f"\n[{r['username']}] {a.get('verdict', 'n/a')}")
        print("\n--- Narratives ---")
        for r in results:
            a = r["analysis"]
            print(f"\n[{r['username']}]\n{a.get('narrative', 'n/a')}")
    else:
        print("No successful runs.")


if __name__ == "__main__":
    main()
