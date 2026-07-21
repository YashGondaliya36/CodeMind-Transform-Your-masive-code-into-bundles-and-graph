"""
app/core/agent/responder.py — Context Assembly + LLM Response
==============================================================
Final step of the agent pipeline. Now with Intent-First Routing:

  PATH 1 (DIRECT):  General/overview question → Use index.md immediately
  PATH 2 (RAG):     Specific keyword question → 1-shot retrieval (default)
  PATH 3 (AGENTIC): Relational/complex question → Full ReAct tool loop

Tools are ONLY invoked on Path 3 or when Path 2 retrieval confidence is too low.
"""

from __future__ import annotations

from app.core.agent.retriever import retrieve_relevant_files
from app.core.agent.agent_router import classify_query, should_escalate_to_agentic, RoutePath
from app.core.agent.agentic_loop import run_agentic_loop
from app.config import settings
from app.models.chat import ChatRequest, ChatResponse, SourceFile
from app.utils.llm_client import generate_text, count_tokens


def answer_question(request: ChatRequest) -> ChatResponse:
    """
    Core agent entrypoint — routes the request to the optimal strategy.
    """
    from app.core.agent.metadata_scanner import scan_all_metadata
    all_meta = scan_all_metadata(request.repo_name)
    files_scanned = len(all_meta)

    # ── Intent Classification (Zero Cost — pure regex) ─────────────────────────
    route = classify_query(request.question)

    # ── PATH 1: Direct Overview (cheapest — only uses index.md) ───────────────
    if route == RoutePath.DIRECT:
        return _answer_direct(request, files_scanned)

    # ── PATH 2: Standard RAG (1-shot retrieval) ────────────────────────────────
    if route == RoutePath.RAG:
        retrieved = retrieve_relevant_files(
            repo_name=request.repo_name,
            question=request.question,
            max_files=request.max_files,
            min_score=0.0,
        )
        scores = [score for _, score in retrieved]

        # Auto-escalate if retrieval confidence is too low
        if should_escalate_to_agentic(scores):
            route = RoutePath.AGENTIC
            # Save the retrieved files to pass into the Agentic Loop
            initial_context = _build_context_block(retrieved, request.repo_name)
        else:
            return _answer_from_rag(request, retrieved, files_scanned)

    # ── PATH 3: Agentic Loop (only when needed) ────────────────────────────────
    if route == RoutePath.AGENTIC:
        # Pass the context block if we arrived here via RAG escalation
        return _answer_agentically(request, files_scanned, initial_context=locals().get("initial_context"))

    # Fallback (should never reach here)
    return _answer_direct(request, files_scanned)


# ── Path Handler: Direct (index.md only) ─────────────────────────────────────

def _answer_direct(request: ChatRequest, files_scanned: int) -> ChatResponse:
    """Path 1: Use master index.md for general overview questions."""
    from app.core.bundle.manager import get_file_detail
    try:
        index = get_file_detail(request.repo_name, "index.md")
        context = f"--- Project Index ---\n{index.content[:10000]}"
    except Exception:
        context = "No index file available."

    prompt = _build_answer_prompt(request.question, request.repo_name, context)
    answer, tok_in, tok_out = generate_text(prompt, temperature=0.2)

    return ChatResponse(
        answer=answer,
        sources_used=[SourceFile(filename="index.md", title="Project Index", relevance_score=1.0, tags=["overview"])],
        files_scanned=files_scanned,
        tokens_input=tok_in,
        tokens_output=tok_out,
        tokens_used=tok_in + tok_out,
        repo_name=request.repo_name,
        question=request.question,
    )


# ── Path Handler: Standard RAG (1-shot) ───────────────────────────────────────

def _answer_from_rag(request: ChatRequest, retrieved: list, files_scanned: int) -> ChatResponse:
    """Path 2: Standard 1-shot retrieval + answer."""
    if not retrieved:
        return _answer_agentically(request, files_scanned)

    context_block = _build_context_block(retrieved, request.repo_name)
    prompt = _build_answer_prompt(request.question, request.repo_name, context_block)
    answer, tok_in, tok_out = generate_text(prompt, temperature=0.3)

    sources = [
        SourceFile(filename=d.filename, title=d.title, relevance_score=s, tags=d.tags)
        for d, s in retrieved
    ]
    return ChatResponse(
        answer=answer, sources_used=sources, files_scanned=files_scanned,
        tokens_input=tok_in, tokens_output=tok_out, tokens_used=tok_in + tok_out,
        repo_name=request.repo_name, question=request.question,
    )


# ── Path Handler: Agentic Loop ────────────────────────────────────────────────

def _answer_agentically(request: ChatRequest, files_scanned: int, initial_context: str | None = None) -> ChatResponse:
    """Path 3: Full ReAct tool loop — only activated when truly needed."""
    answer, tool_calls_log, tokens_in, tokens_out = run_agentic_loop(
        repo_name=request.repo_name,
        question=request.question,
        initial_context=initial_context,
    )

    # Build source list from tool call log (which files were read)
    sources = []
    seen = set()
    for call in tool_calls_log:
        if call["tool"] in ("read_module", "follow_import"):
            fname = call["args"].get("filename") or call["args"].get("import_name", "unknown")
            if fname not in seen:
                sources.append(SourceFile(filename=fname, title=fname, relevance_score=1.0, tags=["agentic"]))
                seen.add(fname)

    return ChatResponse(
        answer=answer, sources_used=sources, files_scanned=files_scanned,
        tokens_input=tokens_in, tokens_output=tokens_out, tokens_used=tokens_in + tokens_out,
        repo_name=request.repo_name, question=request.question,
    )


def _build_context_block(
    retrieved: list[tuple],
    repo_name: str,
) -> str:
    """
    Format the retrieved OKF files into a clean context block for the prompt.
    Each file is clearly delimited so the LLM can reference them separately.
    """
    blocks = []
    for idx, (detail, score) in enumerate(retrieved, start=1):
        # Increased to ~15000 chars to avoid aggressively truncating deep technical details
        markdown_body = f"{detail.content[:15000]}"
        
        # Optionally inject the RAW source code so the LLM can read exact math/logic 
        # (which might have been skipped by the high-level markdown summarizer)
        raw_code_block = ""
        if detail.resource:
            from pathlib import Path
            from app.utils.file_utils import safe_read
            source_path = settings.clone_path / repo_name / detail.resource
            if source_path.exists():
                raw_code = safe_read(source_path)
                if raw_code:
                    raw_code_block = f"\n\n--- ORIGINAL SOURCE CODE ---\n```\n{raw_code[:15000]}\n```\n"

        block = (
            f"--- Knowledge File {idx}: {detail.title} ---\n"
            f"File: {detail.filename}\n"
            f"Tags: {', '.join(detail.tags)}\n"
            f"Relevance: {score:.2f}\n\n"
            f"{markdown_body}"
            f"{raw_code_block}"
        )
        blocks.append(block)
    return "\n\n".join(blocks)


def _build_answer_prompt(question: str, repo_name: str, context: str) -> str:
    """Build the final LLM prompt with injected OKF context."""
    return f"""You are CodeMind, an expert AI developer assistant with deep knowledge of the '{repo_name}' codebase.

You have been given structured knowledge files (OKF format) that describe specific modules and concepts in this codebase. Use ONLY this provided context to answer the question. If the answer is not covered in the context, say so clearly — do NOT hallucinate.

## Knowledge Context (from OKF Bundle)

{context}

---

## Developer's Question

{question}

---

## Instructions
- Answer clearly and directly.
- Reference specific function names, class names, or file paths from the context when relevant.
- Use markdown formatting (headers, code blocks, bullet points) for clarity.
- If the context is insufficient, say: "The available knowledge files don't fully cover this. Based on what I can see: [partial answer]"
- Do NOT make up information that isn't in the context.

## Answer:
"""


def _answer_without_context(question: str, repo_name: str) -> str:
    """Fallback: answer when no relevant OKF files were found."""
    prompt = f"""You are CodeMind, an AI developer assistant for the '{repo_name}' codebase.

No relevant knowledge files were found for this question in the OKF bundle.
This may mean:
1. The relevant module hasn't been analysed yet
2. The question is about something not in the codebase
3. The keywords in the question don't match the current bundle's tags

Question: {question}

Please acknowledge that the knowledge base doesn't have sufficient context for this specific question, and suggest what the user could do (e.g., re-run analysis, check the bundle explorer, or rephrase with different keywords).
"""
    text, _, _ = generate_text(prompt, temperature=0.1)
    return text

