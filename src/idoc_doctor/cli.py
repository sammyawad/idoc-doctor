from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import __version__
from .idoc import lint, parse, summarize
from .knowledge import explain_status
from .render import render_idocs, render_status


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="idoc-doctor",
                                description="Explain SAP IDoc statuses and XML IDocs, offline. Never connects to SAP.")
    p.add_argument("--version", action="version", version=f"idoc-doctor {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("status", help="explain a status code, optionally with its message text")
    s.add_argument("code")
    s.add_argument("--message", "-m", default="")
    s.add_argument("--json", action="store_true")
    e = sub.add_parser("explain", help="summarise and lint an XML IDoc file ('-' for stdin)")
    e.add_argument("file")
    e.add_argument("--json", action="store_true")
    e.add_argument("--md", action="store_true")
    e.add_argument("--strict", action="store_true", help="exit 2 if any ERROR is found")
    sub.add_parser("mcp", help="run as an MCP server on stdio")
    a = p.parse_args(argv)

    if a.cmd == "status":
        if a.json:
            print(json.dumps(explain_status(a.code, a.message), indent=2))
        else:
            print(render_status(a.code, a.message))
        return 0
    if a.cmd == "mcp":
        from .mcp_server import serve
        serve()
        return 0

    if a.file == "-":
        text = sys.stdin.read()
    else:
        with open(a.file, encoding="utf-8-sig") as fh:
            text = fh.read()
    try:
        docs = parse(text)
    except (ValueError, SyntaxError) as exc:
        print(f"idoc-doctor: {exc}", file=sys.stderr)
        return 1
    errors = sum(1 for d in docs for i in lint(d) if i.level == "ERROR")
    if a.json:
        print(json.dumps([{"summary": summarize(d), "issues": [asdict(i) for i in lint(d)]} for d in docs], indent=2))
    else:
        print(render_idocs(text, markdown=a.md))
    return 2 if a.strict and errors else 0


if __name__ == "__main__":
    sys.exit(main())
