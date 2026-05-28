"""
REDITRUE - Multi-Modal Authenticity Verification API
=====================================================

Central REST API that orchestrates three analysis pillars:
  1. Comment Network Analysis (this team's module)
  2. Author Reputation Analysis (Teammate A)
  3. Image Forensics Analysis (Teammate B)

Run:
    uvicorn app:app --reload --port 8000
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from CommentAnalyzer import Comment, CommentList, MainOrchestrator


# ===========================================================================
# FastAPI App
# ===========================================================================

app = FastAPI(
    title="insert here",
    description="Multi-Modal Reddit Post Authenticity Verification API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================================================
# Pydantic Models
# ===========================================================================

class CommentItem(BaseModel):
    id: str
    parent_id: str | None = None
    text: str = ""
    author: str = ""
    created_utc: float = 0.0


class AuthorAnalysis(BaseModel):
    """Teammate A's author reputation input."""
    author_reputation_score: float = Field(0.0, ge=0.0, le=1.0)
    author_metadata: dict[str, Any] = Field(default_factory=dict)


class ImageAnalysis(BaseModel):
    """Teammate B's image forensics input."""
    image_fake_score: float = Field(0.0, ge=0.0, le=1.0)
    image_metadata: dict[str, Any] = Field(default_factory=dict)


class SuperAnalyzeRequest(BaseModel):
    """Unified request combining all three analysis pillars."""
    # Pillar 1: Comments (my part)
    comments: list[CommentItem] = Field(default_factory=list)
    post_created_utc: float | None = None
    author_profiles: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Pillar 2: Author reputation (Teammate A)
    author_analysis: AuthorAnalysis = Field(default_factory=AuthorAnalysis)

    # Pillar 3: Image forensics (Teammate B)
    image_analysis: ImageAnalysis = Field(default_factory=ImageAnalysis)


class PillarBreakdown(BaseModel):
    score: float
    weight: float
    details: dict[str, Any] = Field(default_factory=dict)


class SuperAnalyzeResponse(BaseModel):
    final_verdict: str
    confidence_score: float
    detailed_breakdown: dict[str, PillarBreakdown]
    flags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ===========================================================================
# Weights
# ===========================================================================

WEIGHT_COMMENTS = 0.0
WEIGHT_AUTHOR = 0.0
WEIGHT_IMAGE = 0.0


# ===========================================================================
# Verdict Mapping
# ===========================================================================

def map_score_to_verdict(score: float) -> str:
    if score <= 0.20:
        return "Likely Authentic"
    elif score <= 0.45:
        return "Minor Concerns"
    elif score <= 0.70:
        return "Suspicious"
    else:
        return "High Risk"


# ===========================================================================
# Pillar Processors
# ===========================================================================

def process_comments(request: SuperAnalyzeRequest) -> dict[str, Any]:
    """
    Pillar 1: Run our CommentAnalyzer pipeline.
    Returns the network_score and full payload from MainOrchestrator.
    """
    comments = [
        Comment(
            id=c.id,
            parent_id=c.parent_id or "",
            text=c.text,
            author=c.author,
            created_utc=c.created_utc,
        )
        for c in request.comments
    ]

    comment_list = CommentList(comments)
    orchestrator = MainOrchestrator(
        comment_list=comment_list,
        author_profiles=request.author_profiles,
        post_created_utc=request.post_created_utc,
    )

    payload = orchestrator.get_extension_payload()
    return payload


def process_author(author_input: AuthorAnalysis) -> dict[str, Any]:
    """
    Pillar 2: Author Reputation Analysis (Teammate A).

    ┌─────────────────────────────────────────────────────────┐
    │  STUB: Teammate A plugs their logic here.               │
    │                                                         │
    │  Currently returns the score passed in from the request │
    │  body. Replace with actual author analysis function     │
    │  call when ready.                                       │
    │                                                         │
    │  Expected output:                                       │
    │    - "score": float [0.0, 1.0]                          │
    │    - "details": dict with author-specific metadata      │
    └─────────────────────────────────────────────────────────┘
    """
    return {
        "score": author_input.author_reputation_score,
        "details": {
            "source": "teammate_a_module",
            "metadata": author_input.author_metadata,
        },
    }


def process_image(image_input: ImageAnalysis) -> dict[str, Any]:
    """
    Pillar 3: Image Forensics Analysis (Teammate B).

    ┌─────────────────────────────────────────────────────────┐
    │  STUB: Teammate B plugs their logic here.               │
    │                                                         │
    │  Currently returns the score passed in from the request │
    │  body. Replace with actual image forensics function     │
    │  call when ready.                                       │
    │                                                         │
    │  Expected output:                                       │
    │    - "score": float [0.0, 1.0]                          │
    │    - "details": dict with image-specific metadata       │
    └─────────────────────────────────────────────────────────┘
    """
    return {
        "score": image_input.image_fake_score,
        "details": {
            "source": "teammate_b_module",
            "metadata": image_input.image_metadata,
        },
    }


# ===========================================================================
# Endpoints
# ===========================================================================

@app.get("/health")
def health_check():
    """Health check for uptime monitoring."""
    return {"status": "ok", "service": "REDITRUE", "version": "1.0.0"}


@app.post("/api/analyze", response_model=SuperAnalyzeResponse)
def analyze_post(request: SuperAnalyzeRequest):
    """
    Multi-Modal Analysis Endpoint.

    Accepts comment data, author reputation, and image forensics scores.
    Returns a unified trust verdict combining all three pillars.

    Target: < 10 second response time.
    """
    start_time = time.time()

    try:
        # --- Pillar 1: Comment Network Analysis ---
        if request.comments:
            comment_payload = process_comments(request)
            comment_score = comment_payload.get("confidence_score", 0.0)
            comment_details = {
                "network_analysis": comment_payload.get("network_analysis", {}),
                "account_analysis": comment_payload.get("account_analysis", {}),
                "community_debunking": comment_payload.get("community_debunking", {}),
            }
            comment_flags = comment_payload.get("flags", [])
        else:
            comment_score = 0.0
            comment_details = {"note": "No comments provided"}
            comment_flags = []

        # --- Pillar 2: Author Reputation ---
        author_result = process_author(request.author_analysis)
        author_score = author_result["score"]

        # --- Pillar 3: Image Forensics ---
        image_result = process_image(request.image_analysis)
        image_score = image_result["score"]

        # --- Weighted Combination ---
        final_score = (
            (comment_score * WEIGHT_COMMENTS) +
            (author_score * WEIGHT_AUTHOR) +
            (image_score * WEIGHT_IMAGE)
        )
        final_score = min(1.0, max(0.0, final_score))

        verdict = map_score_to_verdict(final_score)

        # --- Build Response ---
        elapsed = round(time.time() - start_time, 3)

        return SuperAnalyzeResponse(
            final_verdict=verdict,
            confidence_score=round(final_score, 4),
            detailed_breakdown={
                "comments_network": PillarBreakdown(
                    score=round(comment_score, 4),
                    weight=WEIGHT_COMMENTS,
                    details=comment_details,
                ),
                "author_reputation": PillarBreakdown(
                    score=round(author_score, 4),
                    weight=WEIGHT_AUTHOR,
                    details=author_result["details"],
                ),
                "image_forensics": PillarBreakdown(
                    score=round(image_score, 4),
                    weight=WEIGHT_IMAGE,
                    details=image_result["details"],
                ),
            },
            flags=comment_flags,
            metadata={
                "processing_time_seconds": elapsed,
                "total_comments_analyzed": len(request.comments),
                "pillars_active": sum([
                    bool(request.comments),
                    author_score > 0.0,
                    image_score > 0.0,
                ]),
            },
        )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Analysis pipeline error: {str(e)}",
        )
