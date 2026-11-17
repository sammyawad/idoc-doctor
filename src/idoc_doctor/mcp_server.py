"""A dependency-free MCP server (stdio, JSON-RPC 2.0, one message per line).
Tools: explain_idoc_status, explain_idoc. It never connects to SAP."""
from __future__ import annotations

import json
import sys

from . import __version__
from .render import render_idocs, render_status

PROTOCOL = "2025-06-18"
TOOLS = [
    {
        "name": "explain_idoc_status",
        "description": "Explain an SAP IDoc status code (e.g. 51, 56, 64, 03) and, if a status message is given, "
                       "match it against common causes and fixes (missing partner profile, material not in plant, "
                       "pricing, locks, closed periods, UoM, format errors...). General knowledge, not a diagnosis.",
        "inputSchema": {"type": "object", "properties": {
            "status": {"type": "string", "description": "Two-digit IDoc status, e.g. \"51\""},
            "message": {"type": "string", "description": "The status record text from WE02/BD87, optional"}},
            "required": ["status"]},
    },
    {
        "name": "explain_idoc",
        "description": "Parse an XML IDoc (ORDERS, DESADV/DELVRY, INVOIC, ...): summarise sender, receiver, "
                       "PO/delivery numbers, partners and items, and lint it for the mistakes that end in status "
                       "51/56/60 (field too long, decimal comma, bad dates, missing items or partners, duplicates).",
        "inputSchema": {"type": "object", "properties": {
            "xml": {"type": "string", "description": "The IDoc XML text"}}, "required": ["xml"]},
    },
]


def handle(msg: dict) -> dict | None:
    mid, method = msg.get("id"), msg.get("method")
    if mid is None:                       # notification (e.g. notifications/initialized)
        return None
    try:
        if method == "initialize":
            client_ver = (msg.get("params") or {}).get("protocolVersion") or PROTOCOL
            result = {"protocolVersion": client_ver, "capabilities": {"tools": {}},
                      "serverInfo": {"name": "idoc-doctor", "version": __version__}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            params = msg.get("params") or {}
            name, args = params.get("name"), params.get("arguments") or {}
            try:
                if name == "explain_idoc_status":
                    text = render_status(str(args["status"]), args.get("message", ""), markdown=True)
                elif name == "explain_idoc":
                    text = render_idocs(args["xml"], markdown=True)
                else:
                    return _err(mid, -32602, f"unknown tool {name!r}")
                result = {"content": [{"type": "text", "text": text}], "isError": False}
            except (KeyError, ValueError) as exc:
                result = {"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True}
        else:
            return _err(mid, -32601, f"method not found: {method}")
    except Exception as exc:  # never crash the server on one bad request
        return _err(mid, -32603, str(exc))
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _err(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def serve(stdin=None, stdout=None) -> None:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            reply = _err(None, -32700, "parse error")
        else:
            reply = handle(msg)
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
