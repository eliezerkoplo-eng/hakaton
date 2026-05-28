"""
Account Age & Karma Profiler Analyzer
=====================================

Detects coordinated inauthentic behavior by analyzing the identity layer:
account age clustering, karma-to-activity mismatch, and age-vs-sentiment
correlation (astroturfing detection).

This is the only analyzer that requires external data beyond CommentList —
it consumes a dict of AuthorProfile objects resolved from the cache layer.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from CommentAnalyzer.models.comment_list import CommentList
from CommentAnalyzer.models.comment import Comment


# ---------------------------------------------------------------------------
# Type alias for author profile data from the cache layer.
# Each profile is a dict with keys:
#   "account_created_utc" (float), "comment_karma" (int),
#   "link_karma" (int), "cached_at" (float)
# ---------------------------------------------------------------------------
AuthorProfile = dict[str, Any]


# ---------------------------------------------------------------------------
# Constants (can be moved to constants.py later)
# ---------------------------------------------------------------------------

# Age bands (in days relative to the post timestamp)
AGE_BAND_FRESH = 7          # < 7 days
AGE_BAND_NEW = 30           # 7–30 days
AGE_BAND_ESTABLISHED = 365  # 30–365 days
# > 365 days = Veteran

# Karma threshold for "low karma" classification
LOW_KARMA_THRESHOLD = 100

# Minimum unique authors required for meaningful analysis
MIN_AUTHORS_FOR_ANALYSIS = 3

# Minimum authors per group for astroturf correlation
MIN_GROUP_SIZE = 3

# Coverage below which the final score is penalized
MIN_COVERAGE_RATIO = 0.4

# Internal sub-metric weights (must sum to 1.0)
CLUSTERING_WEIGHT = 0.35
KARMA_WEIGHT = 0.30
ASTROTURF_WEIGHT = 0.35


class AccountProfilerAnalyzer:
    """
    Analyzes commenter identity signals to detect bot farms and astroturfing.

    Combines three sub-metrics:
      1. New Account Clustering — ratio of fresh/new accounts in the thread
      2. Karma-to-Activity Mismatch — ratio of low-karma accounts
      3. Age vs. Sentiment Correlation — sentiment gap between new and established accounts

    Requires:
      - A CommentList with all thread comments
      - A dict mapping usernames to AuthorProfile dicts (from cache layer)
    """

    def __init__(
        self,
        comment_list: CommentList,
        author_profiles: dict[str, AuthorProfile],
        post_created_utc: float | None = None,
    ) -> None:
        """
        Initialize the Account Profiler Analyzer.

        Args:
            comment_list: The CommentList abstraction containing all thread comments.
            author_profiles: Dict mapping author usernames to their cached profile data.
                             Keys are usernames (str), values are AuthorProfile dicts with
                             at minimum: "account_created_utc", "comment_karma", "link_karma".
            post_created_utc: Unix timestamp of the original post creation. Used as the
                              reference point for computing account ages. If None, falls
                              back to the earliest comment timestamp in the thread.
        """
        self.comment_list = comment_list
        self.author_profiles = author_profiles
        self.post_created_utc = post_created_utc

        # Resolved at analysis time
        self._unique_authors: list[str] = []
        self._resolved_authors: dict[str, AuthorProfile] = {}
        self._coverage_ratio: float = 0.0

    # ------------------------------------------------------------------
    # Public Interface
    # ------------------------------------------------------------------

    def analyze(self) -> float:
        """
        Run all three sub-metrics and return a single aggregated score.

        Returns:
            Float in [0.0, 1.0] representing account-level suspicion.
            Higher = more bot-farm / astroturfing signals.
            Returns 0.0 if insufficient data (< MIN_AUTHORS_FOR_ANALYSIS
            unique authors or coverage below MIN_COVERAGE_RATIO).
        """
        self._resolve_authors()

        if self._coverage_ratio < MIN_COVERAGE_RATIO:
            return 0.0

        clustering_test = self._calculate_clustering_score()
        karma_test = self._calculate_karma_score()
        astroturf_test = self._calculate_astroturf_score()

        grade_clustering = clustering_test * CLUSTERING_WEIGHT
        grade_karma = karma_test * KARMA_WEIGHT
        grade_astroturf = astroturf_test * ASTROTURF_WEIGHT

        raw_grade = grade_clustering + grade_karma + grade_astroturf

        final_grade = raw_grade * self._coverage_ratio
        return self._sanitize_score(final_grade)

    def analyze_detailed(self) -> dict:
        """
        Run full analysis and return a structured breakdown for the journalist UI.

        Returns:
            Dict with keys:
              - "score" (float): The aggregated account profiler score [0.0, 1.0]
              - "sub_scores" (dict): {
                    "clustering": float,
                    "karma_mismatch": float,
                    "astroturf_correlation": float
                }
              - "metadata" (dict): {
                    "unique_authors": int,
                    "resolved_authors": int,
                    "coverage_ratio": float,
                    "age_distribution": {"fresh": int, "new": int, "established": int, "veteran": int},
                    "low_karma_count": int,
                    "sentiment_gap": float | None
                }
        """
        final_score = self.analyze()
        age_dist = {"fresh": 0, "new": 0, "established": 0, "veteran": 0}
        low_karma_count = 0

        reference_timestamp = self._get_reference_timestamp()

        for profile in self._resolved_authors.values():
            comment_karma = profile.get("comment_karma", 0)
            link_karma = profile.get("link_karma", 0)
            if (comment_karma + link_karma) < LOW_KARMA_THRESHOLD:
                low_karma_count += 1

            days = self._compute_account_age_days(profile, reference_timestamp)
            if days < AGE_BAND_FRESH:
                age_dist["fresh"] += 1
            elif days < AGE_BAND_NEW:
                age_dist["new"] += 1
            elif days < AGE_BAND_ESTABLISHED:
                age_dist["established"] += 1
            else:
                age_dist["veteran"] += 1

        clustering = self._calculate_clustering_score()
        karma_mismatch = self._calculate_karma_score()
        astroturf = self._calculate_astroturf_score()

        return {
            "score": round(final_score, 4),
            "sub_scores": {
                "clustering": round(clustering, 4),
                "karma_mismatch": round(karma_mismatch, 4),
                "astroturf_correlation": round(astroturf, 4)
            },
            "metadata": {
                "unique_authors": len(self._unique_authors),
                "resolved_authors": len(self._resolved_authors),
                "coverage_ratio": round(self._coverage_ratio, 4),
                "age_distribution": age_dist,
                "low_karma_count": low_karma_count
            }
        }

    # ------------------------------------------------------------------
    # Private Sub-Metric Methods
    # ------------------------------------------------------------------

    def _resolve_authors(self) -> None:
        """
        Extract unique authors from the CommentList, look them up in
        author_profiles, and compute coverage ratio.

        Populates:
          - self._unique_authors
          - self._resolved_authors (only those found in cache)
          - self._coverage_ratio
        """
        all_authors = self.comment_list.get_all_authors()
        unique_set = set(all_authors)

        ignored_authors = {None, "[deleted]", "[removed]", "AutoModerator"}
        self._unique_authors = [author for author in unique_set if author not in ignored_authors]

        self._resolved_authors = {}
        for author in self._unique_authors:
            if author in self.author_profiles:
                self._resolved_authors[author] = self.author_profiles[author]
        if len(self._unique_authors) > 0:
            self._coverage_ratio = len(self._resolved_authors) / len(self._unique_authors)
        else:
            self._coverage_ratio = 0.0

    def _get_reference_timestamp(self) -> float:
        """
        Determine the reference timestamp for computing account ages.

        Returns post_created_utc if provided, otherwise the earliest
        comment timestamp in the thread.
        """
        if self.post_created_utc is not None:
            return self.post_created_utc
        else:
            times = self.comment_list.get_all_timestamps()
            if len(times) > 0:
                return min(times)

        return 0.0

    def _calculate_clustering_score(self) -> float:
        """
        Measure the ratio of fresh/new accounts in the thread.

        Algorithm:
          • For each resolved author, compute account_age_days =
            (reference_timestamp - account_created_utc) / 86400
          • Bucket into age bands: Fresh (<7d), New (7-30d),
            Established (30-365d), Veteran (>365d)
          • fresh_ratio = (fresh_count + new_count) / total_resolved
          • Return min(1.0, fresh_ratio * 1.8)
            (55%+ young accounts → max score; organic threads are 5-15%)

        Returns:
            Float in [0.0, 1.0]. Returns 0.0 if fewer than
            MIN_AUTHORS_FOR_ANALYSIS authors are resolved.
        """
        if len(self._resolved_authors) < MIN_AUTHORS_FOR_ANALYSIS:
            return 0.0

        reference_timestamp = self._get_reference_timestamp()
        young_count = 0

        for profile in self._resolved_authors.values():
            days = self._compute_account_age_days(profile, reference_timestamp)

            if days < AGE_BAND_NEW:
                young_count += 1

        fresh_ratio = young_count / len(self._resolved_authors)
        return min(1.0, fresh_ratio * 1.8)



    def _calculate_karma_score(self) -> float:
        """
        Measure the ratio of low-karma accounts in the thread.

        Algorithm:
          • For each resolved author, compute total_karma =
            comment_karma + link_karma
          • Count authors with total_karma < LOW_KARMA_THRESHOLD (100)
          • low_karma_ratio = low_karma_count / total_resolved
          • Return min(1.0, low_karma_ratio * 2.0)
            (50%+ low-karma accounts → max score)

        Returns:
            Float in [0.0, 1.0]. Returns 0.0 if fewer than
            MIN_AUTHORS_FOR_ANALYSIS authors are resolved.
        """
        if len(self._resolved_authors) < MIN_AUTHORS_FOR_ANALYSIS:
            return 0.0

        low_karma_count = 0
        for profile in self._resolved_authors.values():
            comment_karma = profile.get("comment_karma", 0)
            link_karma = profile.get("link_karma", 0)

            total_karma = comment_karma + link_karma
            if total_karma < LOW_KARMA_THRESHOLD:
                low_karma_count += 1

        low_karma_ratio = low_karma_count / len(self._resolved_authors)
        return min(1.0, low_karma_ratio * 2.0)

    def _calculate_astroturf_score(self) -> float:
        """
        Cross-reference account age with comment sentiment to detect
        coordinated opinion planting.

        Algorithm:
          • Split resolved authors into two groups:
            - new_group: account age < 30 days
            - established_group: account age > 90 days
          • For each group, collect all their comments from CommentList
          • Compute average sentiment polarity per group using keyword-based
            scoring (positive_words - negative_words) / total_words
          • sentiment_gap = new_group_mean_polarity - established_group_mean_polarity
          • Return min(1.0, max(0.0, sentiment_gap * 2.0))
            (gap of 0.5+ is a very strong astroturfing signal)

        Returns:
            Float in [0.0, 1.0]. Returns 0.0 if either group has fewer
            than MIN_GROUP_SIZE (3) authors.
        """
        if len(self._resolved_authors) < MIN_AUTHORS_FOR_ANALYSIS:
            return 0.0

        reference_timestamp = self._get_reference_timestamp()

        new_group_scores = []
        established_group_scores = []

        for username, profile in self._resolved_authors.items():
            days = self._compute_account_age_days(profile, reference_timestamp)

            author_comments = self.comment_list.get_comments_by_author(username)

            if days < 30:
                for comment in author_comments:
                    cleaned_text = comment.cleaned_text if comment.cleaned_text else ""
                    score = self._compute_comment_polarity(cleaned_text)
                    new_group_scores.append(score)

            elif days > 90:

                for comment in author_comments:
                    cleaned_text = comment.cleaned_text if comment.cleaned_text else ""
                    score = self._compute_comment_polarity(cleaned_text)
                    established_group_scores.append(score)

        if len(new_group_scores) < MIN_GROUP_SIZE or len(established_group_scores) < MIN_GROUP_SIZE:
                return 0.0

        new_mean = np.mean(new_group_scores)
        established_mean = np.mean(established_group_scores)

        sentiment_gap = new_mean - established_mean
        astroturf_score = sentiment_gap * 2.0

        return min(1.0, max(0.0, astroturf_score))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _compute_account_age_days(self, profile: AuthorProfile, reference_ts: float) -> float:
        """
        Compute account age in days relative to the reference timestamp.

        Args:
            profile: The author's cached profile dict.
            reference_ts: The Unix timestamp to measure age against.

        Returns:
            Age in days (float). Returns 0.0 if account_created_utc is
            missing or invalid.
        """
        created_utc = profile.get("account_created_utc", 0)


        if created_utc <= 0:
            return 0.0

        days = (reference_ts - created_utc) / 86400
        return max(0.0, days)

    def _compute_comment_polarity(self, text: str) -> float:
        """
        Compute keyword-based sentiment polarity for a single comment.

        Uses the same positive/negative word lists as the SentimentAnalyzer.
        Formula: (positive_count - negative_count) / total_word_count

        Args:
            text: The cleaned (lowercase, stripped) comment text.

        Returns:
            Float in [-1.0, 1.0]. Returns 0.0 for empty text.
        """
        if not text:
            return 0.0

        words = text.split()
        total_words = len(words)

        if total_words == 0:
            return 0.0

        positive_count = 0
        negative_count = 0

        #later to use a diffrent approch
        positive_lexicon = {"good", "great", "amazing", "agree", "true", "yes", "support"}
        negative_lexicon = {"bad", "fake", "liar", "hoax", "wrong", "no", "shame", "bs"}

        for word in words:
            cleaned_word = word.strip(",.!?;:")

            if cleaned_word.lower() in positive_lexicon:
                positive_count += 1
            elif cleaned_word.lower() in negative_lexicon:
                negative_count += 1

        polarity = (positive_count - negative_count) / total_words
        return polarity



    @staticmethod
    def _sanitize_score(score: float) -> float:
        """Clamp score to [0.0, 1.0] and replace NaN/Inf with 0.0."""
        if np.isnan(score) or np.isinf(score):
            return 0.0

        return min(1.0, max(0.0, score))
