"""
app/api/routes/mcp.py — MCP HTTP Router
========================================
Exposes Model Context Protocol (MCP) JSON-RPC 2.0 tools over HTTP.
Enables web clients, remote Cursor instances, and cloud agents to consume OKF tools.
"""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Request

from codemind_okf.mcp import MCP_TOOLS, _execute_tool

router = APIRouter()


@router.get("/tools")
async def list_mcp_tools():
    """List all available MCP tools."""
    return {"tools": MCP_TOOLS}


@router.post("")
async def mcp_rpc_handler(request: Request):
    """
    HTTP JSON-RPC 2.0 endpoint for MCP.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "codemind-okf-mcp", "version": "1.0.0"},
            },
        }

    elif method == "notifications/initialized":
        return {"jsonrpc": "2.0", "result": None}

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": MCP_TOOLS},
        }

    elif method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})
        result_text = _execute_tool(tool_name, args)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {"type": "text", "text": result_text}
                ]
            },
        }

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method '{method}' not found"},
        }
