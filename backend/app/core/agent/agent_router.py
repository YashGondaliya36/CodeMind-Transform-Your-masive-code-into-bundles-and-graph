"""
app/core/agent/agent_router.py — Intent-First Query Router
===========================================================
Classifies any user question into one of three routing paths
BEFORE performing any expensive work.

Paths:
  PATH_1_DIRECT   → General/overview question → Use index.md only (cheapest)
  PATH_2_RAG      → Specific keyword question → 1-shot retrieval (current behavior)
  PATH_3_AGENTIC  → Relational/complex question → Full agent tool loop (most powerful)

Design principle: The VAST majority of queries (Path 1 + 2) should
never enter the agentic loop. Agentify ONLY when required.
"""

from __future__ import annotations

from enum import Enum
import json
from google import genai
from google.genai import types

from app.config import settings

class RoutePath(str, Enum):
    DIRECT = "direct"     # Use index.md, no search
    RAG = "rag"           # Standard 1-shot keyword retrieval
    AGENTIC = "agentic"   # Full multi-step tool loop


def classify_query(question: str) -> RoutePath:
    """
    Classify a user question into the cheapest routing path that can answer it
    using a zero-shot LLM classification.

    Args:
        question: The raw user question string.

    Returns:
        RoutePath enum value (DIRECT, RAG, or AGENTIC).
    """
    try:
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        
        system_instruction = (
            "You are an intent router for a code assistant. Classify the user's question into one of three routes:\n"
            "1. 'DIRECT': High-level overview questions like 'What is this project?', 'Give me a summary', 'List the architecture'.\n"
            "2. 'AGENTIC': Complex, multi-hop reasoning questions like 'How does X call Y?', 'Trace the flow of...', 'Where is X imported?'.\n"
            "3. 'RAG': Specific keyword or general code questions that don't fit the above two.\n"
            "Output ONLY valid JSON containing a single key 'route' with the uppercase string value."
        )

        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=question,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
                response_mime_type="application/json",
            )
        )
        
        # Parse response
        text = response.text or "{}"
        data = json.loads(text)
        route_str = data.get("route", "").upper()
        
        if route_str == "DIRECT":
            return RoutePath.DIRECT
        if route_str == "AGENTIC":
            return RoutePath.AGENTIC
        
        return RoutePath.RAG
        
    except Exception as e:
        print(f"[Router Warning] LLM routing failed: {e}. Falling back to RAG.")
        # Fallback to standard RAG if the API call fails
        return RoutePath.RAG


def should_escalate_to_agentic(retrieval_scores: list[float], threshold: float = 0.15) -> bool:
    """
    After a standard RAG retrieval, check if results are too weak.
    If all scores are below threshold, escalate to agentic loop for retry.

    Args:
        retrieval_scores: List of relevance scores from the initial search.
        threshold:        Minimum acceptable score for a confident retrieval.

    Returns:
        True if the agentic loop should be used to find better context.
    """
    if not retrieval_scores:
        return True  # Nothing was found — definitely escalate
    return max(retrieval_scores) < threshold
