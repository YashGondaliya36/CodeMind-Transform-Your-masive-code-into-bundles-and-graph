"""
app/core/agent/tools.py — Agentic Tool Definitions
===================================================
Three atomic tools the LLM agent can call during its reasoning loop.

Design principle: Each tool does ONE thing precisely. The LLM decides
WHEN to call them. Your Python code actually executes them.

Tools:
  1. search_bundle(query)      → Keyword search across OKF metadata
  2. read_module(filename)     → Read full content of a specific OKF file
  3. follow_import(import_name)→ Resolve an import path to its OKF file
"""

from __future__ import annotations

import re
from typing import Any

from app.core.agent.retriever import retrieve_relevant_files
from app.core.bundle.manager import get_file_detail, get_bundle_path
from app.core.agent.metadata_scanner import scan_all_metadata


# ── Tool 1: Search ────────────────────────────────────────────────────────────

def search_bundle(repo_name: str, query: str, max_results: int = 4) -> dict[str, Any]:
    """
    Search the OKF knowledge bundle by keyword query.
    Returns a list of matching modules with scores and descriptions.
    """
    results = retrieve_relevant_files(
        repo_name=repo_name,
        question=query,
        max_files=max_results,
        min_score=0.0,
    )
    if not results:
        return {"found": False, "message": f"No modules matched query: '{query}'", "results": []}

    return {
        "found": True,
        "results": [
            {
                "filename": detail.filename,
                "title": detail.title,
                "description": detail.description,
                "tags": detail.tags,
                "score": score,
            }
            for detail, score in results
        ]
    }


# ── Tool 2: Read Module ───────────────────────────────────────────────────────

def read_module(repo_name: str, filename: str) -> dict[str, Any]:
    """
    Read the full OKF markdown content + raw source code for a specific module.
    Use this AFTER search_bundle to get deep details about a specific file.
    """
    try:
        detail = get_file_detail(repo_name, filename)
    except Exception:
        return {"found": False, "error": f"Module '{filename}' not found in bundle '{repo_name}'."}

    # Optionally read the raw source code
    raw_code = None
    if detail.resource:
        from app.config import settings
        from app.utils.file_utils import safe_read
        source_path = settings.clone_path / repo_name / detail.resource
        if source_path.exists():
            raw_src = safe_read(source_path)
            if raw_src:
                raw_code = raw_src[:12000]  # cap for token budget

    return {
        "found": True,
        "filename": detail.filename,
        "title": detail.title,
        "description": detail.description,
        "tags": detail.tags,
        "content": detail.content[:8000],  # markdown body
        "source_code": raw_code,
    }


# ── Tool 3: Follow Import ─────────────────────────────────────────────────────

def follow_import(repo_name: str, import_name: str) -> dict[str, Any]:
    """
    Given a Python import path (e.g. 'ltx_core.model.transformer.attention'),
    deterministically locate and read the corresponding OKF module file.
    
    This is the killer OKF-specific tool — no search needed, just direct mapping.
    """
    # Convert import path to a filename slug
    # e.g. 'ltx_core.model.transformer.attention' -> 'attention'
    parts = import_name.strip().split(".")
    search_slug = "-".join(parts[-3:]) if len(parts) >= 3 else "-".join(parts)

    all_meta = scan_all_metadata(repo_name)
    
    # Try to find the best matching file by filename
    best_match = None
    best_score = 0
    for meta in all_meta:
        # Normalize filename for comparison
        normalized = meta.filename.lower().replace("/", "-").replace("_", "-").replace(".md", "")
        
        # Check how many parts of the import path appear in the filename
        hits = sum(1 for part in parts[-3:] if part.replace("_", "-") in normalized)
        if hits > best_score:
            best_score = hits
            best_match = meta

    if not best_match or best_score == 0:
        return {
            "found": False,
            "error": f"Could not resolve import '{import_name}' to any OKF module file."
        }

    return read_module(repo_name, best_match.filename)


# ── Tool 4: Search File Content ─────────────────────────────────────────────────

def search_file_content(repo_name: str, query: str) -> dict[str, Any]:
    """
    Search inside the actual contents of all OKF modules for a specific string.
    Returns lines containing the query to help locate exact function definitions or usages.
    """
    import os
    bundle_path = get_bundle_path(repo_name)
    if not os.path.exists(bundle_path):
        return {"error": f"Bundle path not found: {bundle_path}"}
        
    results = []
    
    # Iterate all .md files
    for root, _, files in os.walk(bundle_path):
        for file in files:
            if not file.endswith(".md"):
                continue
            
            filepath = os.path.join(root, file)
            # Make path relative to bundle root for clean output
            rel_path = os.path.relpath(filepath, bundle_path)
            
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    
                matches = []
                for i, line in enumerate(lines):
                    if query.lower() in line.lower():
                        # Save line number and the stripped text
                        matches.append({"line": i + 1, "text": line.strip()})
                        
                        # Stop after 5 matches per file to prevent blowing up the context window
                        if len(matches) >= 5:
                            break
                            
                if matches:
                    results.append({
                        "filename": rel_path.replace("\\", "/"),
                        "matches": matches
                    })
                    
                # Stop overall after 10 files
                if len(results) >= 10:
                    break
            except Exception:
                pass
                
    if not results:
        return {"found": False, "message": f"No occurrences of '{query}' found in bundle contents."}
        
    return {
        "found": True,
        "summary": f"Found {len(results)} files containing '{query}'.",
        "results": results
    }


# ── Tool Executor ─────────────────────────────────────────────────────────────

TOOL_REGISTRY = {
    "search_bundle": search_bundle,
    "read_module": read_module,
    "follow_import": follow_import,
    "search_file_content": search_file_content,
}


def execute_tool(tool_name: str, repo_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """
    Central dispatcher: validates tool name and executes with provided args.
    Always injects repo_name as the first argument.
    """
    if tool_name not in TOOL_REGISTRY:
        return {"error": f"Unknown tool: '{tool_name}'. Available: {list(TOOL_REGISTRY.keys())}"}

    fn = TOOL_REGISTRY[tool_name]
    try:
        return fn(repo_name=repo_name, **args)
    except Exception as e:
        return {"error": f"Tool '{tool_name}' failed: {str(e)}"}
