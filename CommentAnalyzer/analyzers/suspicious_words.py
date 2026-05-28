from CommentAnalyzer.models.comment import SuspicionLevel
from collections import Counter
import re
import os

import numpy as np
from google import genai
from google.genai import types

from CommentAnalyzer.models.comment_list import CommentList




# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEBUNKING_LEXICON = {
    "fake", "debunked", "photoshop", "photoshopped", "ai", "hoax", "liar",
    "false", "misleading", "midjourney", "dall-e", "dalle", "generated",
    "fabricated", "disinformation", "misinformation", "propaganda", "staged",
    "manipulated", "doctored", "deepfake", "bot", "bots", "astroturf",
    "shill", "shills", "scam", "fraud", "fraudulent", "clickbait",
    "debunk", "fact-check", "factcheck", "fact check", "bs", "bullshit",
    "cap", "capping", "sus", "suspicious", "altered", "edited",
    "ai-generated", "ai generated", "chatgpt", "gpt", "stable diffusion",
}

# Thresholds for activating LLM verification gate
DENSITY_THRESHOLD = 0.05        # At least 5% of comments must flag
UNIQUE_AUTHOR_THRESHOLD = 0.3   # At least 30% of flagged comments from unique authors
LLM_SAMPLE_SIZE = 15            # Max comments sent to Gemini for verification

# Weights for final score combination
KEYWORD_WEIGHT = 0.55
LLM_WEIGHT = 0.45


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class CommunityDebunkingAnalyzer:
    """
    Detects whether the community is actively exposing or debunking the
    main post as fake, AI-generated, or a disinformation campaign.

    Uses a hybrid approach:
      1. Fast Lexicon Mapping — keyword scan + unique-author ratio
      2. LLM Verification Gate — Gemini confirms genuine debunking intent
    """

    def __init__(self, comment_list: CommentList):
        self.comment_list = comment_list
        self._configure_gemini()

    # ------------------------------------------------------------------
    # Gemini configuration
    # ------------------------------------------------------------------

    def _configure_gemini(self) -> None:
        """Configure the Gemini client from environment variable."""
        api_key = os.environ.get("GEMINI_API_KEY", "")
        if api_key:
            self._client = genai.Client(api_key=api_key)
            self._gemini_available = True
        else:
            self._client = None
            self._gemini_available = False

    # ------------------------------------------------------------------
    # 1. Keyword / Lexicon Analysis
    # ------------------------------------------------------------------

    def analyze_by_keywords(self) -> dict:
        """
        Scan all comments against the debunking lexicon.

        Returns a dict with:
          - "score": float [0.0, 1.0]
          - "flagged_texts": list of raw texts that matched
          - "discussion_density": float
          - "unique_author_ratio": float
          - "flagged_count": int
        """
        comments = self.comment_list.get_all_comments()
        total = len(comments)

        if total == 0:
            return {
                "score": 0.0,
                "flagged_texts": [],
                "discussion_density": 0.0,
                "unique_author_ratio": 0.0,
                "flagged_count": 0,
            }

        flagged_comments = []
        flagged_authors = []

        for comment in comments:
            text = comment.cleaned_text if comment.cleaned_text else ""
            if not text:
                continue

            # Check if any lexicon term appears in the comment
            if self._text_matches_lexicon(text):
                flagged_comments.append(comment.text or "")
                flagged_authors.append(comment.author or "")

        flagged_count = len(flagged_comments)

        if flagged_count == 0:
            return {
                "score": 0.0,
                "flagged_texts": [],
                "discussion_density": 0.0,
                "unique_author_ratio": 0.0,
                "flagged_count": 0,
            }

        # Discussion density: what fraction of the thread is debunking
        discussion_density = flagged_count / total

        # Unique author ratio: grassroots check (not one troll flooding)
        unique_authors = len(set(a for a in flagged_authors if a and a != "[deleted]"))
        unique_author_ratio = unique_authors / flagged_count if flagged_count > 0 else 0.0

        # Combine into a raw score
        # High density + high unique-author ratio = strong community debunking
        raw_score = (discussion_density * 0.6) + (unique_author_ratio * 0.4)
        score = min(1.0, max(0.0, raw_score * 2.5))  # Scale up, cap at 1.0

        return {
            "score": score,
            "flagged_texts": flagged_comments,
            "discussion_density": discussion_density,
            "unique_author_ratio": unique_author_ratio,
            "flagged_count": flagged_count,
        }

    def _text_matches_lexicon(self, cleaned_text: str) -> bool:
        """Check if cleaned text contains any debunking lexicon term."""
        words = set(re.findall(r'[a-z0-9\-]+', cleaned_text))
        # Single-word matches
        if words & DEBUNKING_LEXICON:
            return True
        # Multi-word phrase matches (e.g., "fact check", "ai generated")
        for phrase in DEBUNKING_LEXICON:
            if " " in phrase or "-" in phrase:
                if phrase in cleaned_text:
                    return True
        return False

    # ------------------------------------------------------------------
    # 2. LLM Verification (Gemini)
    # ------------------------------------------------------------------

    def verify_with_llm(self, suspect_texts: list) -> float:
        """
        Pass flagged comments to Gemini to verify genuine debunking intent.
        Filters out sarcasm, trolling, and false positives.

        Args:
            suspect_texts: List of raw comment texts flagged by keyword scan.

        Returns:
            Float between 0.0 and 1.0 where:
              1.0 = community is clearly presenting counter-evidence
              0.0 = no genuine debunking detected (sarcasm/trolling)
        """
        if not self._gemini_available:
            # Fallback: if no API key, return a moderate confidence based on
            # the keyword analysis alone (no LLM gate)
            return 0.5

        if not suspect_texts:
            return 0.0

        # Sample up to LLM_SAMPLE_SIZE comments
        sample = suspect_texts[:LLM_SAMPLE_SIZE]

        system_prompt = (
            "You are a disinformation analysis expert. You will receive a list of "
            "Reddit comments that were flagged because they contain debunking-related "
            "keywords (e.g., 'fake', 'hoax', 'AI-generated', 'misleading').\n\n"
            "Your task: Evaluate whether these comments represent a GENUINE community "
            "effort to debunk or expose the original post as false/manipulated. "
            "Consider:\n"
            "- Are commenters presenting evidence, sources, or logical arguments?\n"
            "- Are they calling out specific inconsistencies?\n"
            "- Or are they being sarcastic, trolling, or using these words in a "
            "non-debunking context (e.g., 'anyone who thinks this is fake is crazy')?\n\n"
            "Respond with ONLY a single floating-point number between 0.0 and 1.0:\n"
            "- 1.0 = The community is clearly and genuinely debunking the post with "
            "evidence or strong arguments.\n"
            "- 0.0 = No genuine debunking is happening; keywords are used sarcastically "
            "or out of context.\n\n"
            "Return ONLY the number. No explanation."
        )

        comments_block = "\n---\n".join(
            f"Comment {i+1}: {text}" for i, text in enumerate(sample)
        )

        user_prompt = (
            f"Here are {len(sample)} flagged comments from a Reddit thread:\n\n"
            f"{comments_block}\n\n"
            "Score (0.0 to 1.0):"
        )

        try:
            response = self._client.models.generate_content(
                model="gemini-2.0-flash",
                contents=system_prompt + "\n\n" + user_prompt,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=10,
                ),
            )

            # Parse the response — expect a single float
            raw_output = response.text.strip()
            score = float(raw_output)
            return min(1.0, max(0.0, score))

        except (ValueError, TypeError):
            # Gemini returned non-numeric text — fallback
            return 0.5
        except Exception:
            # Network error, rate limit, invalid key, etc.
            return 0.5

    # ------------------------------------------------------------------
    # 3. Orchestrator
    # ------------------------------------------------------------------

    def analyze(self) -> SuspicionLevel:
        """
        Orchestrate keyword analysis + LLM verification.

        Returns a SuspicionLevel indicating how strongly the community
        is debunking the post. Higher levels = stronger debunking signal
        (i.e., the POST is more likely fake/manipulated).
        """
        if self.comment_list.size() == 0:
            return SuspicionLevel.VERY_LOW

        # Step 1: Fast lexicon scan
        keyword_result = self.analyze_by_keywords()
        keyword_score = keyword_result["score"]
        discussion_density = keyword_result["discussion_density"]
        unique_author_ratio = keyword_result["unique_author_ratio"]
        flagged_texts = keyword_result["flagged_texts"]

        # Step 2: Decide whether to activate LLM gate
        # Only call Gemini if there's meaningful signal from keywords
        llm_score = 0.0
        llm_activated = False

        if (discussion_density >= DENSITY_THRESHOLD and
                unique_author_ratio >= UNIQUE_AUTHOR_THRESHOLD and
                len(flagged_texts) >= 3):
            llm_score = self.verify_with_llm(flagged_texts)
            llm_activated = True

        # Step 3: Compute final score
        if llm_activated:
            final_score = (keyword_score * KEYWORD_WEIGHT) + (llm_score * LLM_WEIGHT)
        else:
            # Without LLM confirmation, rely solely on keyword score but dampen it
            final_score = keyword_score * 0.6

        final_score = min(1.0, max(0.0, final_score))

        # Step 4: Map to SuspicionLevel
        return self._map_to_level(final_score)

    def analyze_detailed(self) -> dict:
        """
        Full analytical breakdown for the journalist UI.

        Returns a dictionary with all sub-scores and metadata.
        """
        if self.comment_list.size() == 0:
            return {
                "suspicion_level": SuspicionLevel.VERY_LOW.name,
                "final_score": 0.0,
                "sub_scores": {
                    "keyword_score": 0.0,
                    "llm_verification_score": 0.0,
                },
                "metadata": {
                    "total_comments": 0,
                    "flagged_comments": 0,
                    "discussion_density": 0.0,
                    "unique_author_ratio": 0.0,
                    "llm_activated": False,
                    "gemini_available": self._gemini_available,
                },
            }

        # Step 1: Keyword analysis
        keyword_result = self.analyze_by_keywords()
        keyword_score = keyword_result["score"]
        discussion_density = keyword_result["discussion_density"]
        unique_author_ratio = keyword_result["unique_author_ratio"]
        flagged_texts = keyword_result["flagged_texts"]
        flagged_count = keyword_result["flagged_count"]

        # Step 2: LLM gate
        llm_score = 0.0
        llm_activated = False

        if (discussion_density >= DENSITY_THRESHOLD and
                unique_author_ratio >= UNIQUE_AUTHOR_THRESHOLD and
                len(flagged_texts) >= 3):
            llm_score = self.verify_with_llm(flagged_texts)
            llm_activated = True

        # Step 3: Final score
        if llm_activated:
            final_score = (keyword_score * KEYWORD_WEIGHT) + (llm_score * LLM_WEIGHT)
        else:
            final_score = keyword_score * 0.6

        final_score = min(1.0, max(0.0, final_score))
        level = self._map_to_level(final_score)

        return {
            "suspicion_level": level.name,
            "final_score": round(final_score, 4),
            "sub_scores": {
                "keyword_score": round(keyword_score, 4),
                "llm_verification_score": round(llm_score, 4),
            },
            "metadata": {
                "total_comments": self.comment_list.size(),
                "flagged_comments": flagged_count,
                "discussion_density": round(discussion_density, 4),
                "unique_author_ratio": round(unique_author_ratio, 4),
                "llm_activated": llm_activated,
                "gemini_available": self._gemini_available,
            },
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _map_to_level(score: float) -> SuspicionLevel:
        """Map a continuous score to the discrete SuspicionLevel enum."""
        if score <= 0.15:
            return SuspicionLevel.VERY_LOW
        elif score <= 0.35:
            return SuspicionLevel.LOW
        elif score <= 0.60:
            return SuspicionLevel.MEDIUM
        elif score <= 0.80:
            return SuspicionLevel.HIGH
        else:
            return SuspicionLevel.VERY_HIGH
