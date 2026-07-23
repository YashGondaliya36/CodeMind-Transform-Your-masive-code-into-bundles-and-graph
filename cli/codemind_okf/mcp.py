"""
codemind_okf/mcp.py — Model Context Protocol (MCP) Server
=========================================================
Implements Anthropic's Model Context Protocol (MCP) over STDIO.
Compatible with Cursor, Claude Desktop, Antigravity, and Zed.

Exposes 5 core tools:
  1. list_bundles()             — List all available OKF knowledge bundles
  2. get_project_index(repo)    — Read master architecture index.md
  3. search_bundle(repo, query) — Rank & retrieve relevant OKF modules
  4. read_module(repo, file)    — Read module YAML frontmatter + AST details
  5. trace_dependencies(repo)   — Map cross-module dependencies
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
import frontmatter as fm

# JSON-RPC 2.0 helper constants
JSONRPC_VERSION = "2.0"


def find_okf_root(repo_name_or_path: str | None = None) -> Path | None:
    """Find the .okf directory for a given repo name or current directory."""
    if repo_name_or_path:
        p = Path(repo_name_or_path)
        if (p / ".okf").is_dir():
            return p / ".okf"
        if p.name == ".okf" and p.is_dir():
            return p
        # Check backend okf_bundles directory
        okf_bundles = Path("okf_bundles") / repo_name_or_path
        if okf_bundles.is_dir():
            return okf_bundles

    # Default: search in current working directory or parents
    cwd = Path.cwd()
    for parent in [cwd] + list(cwd.parents):
        if (parent / ".okf").is_dir():
            return parent / ".okf"

    return None


# ── Core Tool Handlers ────────────────────────────────────────────────────────

def tool_list_bundles() -> str:
    """List all available local OKF knowledge bundles."""
    bundles = []

    # Check cwd/.okf
    cwd_okf = Path.cwd() / ".okf"
    if cwd_okf.is_dir():
        bundles.append({
            "name": Path.cwd().name,
            "path": str(cwd_okf.resolve()),
            "type": "local_project",
        })

    # Check okf_bundles dir
    bundles_dir = Path("okf_bundles")
    if bundles_dir.is_dir():
        for item in bundles_dir.iterdir():
            if item.is_dir():
                bundles.append({
                    "name": item.name,
                    "path": str(item.resolve()),
                    "type": "stored_bundle",
                })

    if not bundles:
        return "No OKF bundles found. Run `codemind index .` to generate one."

    return json.dumps(bundles, indent=2)


def tool_get_project_index(repo_name: str | None = None) -> str:
    """Fetch the master architecture index.md for a project."""
    root = find_okf_root(repo_name)
    if not root:
        return f"Error: No OKF bundle found for '{repo_name or Path.cwd().name}'. Run `codemind index .` first."

    index_file = root / "index.md"
    if not index_file.exists():
        return f"Error: index.md missing in {root}."

    return index_file.read_text(encoding="utf-8", errors="replace")


def tool_search_bundle(query: str, repo_name: str | None = None, max_results: int = 5) -> str:
    """Perform relevance scoring search across all OKF modules."""
    root = find_okf_root(repo_name)
    if not root:
        return f"Error: No OKF bundle found for '{repo_name or Path.cwd().name}'."

    modules_dir = root / "modules"
    if not modules_dir.is_dir():
        return f"Error: No modules directory in {root}."

    # Stop words (English grammar noise words only — keeping programming terms like 'get', 'code', 'file')
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "how", "what", "where", "when", "why", "who", "which", "can", "could",
        "do", "does", "did", "will", "would", "shall", "should", "in", "on",
        "at", "to", "for", "of", "and", "or", "not", "with", "from", "by",
    }

    keywords = {
        t.lower() for t in re.findall(r"\b\w+\b", query)
        if t.lower() not in stop_words and len(t) > 2
    }

    if not keywords:
        return "Query too short or contains only stop words."

    results = []

    for md_path in modules_dir.glob("*.md"):
        try:
            raw = md_path.read_text(encoding="utf-8", errors="replace")
            post = fm.loads(raw)
            meta = post.metadata

            title = str(meta.get("title", "")).lower()
            tags = [str(t).lower() for t in meta.get("tags", [])]
            key_funcs = [str(f).lower() for f in meta.get("key_functions", [])]
            desc = str(meta.get("description", "")).lower()
            resource = str(meta.get("resource", "")).lower()

            score = 0.0
            for kw in keywords:
                # ── 1. Function & Class match (Highest Weight) ──
                for fn in key_funcs:
                    if kw == fn:
                        score += 4.0
                    elif kw in fn or fn in kw:
                        score += 3.0  # Dynamic sub-word match (e.g. 'auth' in 'authenticate_user')

                # ── 2. Title match ──
                if kw in title:
                    score += 3.0
                elif any(kw in word for word in title.split()):
                    score += 2.0

                # ── 3. Dynamic Tag match ──
                for tag in tags:
                    if kw == tag:
                        score += 2.5
                    elif kw in tag or tag in kw:
                        score += 1.5  # Dynamic tag sub-word match

                # ── 4. Description match ──
                if kw in desc:
                    score += 1.5

                # ── 5. Source path match ──
                if kw in resource:
                    score += 1.0

            if score > 0:
                results.append({
                    "score": round(score, 2),
                    "filename": md_path.name,
                    "title": meta.get("title", md_path.stem),
                    "type": meta.get("type", "module"),
                    "resource": meta.get("resource", ""),
                    "description": meta.get("description", ""),
                    "key_functions": meta.get("key_functions", []),
                    "tags": meta.get("tags", []),
                })
        except Exception:
            continue

    results.sort(key=lambda x: x["score"], reverse=True)
    top_results = results[:max_results]

    if not top_results:
        # Dynamic Fallback: if zero keywords matched, return the top general modules so AI is never stuck
        fallback_results = []
        for md_path in list(modules_dir.glob("*.md"))[:max_results]:
            try:
                raw = md_path.read_text(encoding="utf-8", errors="replace")
                post = fm.loads(raw)
                meta = post.metadata
                fallback_results.append({
                    "score": 0.1,
                    "filename": md_path.name,
                    "title": meta.get("title", md_path.stem),
                    "type": meta.get("type", "module"),
                    "resource": meta.get("resource", ""),
                    "description": meta.get("description", ""),
                    "key_functions": meta.get("key_functions", []),
                    "tags": meta.get("tags", []),
                })
            except Exception:
                continue

        return json.dumps({
            "query": query,
            "keywords_matched": list(keywords),
            "total_matches": 0,
            "fallback_used": True,
            "note": "No exact keyword matches found. Returning primary project modules for context.",
            "results": fallback_results,
        }, indent=2)

    return json.dumps({
        "query": query,
        "keywords_matched": list(keywords),
        "total_matches": len(results),
        "results": top_results,
    }, indent=2)


def tool_read_module(filename: str, repo_name: str | None = None) -> str:
    """Read a specific OKF module file."""
    root = find_okf_root(repo_name)
    if not root:
        return f"Error: No OKF bundle found."

    # Allow passing filename with or without 'modules/' prefix
    fname = filename.replace("modules/", "").replace("modules\\", "")
    target = root / "modules" / fname

    if not target.exists():
        # Try finding by title or matching slug
        matches = list((root / "modules").glob(f"*{fname}*"))
        if matches:
            target = matches[0]
        else:
            return f"Error: Module file '{filename}' not found."

    return target.read_text(encoding="utf-8", errors="replace")


def tool_trace_dependencies(repo_name: str | None = None) -> str:
    """Map dependencies across all modules in the OKF bundle."""
    root = find_okf_root(repo_name)
    if not root:
        return f"Error: No OKF bundle found."

    modules_dir = root / "modules"
    if not modules_dir.is_dir():
        return "Error: No modules directory found."

    dep_map = {}
    for md_path in modules_dir.glob("*.md"):
        try:
            raw = md_path.read_text(encoding="utf-8", errors="replace")
            post = fm.loads(raw)
            meta = post.metadata
            dep_map[meta.get("title", md_path.stem)] = {
                "resource": meta.get("resource", ""),
                "type": meta.get("type", "module"),
                "key_functions": meta.get("key_functions", []),
                "tags": meta.get("tags", []),
            }
        except Exception:
            continue

    return json.dumps(dep_map, indent=2)


# ── MCP Tool Definitions (JSON Schema) ────────────────────────────────────────

MCP_TOOLS = [
    {
        "name": "list_bundles",
        "description": "List all available local OKF knowledge bundles and their file paths.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "get_project_index",
        "description": "Get the master index.md architecture map for a repository bundle. Call this first to understand the full project structure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_name": {
                    "type": "string",
                    "description": "Optional repository or bundle name. Omit to use local directory.",
                },
            },
        },
    },
    {
        "name": "search_bundle",
        "description": "Search OKF modules by keywords or technical concepts. Returns scored module summaries and key functions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language question or concept query (e.g. 'authentication', 'database schema', 'pipeline').",
                },
                "repo_name": {
                    "type": "string",
                    "description": "Optional repo/bundle name.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_module",
        "description": "Read the full OKF markdown documentation for a specific module, including function signatures, AST breakdown, and docstrings.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": "Module filename (e.g., 'src-auth-router.md' or 'auth_router.py').",
                },
                "repo_name": {
                    "type": "string",
                    "description": "Optional repo/bundle name.",
                },
            },
            "required": ["filename"],
        },
    },
    {
        "name": "trace_dependencies",
        "description": "Get a map of all project modules, their types, key functions, and dependencies.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_name": {
                    "type": "string",
                    "description": "Optional repo/bundle name.",
                },
            },
        },
    },
]


# ── MCP Server Loop (STDIO Transport) ────────────────────────────────────────

def run_mcp_server():
    """Main STDIO JSON-RPC 2.0 event loop for Model Context Protocol (MCP)."""
    # Force utf-8 stdout/stdin
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            req = json.loads(line)
            req_id = req.get("id")
            method = req.get("method")
            params = req.get("params", {})

            # ── Initialize ──
            if method == "initialize":
                _reply(req_id, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {},
                    },
                    "serverInfo": {
                        "name": "codemind-okf-mcp",
                        "version": "1.0.0",
                    },
                })

            elif method == "notifications/initialized":
                pass  # Client notification — no reply needed

            # ── Tools List ──
            elif method == "tools/list":
                _reply(req_id, {"tools": MCP_TOOLS})

            # ── Tools Call ──
            elif method == "tools/call":
                tool_name = params.get("name")
                args = params.get("arguments", {})
                result_text = _execute_tool(tool_name, args)

                _reply(req_id, {
                    "content": [
                        {
                            "type": "text",
                            "text": result_text,
                        }
                    ]
                })

            elif method == "ping":
                _reply(req_id, {})

            else:
                if req_id is not None:
                    _reply_error(req_id, -32601, f"Method '{method}' not found")

        except json.JSONDecodeError:
            continue
        except Exception as e:
            sys.stderr.write(f"[CodeMind MCP Error] {e}\n")
            sys.stderr.flush()


def _execute_tool(name: str, args: dict[str, Any]) -> str:
    """Route tool call to appropriate handler function."""
    try:
        if name == "list_bundles":
            return tool_list_bundles()
        elif name == "get_project_index":
            return tool_get_project_index(args.get("repo_name"))
        elif name == "search_bundle":
            return tool_search_bundle(
                query=args.get("query", ""),
                repo_name=args.get("repo_name"),
                max_results=int(args.get("max_results", 5)),
            )
        elif name == "read_module":
            return tool_read_module(
                filename=args.get("filename", ""),
                repo_name=args.get("repo_name"),
            )
        elif name == "trace_dependencies":
            return tool_trace_dependencies(args.get("repo_name"))
        else:
            return f"Error: Unknown tool '{name}'."
    except Exception as e:
        return f"Tool Execution Error ({name}): {str(e)}"


def _reply(req_id: Any, result: Any):
    if req_id is None:
        return
    msg = {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "result": result,
    }
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def _reply_error(req_id: Any, code: int, message: str):
    if req_id is None:
        return
    msg = {
        "jsonrpc": JSONRPC_VERSION,
        "id": req_id,
        "error": {
            "code": code,
            "message": message,
        },
    }
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    run_mcp_server()
