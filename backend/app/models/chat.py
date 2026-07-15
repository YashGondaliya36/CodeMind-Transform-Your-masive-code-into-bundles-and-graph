"""
app/models/chat.py — Chat Agent Pydantic Schemas
=================================================
Request and response models for POST /chat/ask.
"""

from typing import Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Body for POST /chat/ask"""

    repo_name: str = Field(
        ...,
        description="The repo_name slug whose OKF bundle to query against.",
        examples=["fastapi-core"],
    )
    question: str = Field(
        ...,
        description="The developer's natural language question about the codebase.",
        examples=["How does user authentication work?"],
        min_length=5,
        max_length=2000,
    )
    max_files: int = Field(
        default=5,
        ge=1,
        le=15,
        description="Maximum number of OKF files to inject into context (cost control).",
    )


class SourceFile(BaseModel):
    """
    Metadata about an OKF file that was used to generate the answer.
    Shown to the user for full transparency (no black-box answers).
    """

    filename: str
    title: str
    relevance_score: float = Field(ge=0.0, le=1.0)
    tags: list[str] = []


class ChatResponse(BaseModel):
    """Response for POST /chat/ask"""

    answer: str                             # The LLM's answer
    sources_used: list[SourceFile]          # Which OKF files were injected
    files_scanned: int                      # Total frontmatters scanned (for UI display)
    tokens_input: Optional[int] = None      # Prompt / input tokens consumed
    tokens_output: Optional[int] = None     # Completion / output tokens generated
    tokens_used: Optional[int] = None       # Total (kept for backwards compat)
    repo_name: str
    question: str                           # Echo back for frontend convenience
