from __future__ import annotations

from .idoc import lint, parse, summarize
from .knowledge import explain_status

FOOTER = ("idoc-doctor explains one IDoc at a time. Trace follows an order across SAP, the middleware, "
          "the 3PL's EDI and the carrier, and shows where it stopped: see the README.")


def render_status(code: str, message: str = "", markdown: bool = False) -> str:
    e = explain_status(code, message)
    b = "**" if markdown else ""
    lines = [f"{b}IDoc status {e['status']}{b} ({e['direction']}): {e['meaning']}"
             + (" - error" if e["is_error"] else ""),
             f"Next: {e['next_step']}"]
    if message:
        if e["playbooks"]:
            lines.append("")
            lines.append(f"Message: \"{message}\"")
            for p in e["playbooks"]:
                lines.append(f"- {b}{p['title']}{b}. Likely cause: {p['likely_cause']} Fix: {p['fix']}")
        else:
            lines.append(f"No playbook matched \"{message}\". Read the full status record in WE02; "
                         "the long text (and SE91 message class/number) usually names the object.")
    lines.append("")
    lines.append("General guidance, not a diagnosis of your system.")
    return "\n".join(lines)


def render_idocs(xml_text: str, markdown: bool = False) -> str:
    docs = parse(xml_text)
    out: list[str] = []
    h = "### " if markdown else ""
    for d in docs:
        s = summarize(d)
        issues = lint(d)
        out.append(f"{h}IDoc {s['docnum'] or '(no number)'}: {s['message_type']} / {s['idoc_type']} ({s['direction']})")
        out.append(f"- from {s['sender']} to {s['receiver']}")
        if s.get("partners"):
            out.append("- partners: " + ", ".join(f"{k} {v}" for k, v in s["partners"].items()))
        biz = s.get("business") or {}
        for k, v in biz.items():
            if k == "items":
                continue
            if v:
                out.append(f"- {k.replace('_', ' ')}: {v}")
        items = biz.get("items")
        if isinstance(items, list):
            out.append(f"- items: {len(items)}")
            for it in items[:20]:
                out.append("  - " + ", ".join(f"{k} {v}" for k, v in it.items() if v))
        elif items:
            out.append(f"- items: {items}")
        out.append("- segments: " + ", ".join(f"{k} x{v}" for k, v in s["segments"].items()))
        if issues:
            out.append(f"- {sum(i.level == 'ERROR' for i in issues)} errors, "
                       f"{sum(i.level == 'WARN' for i in issues)} warnings:")
            for i in issues:
                out.append(f"  - {i.level} {i.where}: {i.message}")
        else:
            out.append("- lint: no problems found")
        out.append("")
    out.append(FOOTER)
    return "\n".join(out)
