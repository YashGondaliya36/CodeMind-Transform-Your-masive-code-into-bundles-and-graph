"""
app/core/agent/agentic_loop.py — ReAct Agent Execution Loop
=============================================================
Implements the core Reasoning + Acting (ReAct) loop using
Gemini's native function calling via the google-genai SDK.

The LLM is given 3 tools and allowed to reason and act in multiple
turns until it reaches a confident final answer.

Safety features:
  - MAX_STEPS circuit breaker prevents infinite loops
  - Tool execution is fully sandboxed in Python (LLM only generates intents)
  - Token count tracked across all turns
"""

from __future__ import annotations

import json
from typing import Any

from google import genai
from google.genai import types

from app.config import settings
from app.core.agent.tools import execute_tool

MAX_STEPS = 5  # Circuit breaker: max tool calls before forcing a final answer

# ── Gemini Function Declarations ──────────────────────────────────────────────

_TOOL_DECLARATIONS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="search_bundle",
        description=(
            "Search the codebase knowledge bundle by keyword. "
            "Use this to find which modules are relevant to a concept or topic. "
            "Returns a ranked list of matching files with titles, descriptions, and scores."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query": types.Schema(
                    type=types.Type.STRING,
                    description="Keywords or a short phrase describing what to search for."
                ),
                "max_results": types.Schema(
                    type=types.Type.INTEGER,
                    description="Max number of results to return. Default is 4."
                ),
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="read_module",
        description=(
            "Read the full OKF knowledge file for a specific module, including "
            "its raw source code. Use this AFTER search_bundle to get deep details "
            "about a specific file. Requires the exact filename from search results."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "filename": types.Schema(
                    type=types.Type.STRING,
                    description="The exact filename of the OKF module (e.g. 'modules/auth-router.md')."
                ),
            },
            required=["filename"],
        ),
    ),
    types.FunctionDeclaration(
        name="follow_import",
        description=(
            "Given a Python import path found in source code "
            "(e.g. 'ltx_core.model.transformer.attention'), find and read the "
            "corresponding OKF knowledge file. Use this to trace dependencies "
            "without needing to search again."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "import_name": types.Schema(
                    type=types.Type.STRING,
                    description="The full Python import path to resolve."
                ),
            },
            required=["import_name"],
        ),
    ),
    types.FunctionDeclaration(
        name="search_file_content",
        description=(
            "Search for an exact string (like a function name, class name, or variable) "
            "inside all markdown files in the bundle. Returns a list of files and line numbers "
            "where the text appears. Use this to quickly locate where specific code is used or defined."
        ),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "query": types.Schema(
                    type=types.Type.STRING,
                    description="The exact text to search for inside the file contents."
                ),
            },
            required=["query"],
        ),
    ),
])


# ── System Prompt ─────────────────────────────────────────────────────────────

def _build_system_prompt(repo_name: str) -> str:
    return f"""You are CodeMind, an expert AI developer assistant for the '{repo_name}' codebase.

You have access to a structured knowledge base (OKF format) containing detailed documentation for every module in this project. You can use your tools to navigate it like a real developer would.

## Your Tools
- **search_bundle**: Find relevant modules by keyword. Use this first when you need to locate a concept.
- **read_module**: Read the full documentation + source code of a specific module. Use after search_bundle.
- **follow_import**: Trace a specific Python import to its module. Use when you see an import and need to understand it.
- **search_file_content**: Find exact string matches (e.g. a function name) across all files. Use when you know what symbol you are looking for but don't know which file it is in.

## Rules
1. ONLY call a tool when you genuinely need more information. Do NOT call tools for general questions you already know the answer to.
2. NEVER call the same tool with the same arguments twice.
3. After at most {MAX_STEPS} tool calls, synthesize your final answer based on what you have found.
4. Be precise: reference exact function names, class names, and file paths in your final answer.
5. If you cannot find enough context after your searches, say so clearly — do NOT hallucinate.
6. **CHAIN OF THOUGHT REQUIRED**: Before outputting a tool call or your final answer, you MUST write down your thought process inside `<thought>...</thought>` tags. 
   - Example: `<thought>I need to find where the auth logic is. I'll use search_bundle.</thought>`

## Answer Format
Provide your final answer in clear markdown with headers and code blocks where helpful. DO NOT include `<thought>` blocks in your final text answer (only use them when thinking before calling a tool)."""


# ── Main Loop ─────────────────────────────────────────────────────────────────

def run_agentic_loop(
    repo_name: str,
    question: str,
    initial_context: str | None = None,
) -> tuple[str, list[dict[str, Any]], int, int]:
    """
    Run the full ReAct agentic reasoning loop.

    Args:
        repo_name: The OKF bundle to query against.
        question:  The developer's question.

    Returns:
        Tuple of (final_answer, tool_calls_log, tokens_in, tokens_out).
    """
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    system_prompt = _build_system_prompt(repo_name)
    
    user_prompt = question
    if initial_context:
        user_prompt = f"Initial context retrieved from search:\n{initial_context}\n\nQuestion: {question}"

    # Conversation history (multi-turn)
    conversation: list[types.Content] = [
        types.Content(
            role="user",
            parts=[types.Part(text=user_prompt)]
        )
    ]
    
    tool_calls_log: list[dict[str, Any]] = []
    tokens_in = 0
    tokens_out = 0
    steps = 0
    
    while steps < MAX_STEPS:
        # Send the current conversation to the LLM
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=conversation,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[_TOOL_DECLARATIONS],
                temperature=0.1,
            ),
        )
        
        # Track token usage
        if response.usage_metadata:
            tokens_in += getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            tokens_out += getattr(response.usage_metadata, "candidates_token_count", 0) or 0
        
        candidate = response.candidates[0]
        response_content = candidate.content
        
        # Add the model's response to conversation history
        conversation.append(response_content)
        
        # Check if the model wants to call a tool
        function_calls = [
            part.function_call
            for part in response_content.parts
            if part.function_call is not None
        ]
        
        if not function_calls:
            # Model gave a final text answer — we are done!
            import re
            final_text = "".join(
                part.text for part in response_content.parts if part.text
            )
            final_text = re.sub(r'<thought>.*?</thought>', '', final_text, flags=re.DOTALL).strip()
            return final_text, tool_calls_log, tokens_in, tokens_out
        
        # Execute each tool call and collect results
        tool_results: list[types.Part] = []
        for fc in function_calls:
            steps += 1
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}
            
            # Log the tool call for transparency
            tool_calls_log.append({"tool": tool_name, "args": tool_args})
            
            # Execute tool in Python (sandboxed)
            result = execute_tool(tool_name, repo_name, tool_args)
            
            # Format the result as a function response for Gemini
            tool_results.append(
                types.Part.from_function_response(
                    name=tool_name,
                    response=result,
                )
            )
            
            if steps >= MAX_STEPS:
                break
        
        # Feed tool results back into the conversation
        conversation.append(
            types.Content(role="tool", parts=tool_results)
        )
    
    # ── Circuit Breaker: Forced Final Answer ──────────────────────────────────
    # If we hit MAX_STEPS, force the LLM to summarize what it found
    conversation.append(
        types.Content(
            role="user",
            parts=[types.Part(text=(
                "You have used the maximum number of tool calls. "
                "Please synthesize a final answer based on everything you have found so far."
            ))]
        )
    )
    
    final_response = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents=conversation,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.1,
        ),
    )
    
    if final_response.usage_metadata:
        tokens_in += getattr(final_response.usage_metadata, "prompt_token_count", 0) or 0
        tokens_out += getattr(final_response.usage_metadata, "candidates_token_count", 0) or 0
        
    import re
    final_text = "".join(
        part.text for part in final_response.candidates[0].content.parts if part.text
    )
    final_text = re.sub(r'<thought>.*?</thought>', '', final_text, flags=re.DOTALL).strip()
    return final_text, tool_calls_log, tokens_in, tokens_out


# ── Streaming Version ─────────────────────────────────────────────────────────

async def run_agentic_loop_streaming(repo_name: str, question: str, initial_context: str | None = None):
    """
    Async generator version of run_agentic_loop.
    Yields SSE-compatible event dicts as the agent reasons and calls tools.
    The /chat/stream endpoint uses this to push live updates to the UI.
    """
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    system_prompt = _build_system_prompt(repo_name)
    user_prompt = question
    if initial_context:
        user_prompt = f"Initial context retrieved from search:\n{initial_context}\n\nQuestion: {question}"

    conversation: list[types.Content] = [
        types.Content(role="user", parts=[types.Part(text=user_prompt)])
    ]

    steps = 0

    while steps < MAX_STEPS:
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=conversation,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=[_TOOL_DECLARATIONS],
                temperature=0.1,
            ),
        )

        candidate = response.candidates[0]
        response_content = candidate.content
        conversation.append(response_content)

        function_calls = [
            part.function_call
            for part in response_content.parts
            if part.function_call is not None
        ]

        if not function_calls:
            # Model gave final text answer — yield it and stop
            import re
            final_text = "".join(p.text for p in response_content.parts if p.text)
            final_text = re.sub(r'<thought>.*?</thought>', '', final_text, flags=re.DOTALL).strip()
            yield {"type": "agent_answer", "message": final_text}
            return

        # Yield each tool call as an event before executing it
        tool_results: list[types.Part] = []
        for fc in function_calls:
            steps += 1
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}

            # Emit tool call event
            yield {
                "type": "tool_call",
                "tool": tool_name,
                "args": tool_args,
                "message": _tool_call_label(tool_name, tool_args),
                "step": steps,
            }

            # Execute and emit result
            result = execute_tool(tool_name, repo_name, tool_args)
            found = result.get("found", True)
            yield {
                "type": "tool_result",
                "tool": tool_name,
                "found": found,
                "message": f"{'Found' if found else 'Not found'}: {_tool_result_summary(tool_name, result)}",
                "step": steps,
            }

            tool_results.append(
                types.Part.from_function_response(name=tool_name, response=result)
            )

            if steps >= MAX_STEPS:
                break

        conversation.append(types.Content(role="tool", parts=tool_results))

    # Circuit breaker hit — emit event and force final answer
    yield {"type": "thinking", "message": "Reached step limit — synthesizing final answer..."}


def _tool_call_label(tool_name: str, args: dict) -> str:
    """Generate a human-readable label for a tool call."""
    if tool_name == "search_bundle":
        return f'Searching: "{args.get("query", "...")}"'
    elif tool_name == "read_module":
        fname = args.get("filename", "...").split("/")[-1].replace(".md", "")
        return f'Reading: {fname}'
    elif tool_name == "follow_import":
        return f'Following import: {args.get("import_name", "...")}'
    return f'Calling: {tool_name}'


def _tool_result_summary(tool_name: str, result: dict) -> str:
    """Generate a brief summary of a tool result."""
    if not result.get("found", True):
        return result.get("error", "not found")
    if tool_name == "search_bundle":
        count = len(result.get("results", []))
        return f"{count} module(s) matched"
    elif tool_name in ("read_module", "follow_import"):
        return result.get("title", result.get("filename", "module read"))
    return "success"
