"""Parse XML IDocs (the format CPI/PI and WE19/WE02 exports use), summarise them in
business terms, and lint them for the mistakes that usually end in status 51/56/60."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime

# Field lengths for common header/item fields (standard segment definitions).
MAX_LEN = {
    ("E1EDK02", "BELNR"): 35, ("E1EDK01", "BELNR"): 35, ("E1EDKA1", "PARTN"): 17,
    ("E1EDP01", "POSEX"): 6, ("E1EDP01", "MENEE"): 3, ("E1EDK01", "CURCY"): 3,
    ("E1EDP19", "IDTNR"): 35, ("E1EDL20", "VBELN"): 10, ("E1EDL24", "POSNR"): 6,
}
NUMERIC = {"MENGE", "LFIMG", "NTGEW", "BRGEW", "VOLUM", "VPREI", "NETWR", "SUMME", "BETRG", "LGMNG"}
DIRECTION = {"1": "outbound", "2": "inbound"}
PARTNER_ROLE = {"AG": "sold-to", "WE": "ship-to", "RE": "bill-to", "RG": "payer", "LF": "vendor",
                "SP": "carrier", "LS": "logical system"}


@dataclass
class Segment:
    name: str
    depth: int
    fields: dict[str, str]
    children: list["Segment"] = field(default_factory=list)


@dataclass
class Issue:
    level: str        # ERROR | WARN
    where: str
    message: str


@dataclass
class IDoc:
    control: dict[str, str]
    segments: list[Segment]          # top-level, with children nested

    def walk(self):
        stack = list(reversed(self.segments))
        while stack:
            s = stack.pop()
            yield s
            stack.extend(reversed(s.children))

    def find(self, name: str) -> list[Segment]:
        return [s for s in self.walk() if s.name == name]


def _segment(el: ET.Element, depth: int) -> Segment:
    fields, children = {}, []
    for child in el:
        if child.get("SEGMENT") is not None or len(child):
            children.append(_segment(child, depth + 1))
        else:
            fields[child.tag] = (child.text or "")
    return Segment(el.tag, depth, fields, children)


def parse(xml_text: str) -> list[IDoc]:
    if re.search(r"<!(?:DOCTYPE|ENTITY)", xml_text, re.I):
        raise ValueError("DOCTYPE/ENTITY declarations are not accepted")
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    idoc_els = [root] if root.tag == "IDOC" else root.findall(".//IDOC")
    if not idoc_els:
        raise ValueError("no <IDOC> element found; is this an XML IDoc?")
    out = []
    for el in idoc_els:
        control: dict[str, str] = {}
        segs: list[Segment] = []
        for child in el:
            if child.tag == "EDI_DC40":
                control = {c.tag: (c.text or "").strip() for c in child}
            else:
                segs.append(_segment(child, 0))
        out.append(IDoc(control, segs))
    return out


def _f(seg: Segment | None, name: str) -> str:
    return (seg.fields.get(name) or "").strip() if seg else ""


def _qual(segs: list[Segment], qualf: str, field_name: str = "QUALF") -> Segment | None:
    return next((s for s in segs if _f(s, field_name) == qualf), None)


def summarize(doc: IDoc) -> dict:
    c = doc.control
    mes = c.get("MESTYP", "")
    s = {
        "docnum": c.get("DOCNUM", "").lstrip("0"),
        "idoc_type": c.get("IDOCTYP", "") + (f" + {c['CIMTYP']}" if c.get("CIMTYP") else ""),
        "message_type": mes,
        "direction": DIRECTION.get(c.get("DIRECT", ""), c.get("DIRECT", "?")),
        "sender": f"{c.get('SNDPRT', '')}/{c.get('SNDPRN', '')} via {c.get('SNDPOR', '')}".strip(),
        "receiver": f"{c.get('RCVPRT', '')}/{c.get('RCVPRN', '')} via {c.get('RCVPOR', '')}".strip(),
        "segments": {},
    }
    for seg in doc.walk():
        s["segments"][seg.name] = s["segments"].get(seg.name, 0) + 1
    partners = {}
    for p in doc.find("E1EDKA1") + doc.find("E1ADRM1"):
        role = _f(p, "PARVW") or _f(p, "PARTNER_Q")
        if role:
            partners[PARTNER_ROLE.get(role, role)] = _f(p, "PARTN") or _f(p, "PARTNER_ID")
    if partners:
        s["partners"] = partners
    if mes in ("ORDERS", "ORDCHG", "ORDRSP"):
        po = _qual(doc.find("E1EDK02"), "001")
        req = _qual(doc.find("E1EDK03"), "002", "IDDAT")
        items = doc.find("E1EDP01")
        s["business"] = {
            "customer_po": _f(po, "BELNR"),
            "requested_delivery": _f(req, "DATUM"),
            "currency": _f(next(iter(doc.find("E1EDK01")), None), "CURCY"),
            "items": [{
                "item": _f(it, "POSEX"), "qty": _f(it, "MENGE"), "uom": _f(it, "MENEE"),
                "material": _f(_qual([c for c in it.children if c.name == "E1EDP19"], "002"), "IDTNR")
                or _f(_qual([c for c in it.children if c.name == "E1EDP19"], "001"), "IDTNR"),
            } for it in items],
        }
    elif mes in ("DESADV", "SHPCON", "WHSCON", "SHPORD", "DELVRY"):
        hdr = next(iter(doc.find("E1EDL20")), None)
        s["business"] = {
            "delivery": _f(hdr, "VBELN"), "bill_of_lading": _f(hdr, "BOLNR"),
            "items": [{"item": _f(i, "POSNR"), "material": _f(i, "MATNR"), "qty": _f(i, "LFIMG"),
                       "uom": _f(i, "VRKME")} for i in doc.find("E1EDL24")],
        }
    elif mes == "INVOIC":
        hdr = next(iter(doc.find("E1EDK01")), None)
        s["business"] = {"invoice": _f(hdr, "BELNR"), "currency": _f(hdr, "CURCY"),
                         "items": len(doc.find("E1EDP01"))}
    return s


def _valid_date(v: str) -> bool:
    if not re.fullmatch(r"\d{8}", v):
        return False
    if v == "00000000":
        return True          # SAP's initial date
    try:
        datetime.strptime(v, "%Y%m%d")
        return True
    except ValueError:
        return False


def lint(doc: IDoc) -> list[Issue]:
    c, issues = doc.control, []
    for k in ("IDOCTYP", "MESTYP", "SNDPRN", "RCVPRN"):
        if not c.get(k):
            issues.append(Issue("ERROR", f"EDI_DC40.{k}", "empty; the partner profile lookup will fail (status 56)"))
    if c.get("DIRECT") not in ("1", "2"):
        issues.append(Issue("WARN", "EDI_DC40.DIRECT", f"{c.get('DIRECT')!r} is not 1 (outbound) or 2 (inbound)"))

    for seg in doc.walk():
        for name, raw in seg.fields.items():
            v = raw.strip()
            where = f"{seg.name}.{name}"
            if raw != v and v and name in ("PARTN", "IDTNR", "MATNR", "BELNR", "KUNNR"):
                issues.append(Issue("WARN", where, f"leading/trailing spaces in {v!r}; lookups may not match"))
            if (seg.name, name) in MAX_LEN and len(v) > MAX_LEN[(seg.name, name)]:
                issues.append(Issue("ERROR", where, f"{len(v)} characters, field holds "
                                    f"{MAX_LEN[(seg.name, name)]}; it will be cut or rejected"))
            # DATUM is always a date; other *DAT fields only when they look like one
            # (IDDAT, for example, is a 3-digit date qualifier).
            is_date = name == "DATUM" or (name.endswith("DAT") and re.fullmatch(r"\d{8}", v or ""))
            if is_date and v and not _valid_date(v):
                issues.append(Issue("ERROR", where, f"{v!r} is not a valid YYYYMMDD date"))
            if name in NUMERIC and v:
                if re.fullmatch(r"-?\d+,\d+-?", v):
                    issues.append(Issue("ERROR", where, f"{v!r} uses a decimal comma; IDocs expect a decimal point"))
                elif not re.fullmatch(r"-?\d+(\.\d+)?-?", v):
                    issues.append(Issue("ERROR", where, f"{v!r} is not a number"))

    mes = c.get("MESTYP", "")
    if mes in ("ORDERS", "ORDCHG"):
        items = doc.find("E1EDP01")
        if not items:
            issues.append(Issue("ERROR", "E1EDP01", "no items; the order can't be created"))
        if not any(_f(p, "PARVW") == "AG" for p in doc.find("E1EDKA1")):
            issues.append(Issue("WARN", "E1EDKA1", "no sold-to partner (PARVW AG); sold-to must come from the partner profile"))
        if not _qual(doc.find("E1EDK02"), "001"):
            issues.append(Issue("WARN", "E1EDK02", "no customer PO number (QUALF 001)"))
        seen = set()
        for it in items:
            pos = _f(it, "POSEX")
            if pos and pos in seen:
                issues.append(Issue("ERROR", f"E1EDP01[{pos}]", "duplicate item number POSEX"))
            seen.add(pos)
            qty = _f(it, "MENGE")
            if not qty:
                issues.append(Issue("ERROR", f"E1EDP01[{pos}].MENGE", "no quantity"))
            elif re.fullmatch(r"-?\d+(\.\d+)?", qty) and float(qty) <= 0:
                issues.append(Issue("ERROR", f"E1EDP01[{pos}].MENGE", f"quantity {qty} is not positive"))
            if not any(ch.name == "E1EDP19" and _f(ch, "IDTNR") for ch in it.children) and not _f(it, "MATNR"):
                issues.append(Issue("WARN", f"E1EDP01[{pos}]", "no material (E1EDP19 IDTNR); needs a cross-reference to post"))
    elif mes in ("DESADV", "SHPCON", "WHSCON", "DELVRY"):
        if not doc.find("E1EDL20"):
            issues.append(Issue("ERROR", "E1EDL20", "no delivery header"))
        if not doc.find("E1EDL24"):
            issues.append(Issue("WARN", "E1EDL24", "no delivery items"))
    return issues
