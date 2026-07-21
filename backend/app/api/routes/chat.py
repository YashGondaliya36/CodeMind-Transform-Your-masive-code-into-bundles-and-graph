"""
app/api/routes/chat.py — Chat Agent Endpoint
=============================================
POST /chat/ask    — Standard JSON response
GET  /chat/stream — Server-Sent Events stream (live agent thinking)
"""

import json
import asyncio
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.core.agent.responder import answer_question
from app.core.agent.agent_router import classify_query, should_escalate_to_agentic, RoutePath
from app.core.bundle.manager import bundle_exists
from app.models.chat import ChatRequest, ChatResponse

router = APIRouter()


@router.post(
    "/ask",
    response_model=ChatResponse,
    summary="Ask a question about a codebase",
)
async def ask(request: ChatRequest):
    """
    Ask a natural language question about any analyzed repository.
    Returns a complete JSON response. For streaming, use GET /chat/stream.
    """
    if not bundle_exists(request.repo_name):
        raise HTTPException(
            status_code=404,
            detail=(
                f"No OKF bundle found for repo '{request.repo_name}'. "
                f"Run POST /repo/analyze first to generate the knowledge bundle."
            ),
        )

    try:
        return answer_question(request)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"LLM error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent error: {e}")


@router.post(
    "/stream",
    summary="Ask a question with live agent thinking stream (SSE)",
)
async def ask_stream(request: ChatRequest):
    """
    Streams the agent's thinking process as Server-Sent Events (SSE).
    Each event describes what the agent is doing (routing, searching, reading, answering).
    The final event contains the complete ChatResponse as JSON.
    """
    if not bundle_exists(request.repo_name):
        raise HTTPException(status_code=404, detail=f"No OKF bundle for '{request.repo_name}'")

    async def event_stream():
        def emit(event_type: str, payload: dict) -> str:
            data = json.dumps({"type": event_type, **payload})
            return f"data: {data}\n\n"

        try:
            # ── Step 1: Classify intent ────────────────────────────────────────
            route = classify_query(request.question)
            route_labels = {
                RoutePath.DIRECT: "overview",
                RoutePath.RAG: "keyword search",
                RoutePath.AGENTIC: "deep reasoning",
            }
            yield emit("routing", {
                "path": route.value,
                "label": route_labels[route],
                "message": f"Classified as: {route_labels[route].upper()}"
            })
            await asyncio.sleep(0.05)

            from app.core.agent.metadata_scanner import scan_all_metadata
            all_meta = scan_all_metadata(request.repo_name)
            files_scanned = len(all_meta)

            # ── PATH 1: DIRECT ─────────────────────────────────────────────────
            if route == RoutePath.DIRECT:
                yield emit("thinking", {"message": "Reading project index for overview..."})
                await asyncio.sleep(0.05)
                response = answer_question(request)
                yield emit("done", {"response": response.model_dump()})
                return

            # ── PATH 2: RAG ────────────────────────────────────────────────────
            if route == RoutePath.RAG:
                yield emit("thinking", {"message": f"Scanning {files_scanned} knowledge files..."})
                await asyncio.sleep(0.05)

                from app.core.agent.retriever import retrieve_relevant_files
                retrieved = retrieve_relevant_files(
                    repo_name=request.repo_name,
                    question=request.question,
                    max_files=request.max_files,
                    min_score=0.0,
                )
                scores = [s for _, s in retrieved]

                if retrieved:
                    for detail, score in retrieved:
                        yield emit("file_found", {
                            "filename": detail.filename,
                            "title": detail.title,
                            "score": round(score, 3),
                            "message": f"Found: {detail.title} ({round(score*100)}% match)"
                        })
                        await asyncio.sleep(0.05)

                if should_escalate_to_agentic(scores):
                    route = RoutePath.AGENTIC
                    yield emit("escalating", {
                        "message": "Low confidence — escalating to Agent Loop..."
                    })
                    await asyncio.sleep(0.05)
                    from app.core.agent.responder import _build_context_block
                    initial_context = _build_context_block(retrieved, request.repo_name)
                else:
                    yield emit("thinking", {"message": "Synthesizing answer..."})
                    await asyncio.sleep(0.05)
                    response = answer_question(request)
                    yield emit("done", {"response": response.model_dump()})
                    return

            # ── PATH 3: AGENTIC ────────────────────────────────────────────────
            if route == RoutePath.AGENTIC:
                yield emit("thinking", {"message": "Entering Agent Reasoning Loop..."})
                await asyncio.sleep(0.05)

                # Stream tool calls from the agentic loop
                from app.core.agent.agentic_loop import run_agentic_loop_streaming
                
                async for event in run_agentic_loop_streaming(request.repo_name, request.question, initial_context=locals().get("initial_context")):
                    yield emit(event["type"], event)
                    await asyncio.sleep(0.05)

                # Get final complete response
                response = answer_question(request)
                yield emit("done", {"response": response.model_dump()})

        except Exception as e:
            yield emit("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
