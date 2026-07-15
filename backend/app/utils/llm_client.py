"""
app/utils/llm_client.py — Gemini API Wrapper
=============================================
Single place for ALL LLM calls in the project.
Swap the model or provider here without touching any other file.
"""

from google import genai
from google.genai import types

from app.config import settings


def _get_client() -> genai.Client:
    """Lazily configure and return a Gemini GenAI Client instance."""
    if not settings.GEMINI_API_KEY:
        raise ValueError(
            "GEMINI_API_KEY is not set. "
            "Copy .env.example → .env and add your key."
        )
    return genai.Client(api_key=settings.GEMINI_API_KEY)


def generate_text(prompt: str, temperature: float = 0.2) -> tuple[str, int, int]:
    """
    Send a prompt to Gemini and return the text + token breakdown.

    Args:
        prompt:      The full prompt string.
        temperature: Lower = more deterministic. Use 0.2 for code summaries.

    Returns:
        Tuple of (answer_text, input_tokens, output_tokens).
        Token counts come from usage_metadata — no extra API call needed.

    Raises:
        ValueError: If GEMINI_API_KEY is missing.
        RuntimeError: If the API call fails.
    """
    try:
        client = _get_client()
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=temperature),
        )
        text = response.text.strip()
        meta = response.usage_metadata
        input_tokens = getattr(meta, "prompt_token_count", 0) or 0
        output_tokens = getattr(meta, "candidates_token_count", 0) or 0
        return text, input_tokens, output_tokens
    except Exception as e:
        raise RuntimeError(f"LLM call failed: {e}") from e


def count_tokens(text: str) -> int:
    """
    Estimate token count for a given text string.
    NOTE: Prefer using usage_metadata from generate_text() instead of calling
    this directly — it avoids an extra API round-trip.

    Returns:
        Approximate token count (rough estimate: 1 token ~= 4 chars).
    """
    # Rough estimation — no extra API call
    return len(text) // 4


def check_connectivity() -> dict:
    """
    Ping the Gemini API with a minimal prompt to verify connectivity.
    Used by the /health endpoint.

    Returns:
        {"status": "ok", "model": "gemini-1.5-flash"} on success.
        {"status": "error", "message": "..."} on failure.
    """
    try:
        response_text, _, _ = generate_text("Say 'ok' and nothing else.", temperature=0.0)
        return {
            "status": "ok",
            "model": settings.GEMINI_MODEL,
            "response_preview": response_text[:50],
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
