"""
MainOrchestrator
================

Central orchestration layer for the Reddit Browser Extension backend.
Merges the outputs of AccountProfilerAnalyzer and CommunityDebunkingAnalyzer
into a single unified JSON payload optimized for the extension popup UI.
"""

from __future__ import annotations

from typing import Any

from CommentAnalyzer.models.comment_list import CommentList
from CommentAnalyzer.analyzers.account_profiler import AccountProfilerAnalyzer, AuthorProfile
from CommentAnalyzer.analyzers.suspicious_words import CommunityDebunkingAnalyzer
from CommentAnalyzer.analyzers.bot_network_analyzer import BotNetworkAnalyzer


# ---------------------------------------------------------------------------
# Verdict thresholds & labels
# ---------------------------------------------------------------------------

VERDICT_THRESHOLDS = [
    (0.20, "Likely Authentic"),
    (0.45, "Minor Concerns"),
    (0.70, "Suspicious"),
]
VERDICT_HIGH_RISK = "High Risk"

# Weights for combining the two analyzer scores
PROFILER_WEIGHT = 0.40
NETWORK_WEIGHT = 0.35
DEBUNKER_WEIGHT = 0.25


class MainOrchestrator:
    """
    Unified orchestrator that runs both core analyzers and produces
    a single JSON-ready payload for the browser extension popup.

    Responsibilities:
      1. Instantiate AccountProfilerAnalyzer and CommunityDebunkingAnalyzer
      2. Combine their scores into a weighted verdict
      3. Merge their detailed outputs into one extension-friendly dict
      4. Generate human-readable flag strings for the UI bullet list
    """

    def __init__(
        self,
        comment_list: CommentList,
        author_profiles: dict[str, AuthorProfile],
        post_created_utc: float | None = None,
    ) -> None:
        """
        Initialize the orchestrator with shared data and instantiate analyzers.

        Args:
            comment_list: The CommentList abstraction containing all thread comments.
            author_profiles: Dict mapping author usernames to their cached profile
                             data (account_created_utc, comment_karma, link_karma).
            post_created_utc: Unix timestamp of the original post. Used by the
                              AccountProfilerAnalyzer as the reference point for
                              computing account ages. Optional — falls back internally.
        """
        self.comment_list = comment_list
        self.author_profiles = author_profiles
        self.post_created_utc = post_created_utc
        self.network_analyzer = BotNetworkAnalyzer(comment_list=self.comment_list)

        # Instantiate sub-analyzers
        self.profiler = AccountProfilerAnalyzer(
            comment_list=self.comment_list,
            author_profiles=self.author_profiles,
            post_created_utc=self.post_created_utc,
        )
        self.debunker = CommunityDebunkingAnalyzer(
            comment_list=self.comment_list,
        )

    # ------------------------------------------------------------------
    # Public Interface
    # ------------------------------------------------------------------

    def analyze_post(self) -> dict[str, Any]:
        """
        Compute the unified risk score and map it to a verdict string
        for the extension's main badge display.

        Logic (to be implemented):
          1. Call self.profiler.analyze() → float [0.0, 1.0]
          2. Call self.debunker.analyze_by_keywords()["score"] → float [0.0, 1.0]
             (use keyword score directly to avoid LLM latency for badge-only mode)
          3. combined = (profiler_score * PROFILER_WEIGHT) + (debunker_score * DEBUNKER_WEIGHT)
          4. Map combined score to verdict string:
               ≤ 0.20 → "Likely Authentic"
               ≤ 0.45 → "Minor Concerns"
               ≤ 0.70 → "Suspicious"
               > 0.70 → "High Risk"

        Returns:
            {
                "confidence_score": float,       # Combined score [0.0, 1.0]
                "verdict": str,                  # Human-readable badge text
                "risk_level": str,               # SuspicionLevel enum name (mapped)
                "profiler_score": float,         # Raw profiler sub-score
                "debunker_score": float,         # Raw debunker sub-score
            }
        """
        profiler_score = self.profiler.analyze()
        debunker_score = self.debunker.analyze_by_keywords()["score"]

        net = self.network_analyzer
        self.network_sub_scores = {
            "volume_ratio": net.analyze_by_volume(),
            "text_similarity": net.analyze_by_text_similarity(),
            "time_bursts": net.analyze_by_time_bursts(),
            "text_patterns": net.analyze_by_text_patterns(),
            "network_topology": net.analyze_by_network_topology(),
            "activity_hours": net.analyze_by_activity_hours(),
            "lexical_diversity": net.analyze_by_lexical_diversity(),
        }

        network_score = (
                (self.network_sub_scores["volume_ratio"] * 0.20) +
                (self.network_sub_scores["text_similarity"] * 0.20) +
                (self.network_sub_scores["time_bursts"] * 0.15) +
                (self.network_sub_scores["text_patterns"] * 0.10) +
                (self.network_sub_scores["network_topology"] * 0.10) +
                (self.network_sub_scores["activity_hours"] * 0.10) +
                (self.network_sub_scores["lexical_diversity"] * 0.15)
        )


        combined_score = (
                (profiler_score * PROFILER_WEIGHT) +
                (network_score * NETWORK_WEIGHT) +
                (debunker_score * DEBUNKER_WEIGHT)
        )


        if network_score > 0.45 and combined_score < 0.25:
            combined_score = max(combined_score, network_score * 0.85)


        if self.network_sub_scores["volume_ratio"] > 0.70:
            combined_score = max(combined_score, 0.48)

        verdict = self._map_score_to_verdict(combined_score)

        return {
            "confidence_score": round(combined_score, 4),
            "verdict": verdict,
            "risk_level": verdict,
            "profiler_score": round(profiler_score, 4),
            "network_score": round(network_score, 4),
            "debunker_score": round(debunker_score, 4),
        }


    def get_extension_payload(self) -> dict[str, Any]:
        """
        Produce the full unified JSON payload for the extension popup dashboard.

        Logic (to be implemented):
          1. Call self.profiler.analyze_detailed() → dict
          2. Call self.debunker.analyze_detailed() → dict
          3. Call self.analyze_post() to get the combined verdict
          4. Merge all outputs into a single nested structure
          5. Generate human-readable flags from sub-scores exceeding 0.5

        Returns:
            {
                "verdict": str,
                "confidence_score": float,
                "risk_level": str,

                "account_analysis": {
                    "score": float,
                    "sub_scores": {...},
                    "metadata": {
                        "age_distribution": {...},
                        "low_karma_count": int,
                        "coverage_ratio": float,
                        ...
                    }
                },

                "community_debunking": {
                    "score": float,
                    "sub_scores": {...},
                    "metadata": {
                        "discussion_density": float,
                        "unique_author_ratio": float,
                        "llm_activated": bool,
                        ...
                    }
                },

                "flags": [str, ...],            # Human-readable explanations

                "metadata": {
                    "total_comments": int,
                    "unique_authors": int,
                    "analysis_timestamp": float,
                }
            }
        """
        profiler_detail = self.profiler.analyze_detailed()
        debunker_detail = self.debunker.analyze_detailed()


        post_summary = self.analyze_post()
        flags = self._generate_flags(profiler_detail, debunker_detail)

        import time

        return {
            "verdict": post_summary["verdict"],
            "confidence_score": post_summary["confidence_score"],
            "risk_level": post_summary["risk_level"],

            "account_analysis": profiler_detail,

            # שליפה מהירה מהזיכרון ללא חישוב מחדש!
            "network_analysis": {
                "score": post_summary["network_score"],
                "sub_scores": {k: round(v, 4) for k, v in self.network_sub_scores.items()}
            },

            "community_debunking": debunker_detail,
            "flags": flags,

            "metadata": {
                "total_comments": len(self.comment_list.get_all_timestamps()),
                "unique_authors": profiler_detail.get("metadata", {}).get("unique_authors", 0),
                "analysis_timestamp": time.time()
            }
        }
    # ------------------------------------------------------------------
    # Private Helpers
    # ------------------------------------------------------------------

    def _map_score_to_verdict(self, score: float) -> str:
        """
        Map a combined score [0.0, 1.0] to a verdict string.

        Uses VERDICT_THRESHOLDS for boundary checks.
        Scores above the highest threshold return VERDICT_HIGH_RISK.

        Args:
            score: The combined weighted score.

        Returns:
            One of: "Likely Authentic", "Minor Concerns", "Suspicious", "High Risk"
        """
        for (threshold, msg) in VERDICT_THRESHOLDS:
            if score <= threshold:
                return msg
        return VERDICT_HIGH_RISK

    def _generate_flags(
        self,
        profiler_detail: dict[str, Any],
        debunker_detail: dict[str, Any],
    ) -> list[str]:
        """
        Generate human-readable flag strings from analyzer outputs.

        Checks sub-scores and metadata values against thresholds to produce
        bullet-point explanations the extension UI can render directly.

        Examples of generated flags:
          - "65% of commenters have accounts < 30 days old"
          - "Community is actively debunking with evidence (density: 35%)"
          - "Low karma accounts dominate the thread (42% below 100 karma)"

        Args:
            profiler_detail: Output dict from AccountProfilerAnalyzer.analyze_detailed()
            debunker_detail: Output dict from CommunityDebunkingAnalyzer.analyze_detailed()

        Returns:
            List of human-readable strings, ordered by severity (highest first).
        """
        flags = []

        profiler_subs = profiler_detail.get("sub_scores", {})

        if profiler_subs.get("clustering", 0.0) > 0.5:
            flags.append("High concentration of newly created accounts posting in this thread.")

        if profiler_subs.get("karma_mismatch", 0.0) > 0.5:
            flags.append("Thread activity is heavily dominated by accounts with near-zero karma.")

        if profiler_subs.get("astroturf_correlation", 0.0) > 0.5:
            flags.append("Suspicious sentiment shift: new accounts are unusually positive compared to older users.")


        debunker_subs = debunker_detail.get("sub_scores", {})
        debunker_meta = debunker_detail.get("metadata", {})


        if debunker_detail.get("score", 0.0) > 0.5:
            flags.append("Community is actively challenging or debunking the validity of this post.")


        if debunker_meta.get("discussion_density", 0.0) > 0.2:
            flags.append("An unusually high percentage of comments contain keywords like 'fake', 'hoax', or 'AI'.")

        return flags
