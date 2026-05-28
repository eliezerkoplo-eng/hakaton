"""
Orchestrator Simulation Script - 8 Scenario Suite
===================================================

Runs the MainOrchestrator against 8 distinct scenarios to validate scoring
accuracy across organic, malicious, hybrid, and edge-case conditions.

Usage:
    set PYTHONIOENCODING=utf-8
    python simulate_orchestrator.py
"""

import sys
import json
import time

sys.path.insert(0, r"c:\hackaton\hakaton")

from CommentAnalyzer import Comment, CommentList, MainOrchestrator


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

POST_TIMESTAMP = 1716900000.0  # Reference: ~May 28, 2024

def days_ago(days: int) -> float:
    """Return a Unix timestamp N days before POST_TIMESTAMP."""
    return POST_TIMESTAMP - (days * 86400)


# ===========================================================================
# SCENARIO BUILDERS
# ===========================================================================

def build_scenario_a():
    """Organic Thread: Veterans, high karma, varied sentiment, clean text."""
    comments = [
        Comment("c1", "post1", "This is a really interesting perspective, thanks for sharing.", "vet_1", POST_TIMESTAMP + 120),
        Comment("c2", "post1", "I disagree with the premise but the data is solid.", "vet_2", POST_TIMESTAMP + 300),
        Comment("c3", "c1", "Agreed, I have seen similar results in my own research.", "vet_3", POST_TIMESTAMP + 600),
        Comment("c4", "post1", "Can someone explain the methodology here?", "vet_4", POST_TIMESTAMP + 900),
        Comment("c5", "c4", "Sure, they used a longitudinal study over 5 years.", "vet_5", POST_TIMESTAMP + 1200),
        Comment("c6", "post1", "Not sure I buy this. The sample size seems small.", "vet_6", POST_TIMESTAMP + 1800),
        Comment("c7", "c6", "Sample size is 2000, thats actually quite large.", "vet_7", POST_TIMESTAMP + 2400),
        Comment("c8", "post1", "Great post. Bookmarked for later reading.", "vet_8", POST_TIMESTAMP + 3600),
        Comment("c9", "post1", "This aligns with what I learned in grad school.", "vet_9", POST_TIMESTAMP + 5400),
        Comment("c10", "c2", "Your disagreement is valid but consider the control group.", "vet_10", POST_TIMESTAMP + 7200),
        Comment("c11", "post1", "Interesting thread, lots of good discussion here.", "vet_1", POST_TIMESTAMP + 9000),
        Comment("c12", "c7", "Fair point about the sample size. I stand corrected.", "vet_6", POST_TIMESTAMP + 10800),
    ]
    profiles = {
        "vet_1":  {"account_created_utc": days_ago(730),  "comment_karma": 15000, "link_karma": 3000},
        "vet_2":  {"account_created_utc": days_ago(1200), "comment_karma": 42000, "link_karma": 8000},
        "vet_3":  {"account_created_utc": days_ago(900),  "comment_karma": 8500,  "link_karma": 1200},
        "vet_4":  {"account_created_utc": days_ago(500),  "comment_karma": 3200,  "link_karma": 600},
        "vet_5":  {"account_created_utc": days_ago(1500), "comment_karma": 51000, "link_karma": 12000},
        "vet_6":  {"account_created_utc": days_ago(800),  "comment_karma": 6700,  "link_karma": 900},
        "vet_7":  {"account_created_utc": days_ago(1100), "comment_karma": 22000, "link_karma": 4500},
        "vet_8":  {"account_created_utc": days_ago(600),  "comment_karma": 4100,  "link_karma": 700},
        "vet_9":  {"account_created_utc": days_ago(1800), "comment_karma": 38000, "link_karma": 9000},
        "vet_10": {"account_created_utc": days_ago(400),  "comment_karma": 2800,  "link_karma": 500},
    }
    return CommentList(comments), profiles


def build_scenario_b():
    """Bot-Farm Thread: Young accounts, low karma, astroturf gap, debunking keywords."""
    comments = [
        Comment("b1", "post2", "This is amazing, everyone needs to see this!", "bot_1", POST_TIMESTAMP + 10),
        Comment("b2", "post2", "Wow great content, so true and important!", "bot_2", POST_TIMESTAMP + 15),
        Comment("b3", "post2", "I agree completely, this is the best post today.", "bot_3", POST_TIMESTAMP + 22),
        Comment("b4", "post2", "Love this! Shared with all my friends.", "bot_4", POST_TIMESTAMP + 30),
        Comment("b5", "post2", "Amazing work, keep it up! So good.", "bot_5", POST_TIMESTAMP + 35),
        Comment("b6", "post2", "This is great news, very true and good.", "bot_6", POST_TIMESTAMP + 42),
        Comment("b7", "post2", "Yes! I support this message completely. Great!", "bot_7", POST_TIMESTAMP + 50),
        Comment("b8", "post2", "Perfect post, agree with everything said here.", "bot_8", POST_TIMESTAMP + 55),
        Comment("v1", "post2", "This is clearly fake. Reverse image search shows its from 2019.", "real_1", POST_TIMESTAMP + 300),
        Comment("v2", "post2", "Debunked. The source has been retracted. This is a hoax.", "real_2", POST_TIMESTAMP + 450),
        Comment("v3", "b1", "Look at these bot accounts, all created this week. AI generated spam.", "real_3", POST_TIMESTAMP + 600),
        Comment("v4", "post2", "Misleading propaganda. The original study says the opposite.", "real_4", POST_TIMESTAMP + 900),
        Comment("v5", "v1", "Confirmed fake. I fact-checked this with Reuters.", "real_2", POST_TIMESTAMP + 1200),
    ]
    profiles = {
        "bot_1": {"account_created_utc": days_ago(5),   "comment_karma": 12,  "link_karma": 3},
        "bot_2": {"account_created_utc": days_ago(8),   "comment_karma": 7,   "link_karma": 0},
        "bot_3": {"account_created_utc": days_ago(3),   "comment_karma": 22,  "link_karma": 1},
        "bot_4": {"account_created_utc": days_ago(12),  "comment_karma": 45,  "link_karma": 5},
        "bot_5": {"account_created_utc": days_ago(6),   "comment_karma": 9,   "link_karma": 0},
        "bot_6": {"account_created_utc": days_ago(18),  "comment_karma": 31,  "link_karma": 2},
        "bot_7": {"account_created_utc": days_ago(4),   "comment_karma": 5,   "link_karma": 0},
        "bot_8": {"account_created_utc": days_ago(10),  "comment_karma": 18,  "link_karma": 1},
        "real_1": {"account_created_utc": days_ago(1100), "comment_karma": 18000, "link_karma": 4200},
        "real_2": {"account_created_utc": days_ago(800),  "comment_karma": 9500,  "link_karma": 2100},
        "real_3": {"account_created_utc": days_ago(1400), "comment_karma": 32000, "link_karma": 7800},
        "real_4": {"account_created_utc": days_ago(600),  "comment_karma": 5200,  "link_karma": 900},
    }
    return CommentList(comments), profiles


def build_scenario_c():
    """Mixed/Hybrid Thread: 50/50 split of veterans and suspicious new accounts."""
    comments = [
        # Veterans - normal discussion
        Comment("h1", "post3", "Interesting article, but I think the conclusion is overstated.", "mix_vet_1", POST_TIMESTAMP + 200),
        Comment("h2", "post3", "The methodology section is well written at least.", "mix_vet_2", POST_TIMESTAMP + 500),
        Comment("h3", "h1", "I partially agree. The data supports a weaker claim.", "mix_vet_3", POST_TIMESTAMP + 800),
        Comment("h4", "post3", "Has anyone read the follow-up paper? It contradicts this.", "mix_vet_4", POST_TIMESTAMP + 1500),
        Comment("h5", "h4", "Yes, the follow-up had a larger sample and different results.", "mix_vet_5", POST_TIMESTAMP + 2200),
        Comment("h6", "post3", "Good discussion everyone. Nuanced takes are rare on Reddit.", "mix_vet_6", POST_TIMESTAMP + 4000),
        # Suspicious new accounts - promotional/repetitive
        Comment("h7", "post3", "This is so true! Everyone should read this amazing post!", "mix_new_1", POST_TIMESTAMP + 60),
        Comment("h8", "post3", "Wow amazing content! So true and important for everyone!", "mix_new_2", POST_TIMESTAMP + 75),
        Comment("h9", "post3", "I love this! Best thing I have read today, so great!", "mix_new_3", POST_TIMESTAMP + 90),
        Comment("h10", "post3", "Amazing! This is great content, very true!", "mix_new_4", POST_TIMESTAMP + 105),
        Comment("h11", "post3", "So good! Everyone needs to see this amazing post!", "mix_new_5", POST_TIMESTAMP + 120),
        Comment("h12", "post3", "Great work! This is the best post, so true!", "mix_new_6", POST_TIMESTAMP + 135),
    ]
    profiles = {
        "mix_vet_1": {"account_created_utc": days_ago(900),  "comment_karma": 12000, "link_karma": 2500},
        "mix_vet_2": {"account_created_utc": days_ago(1300), "comment_karma": 8000,  "link_karma": 1800},
        "mix_vet_3": {"account_created_utc": days_ago(700),  "comment_karma": 5500,  "link_karma": 900},
        "mix_vet_4": {"account_created_utc": days_ago(1100), "comment_karma": 19000, "link_karma": 4000},
        "mix_vet_5": {"account_created_utc": days_ago(600),  "comment_karma": 3200,  "link_karma": 600},
        "mix_vet_6": {"account_created_utc": days_ago(1500), "comment_karma": 27000, "link_karma": 5500},
        "mix_new_1": {"account_created_utc": days_ago(8),  "comment_karma": 15, "link_karma": 2},
        "mix_new_2": {"account_created_utc": days_ago(5),  "comment_karma": 8,  "link_karma": 0},
        "mix_new_3": {"account_created_utc": days_ago(12), "comment_karma": 22, "link_karma": 3},
        "mix_new_4": {"account_created_utc": days_ago(6),  "comment_karma": 11, "link_karma": 1},
        "mix_new_5": {"account_created_utc": days_ago(9),  "comment_karma": 6,  "link_karma": 0},
        "mix_new_6": {"account_created_utc": days_ago(14), "comment_karma": 30, "link_karma": 4},
    }
    return CommentList(comments), profiles


def build_scenario_d():
    """Organic Flame War: All veterans with high karma, but using debunking keywords heavily."""
    comments = [
        Comment("f1", "post4", "This is fake news and you know it. Stop spreading hoaxes.", "flame_1", POST_TIMESTAMP + 100),
        Comment("f2", "post4", "Calling everything fake without evidence is lazy thinking.", "flame_2", POST_TIMESTAMP + 250),
        Comment("f3", "f1", "I have evidence. The original source was debunked last year.", "flame_1", POST_TIMESTAMP + 400),
        Comment("f4", "f3", "That debunking was itself misleading. Read the actual paper.", "flame_3", POST_TIMESTAMP + 600),
        Comment("f5", "post4", "Both sides are wrong. The truth is more nuanced than fake or real.", "flame_4", POST_TIMESTAMP + 900),
        Comment("f6", "f4", "You are a liar. This is propaganda and everyone can see it.", "flame_5", POST_TIMESTAMP + 1200),
        Comment("f7", "f6", "Name-calling is not an argument. Show me the AI detection results.", "flame_3", POST_TIMESTAMP + 1500),
        Comment("f8", "post4", "I ran it through a deepfake detector and it came back clean.", "flame_6", POST_TIMESTAMP + 2000),
        Comment("f9", "f8", "Those detectors are unreliable. This is clearly manipulated.", "flame_1", POST_TIMESTAMP + 2500),
        Comment("f10", "post4", "Can we stop with the hoax accusations and discuss the content?", "flame_7", POST_TIMESTAMP + 3200),
        Comment("f11", "f10", "The content IS the hoax. Wake up.", "flame_5", POST_TIMESTAMP + 3800),
        Comment("f12", "post4", "Fact check: the claims in this post are partially true, partially false.", "flame_8", POST_TIMESTAMP + 4500),
    ]
    profiles = {
        "flame_1": {"account_created_utc": days_ago(1500), "comment_karma": 35000, "link_karma": 8000},
        "flame_2": {"account_created_utc": days_ago(1200), "comment_karma": 22000, "link_karma": 5000},
        "flame_3": {"account_created_utc": days_ago(2000), "comment_karma": 48000, "link_karma": 11000},
        "flame_4": {"account_created_utc": days_ago(900),  "comment_karma": 15000, "link_karma": 3200},
        "flame_5": {"account_created_utc": days_ago(1800), "comment_karma": 29000, "link_karma": 6500},
        "flame_6": {"account_created_utc": days_ago(1100), "comment_karma": 18000, "link_karma": 4100},
        "flame_7": {"account_created_utc": days_ago(700),  "comment_karma": 9500,  "link_karma": 2000},
        "flame_8": {"account_created_utc": days_ago(1600), "comment_karma": 41000, "link_karma": 9500},
    }
    return CommentList(comments), profiles


def build_scenario_e():
    """Compromised Veterans: Old high-karma accounts with severe network anomalies."""
    # All comments within 30 seconds, near-identical text, low lexical diversity
    base_text = "This product changed my life completely. I recommend it to everyone. Five stars."
    comments = [
        Comment("e1", "post5", base_text, "comp_vet_1", POST_TIMESTAMP + 5),
        Comment("e2", "post5", "This product changed my life completely. I recommend it to everyone. Amazing.", "comp_vet_2", POST_TIMESTAMP + 8),
        Comment("e3", "post5", "This product changed my life. I recommend it to everyone. Five stars.", "comp_vet_3", POST_TIMESTAMP + 11),
        Comment("e4", "post5", base_text, "comp_vet_4", POST_TIMESTAMP + 14),
        Comment("e5", "post5", "This product changed my life completely. Recommend to everyone. Five stars.", "comp_vet_5", POST_TIMESTAMP + 17),
        Comment("e6", "post5", base_text, "comp_vet_6", POST_TIMESTAMP + 20),
        Comment("e7", "post5", "This product changed my life completely. I recommend it. Five stars.", "comp_vet_7", POST_TIMESTAMP + 23),
        Comment("e8", "post5", base_text, "comp_vet_8", POST_TIMESTAMP + 26),
        Comment("e9", "post5", "Product changed my life completely. I recommend it to everyone. Five stars.", "comp_vet_9", POST_TIMESTAMP + 29),
        Comment("e10", "post5", base_text, "comp_vet_10", POST_TIMESTAMP + 32),
    ]
    profiles = {
        "comp_vet_1":  {"account_created_utc": days_ago(1400), "comment_karma": 25000, "link_karma": 6000},
        "comp_vet_2":  {"account_created_utc": days_ago(1100), "comment_karma": 18000, "link_karma": 4500},
        "comp_vet_3":  {"account_created_utc": days_ago(900),  "comment_karma": 12000, "link_karma": 3000},
        "comp_vet_4":  {"account_created_utc": days_ago(1600), "comment_karma": 33000, "link_karma": 7800},
        "comp_vet_5":  {"account_created_utc": days_ago(1200), "comment_karma": 21000, "link_karma": 5200},
        "comp_vet_6":  {"account_created_utc": days_ago(800),  "comment_karma": 9500,  "link_karma": 2100},
        "comp_vet_7":  {"account_created_utc": days_ago(1500), "comment_karma": 28000, "link_karma": 6500},
        "comp_vet_8":  {"account_created_utc": days_ago(1000), "comment_karma": 15000, "link_karma": 3800},
        "comp_vet_9":  {"account_created_utc": days_ago(700),  "comment_karma": 8000,  "link_karma": 1900},
        "comp_vet_10": {"account_created_utc": days_ago(1300), "comment_karma": 20000, "link_karma": 4800},
    }
    return CommentList(comments), profiles


def build_scenario_f():
    """Edge Case F - Empty Thread: Zero comments. Should return safe defaults."""
    return CommentList([]), {}


def build_scenario_g():
    """Edge Case G - Single Spammer: One account posts 90% of comments in clean thread."""
    comments = [
        Comment("g1", "post7", "Buy my product now! Best deal ever! Click here!", "spammer_1", POST_TIMESTAMP + 10),
        Comment("g2", "post7", "Amazing deal! Buy now! Limited time offer!", "spammer_1", POST_TIMESTAMP + 20),
        Comment("g3", "post7", "Check out my store! Best prices guaranteed!", "spammer_1", POST_TIMESTAMP + 30),
        Comment("g4", "post7", "Free shipping today only! Buy my product!", "spammer_1", POST_TIMESTAMP + 40),
        Comment("g5", "post7", "Discount code SAVE50! Buy now before its gone!", "spammer_1", POST_TIMESTAMP + 50),
        Comment("g6", "post7", "Best product ever! Everyone is buying it! Act now!", "spammer_1", POST_TIMESTAMP + 60),
        Comment("g7", "post7", "Limited stock! Buy my product! Amazing quality!", "spammer_1", POST_TIMESTAMP + 70),
        Comment("g8", "post7", "Flash sale! Buy now! Best deal of the year!", "spammer_1", POST_TIMESTAMP + 80),
        Comment("g9", "post7", "This is clearly spam. Report this account.", "clean_1", POST_TIMESTAMP + 500),
        Comment("g10", "post7", "Mods, can we get this spammer banned?", "clean_2", POST_TIMESTAMP + 600),
    ]
    profiles = {
        "spammer_1": {"account_created_utc": days_ago(2),  "comment_karma": 1,    "link_karma": 0},
        "clean_1":   {"account_created_utc": days_ago(900), "comment_karma": 7500, "link_karma": 1800},
        "clean_2":   {"account_created_utc": days_ago(600), "comment_karma": 4200, "link_karma": 900},
    }
    return CommentList(comments), profiles


def build_scenario_h():
    """Edge Case H - Uncached Authors: Many comments but zero author profiles resolved."""
    comments = [
        Comment("u1", "post8", "Normal comment about the topic at hand.", "unknown_1", POST_TIMESTAMP + 100),
        Comment("u2", "post8", "I think this is a valid point worth discussing.", "unknown_2", POST_TIMESTAMP + 300),
        Comment("u3", "u1", "Interesting take. I had not considered that angle.", "unknown_3", POST_TIMESTAMP + 600),
        Comment("u4", "post8", "The evidence presented here is compelling.", "unknown_4", POST_TIMESTAMP + 1000),
        Comment("u5", "u4", "Agreed. The sources check out.", "unknown_5", POST_TIMESTAMP + 1500),
        Comment("u6", "post8", "Good thread. Saving for later reference.", "unknown_6", POST_TIMESTAMP + 2200),
        Comment("u7", "post8", "Can someone link the original study?", "unknown_7", POST_TIMESTAMP + 3000),
        Comment("u8", "u7", "Here you go, the DOI is in the article footer.", "unknown_8", POST_TIMESTAMP + 3500),
    ]
    # Empty profiles dict - simulates cache miss / no Reddit API data
    profiles = {}
    return CommentList(comments), profiles


# ===========================================================================
# SCENARIO REGISTRY
# ===========================================================================

SCENARIOS = [
    ("A: Organic Thread",              build_scenario_a, "Likely Authentic"),
    ("B: Bot-Farm Attack",             build_scenario_b, "Suspicious / High Risk"),
    ("C: Mixed Hybrid (50/50)",        build_scenario_c, "Minor Concerns / Suspicious"),
    ("D: Organic Flame War",           build_scenario_d, "Low / Minor Concerns"),
    ("E: Compromised Veterans",        build_scenario_e, "Suspicious / High Risk"),
    ("F: Empty Thread",                build_scenario_f, "Likely Authentic"),
    ("G: Single Spammer Flood",        build_scenario_g, "Suspicious / High Risk"),
    ("H: Uncached Authors (No Data)",  build_scenario_h, "Likely Authentic / Low"),
]


# ===========================================================================
# EXECUTION
# ===========================================================================

def run_all_scenarios():
    results = []

    for name, builder, expected in SCENARIOS:
        comment_list, profiles = builder()
        orchestrator = MainOrchestrator(
            comment_list=comment_list,
            author_profiles=profiles,
            post_created_utc=POST_TIMESTAMP,
        )
        payload = orchestrator.get_extension_payload()
        score = payload["confidence_score"]
        verdict = payload["verdict"]
        results.append((name, score, verdict, expected))

    return results


def print_summary_table(results):
    # Header
    print("\n")
    print("=" * 90)
    print("  SIMULATION RESULTS - 8 SCENARIO SUITE")
    print("=" * 90)
    print("")
    print(f"  {'Scenario':<35} {'Score':<10} {'Verdict':<20} {'Expected':<25}")
    print(f"  {'-'*33}  {'-'*8}  {'-'*18}  {'-'*23}")

    for name, score, verdict, expected in results:
        print(f"  {name:<35} {score:<10.4f} {verdict:<20} {expected:<25}")

    print("")
    print("=" * 90)

    # Validation checks
    print("\n  VALIDATION:")
    checks_passed = 0
    total_checks = 0

    # Check A < 0.20
    total_checks += 1
    if results[0][1] <= 0.20:
        print("  [PASS] Scenario A scored <= 0.20 (organic)")
        checks_passed += 1
    else:
        print(f"  [FAIL] Scenario A scored {results[0][1]:.4f} (expected <= 0.20)")

    # Check B > 0.45
    total_checks += 1
    if results[1][1] > 0.45:
        print("  [PASS] Scenario B scored > 0.45 (bot-farm)")
        checks_passed += 1
    else:
        print(f"  [FAIL] Scenario B scored {results[1][1]:.4f} (expected > 0.45)")

    # Check C is in middle range (0.20 - 0.70)
    total_checks += 1
    if 0.20 < results[2][1] < 0.70:
        print("  [PASS] Scenario C scored in middle range (hybrid)")
        checks_passed += 1
    else:
        print(f"  [FAIL] Scenario C scored {results[2][1]:.4f} (expected 0.20-0.70)")

    # Check D: veterans with keywords should NOT be High Risk
    total_checks += 1
    if results[3][1] < 0.70:
        print("  [PASS] Scenario D scored < 0.70 (veterans not falsely flagged)")
        checks_passed += 1
    else:
        print(f"  [FAIL] Scenario D scored {results[3][1]:.4f} (expected < 0.70)")

    # Check E: compromised veterans should trigger network analyzer
    total_checks += 1
    if results[4][1] > 0.20:
        print("  [PASS] Scenario E scored > 0.20 (network anomalies detected)")
        checks_passed += 1
    else:
        print(f"  [FAIL] Scenario E scored {results[4][1]:.4f} (expected > 0.20)")

    # Check F: empty thread should be safe
    total_checks += 1
    if results[5][1] <= 0.20:
        print("  [PASS] Scenario F scored <= 0.20 (empty thread safe)")
        checks_passed += 1
    else:
        print(f"  [FAIL] Scenario F scored {results[5][1]:.4f} (expected <= 0.20)")

    # Check G: single spammer should be high
    total_checks += 1
    if results[6][1] > 0.45:
        print("  [PASS] Scenario G scored > 0.45 (spammer detected)")
        checks_passed += 1
    else:
        print(f"  [FAIL] Scenario G scored {results[6][1]:.4f} (expected > 0.45)")

    # Check H: uncached authors should degrade gracefully
    total_checks += 1
    if results[7][1] <= 0.45:
        print("  [PASS] Scenario H scored <= 0.45 (graceful degradation)")
        checks_passed += 1
    else:
        print(f"  [FAIL] Scenario H scored {results[7][1]:.4f} (expected <= 0.45)")

    print(f"\n  TOTAL: {checks_passed}/{total_checks} checks passed")
    print("=" * 90)


if __name__ == "__main__":
    results = run_all_scenarios()
    print_summary_table(results)
