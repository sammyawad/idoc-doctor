"""Public, general SAP IDoc knowledge: what each status means and the usual causes of the
most common error messages. Common causes, not a diagnosis of any particular system."""
from __future__ import annotations

import re

# status: (direction, meaning, is_error, what to do next)
STATUS = {
    "01": ("out", "IDoc generated", False, "Normal start of an outbound IDoc."),
    "02": ("out", "Error passing data to port", True,
           "Check the port (WE21) and its RFC destination (SM59: connection test). Reprocess with BD87."),
    "03": ("out", "Data passed to port OK", False,
           "SAP handed it off. If the receiver never got it, check the tRFC queue (SM58) and the middleware "
           "(CPI / PI message monitor) - 03 does not mean delivered."),
    "04": ("out", "Error within control information of EDI subsystem", True,
           "Partner/port data in the control record doesn't match the subsystem; check WE20 and WE21."),
    "12": ("out", "Dispatch OK", False, "Status after a successful dispatch confirmation."),
    "26": ("out", "Error during syntax check of outbound IDoc", True,
           "Segment order or a mandatory segment is wrong for the IDoc type; compare with WE30/WE60 and any extension."),
    "29": ("out", "Error in ALE service", True,
           "Usually a missing or wrong partner profile / distribution model (WE20, BD64) or a filter."),
    "30": ("out", "IDoc ready for dispatch (ALE service)", False,
           "Waiting for collected dispatch: output mode 'collect' needs report RSEOUT00 scheduled (or WE14)."),
    "51": ("in", "Application document not posted", True,
           "The application rejected the data. Read the status message (WE02 > status records), fix the master "
           "data or the mapping, then reprocess with BD87. Match the message against the playbooks below."),
    "53": ("in", "Application document posted", False, "Done. The posted document number is in the status record."),
    "56": ("in", "IDoc with errors added", True,
           "Usually no inbound partner profile for this sender / message type (WE20), or a bad control record."),
    "60": ("in", "Error during syntax check of inbound IDoc", True,
           "Segments don't fit the IDoc type or version (extension / release mismatch); compare in WE30/WE60."),
    "62": ("in", "IDoc passed to application", False, "In flight; should become 53 or 51."),
    "64": ("in", "IDoc ready to be transferred to application", False,
           "Waiting: partner profile says 'trigger by background program' and RBDAPP01 is not scheduled, "
           "or it ran before the IDoc arrived. Schedule RBDAPP01 or process with BD87."),
    "65": ("in", "Error in ALE service", True, "Check the distribution model, filters and partner profile."),
    "66": ("in", "IDoc is waiting for predecessor IDoc (serialization)", False,
           "An earlier IDoc for the same object hasn't posted; fix that one first (BD87 / serialization groups)."),
    "68": ("in", "Error - no further processing", True,
           "Someone or something marked it final (often via BD87 'delete' / RBDMANI2 logic). It won't post on its own."),
    "69": ("in", "IDoc was edited", False, "Edited in WE02/WE19; the original is kept with status 70. Reprocess it."),
    "70": ("in", "Original of an IDoc which was edited", False, "Kept for audit; the edited copy is the one to process."),
}

# (pattern, title, likely cause, fix) - ordered most specific first.
PLAYBOOKS = [
    (r"partner profile|no partner|partner .* not (?:available|maintained)",
     "Partner profile missing",
     "No WE20 entry for this partner number / partner type / message type (or wrong partner function).",
     "Create or correct the partner profile in WE20 (inbound: process code; outbound: port and output mode)."),
    (r"port .* (?:does not exist|not found)|error passing data to port|rfc destination",
     "Port or RFC destination broken",
     "The port in WE21 or its RFC destination in SM59 is wrong, locked or unreachable.",
     "Test the destination in SM59, fix credentials/target, then reprocess with BD87 or RSEOUT00."),
    (r"material .* (?:does not exist|not maintained|not defined)|material .* plant",
     "Material not set up",
     "The material number doesn't exist, or isn't extended to this plant / sales org (often a mapping or "
     "leading-zero / GTIN-to-material conversion issue).",
     "Check MM03 for the material and plant view; fix the cross-reference or the mapping, then reprocess."),
    (r"(?:sold-to|ship-to|customer|partner) .* (?:not defined|does not exist|not created).*(?:sales|area|org)?",
     "Customer / partner not set up for the sales area",
     "Sold-to or ship-to isn't created for this sales org / distribution channel / division, or the "
     "partner mapping (E1EDKA1 PARVW AG/WE) points at the wrong number.",
     "Check the business partner's sales area data; check the customer cross-reference (e.g. EDPAR / VOE4)."),
    (r"plant .* not (?:defined|allowed)|plant .* sales org",
     "Plant not allowed for the sales area",
     "The plant isn't assigned to the sales org / distribution channel.",
     "Fix the plant determination or the mapping; check the sales area assignment."),
    (r"pricing|condition .* (?:missing|not found)|pr00|mandatory condition",
     "Pricing failed",
     "A required condition record (for example PR00) doesn't exist for this material/customer/date.",
     "Maintain the condition record (VK11) or send the price in the IDoc if that's the design; reprocess."),
    (r"credit (?:limit|block|check)",
     "Credit block",
     "The order posted into a credit block or credit check stopped it.",
     "Release in credit management (VKM1 or the FSCM credit case); not an IDoc fix."),
    (r"(?:locked|being processed) by|currently being processed|enqueue",
     "Object locked",
     "Another user or job held a lock on the document or material when the IDoc ran.",
     "Usually transient: reprocess with BD87, or schedule RBDMANI2 to retry status 51 IDocs automatically."),
    (r"posting period|periods? .* (?:closed|not open)|only possible in periods",
     "Posting period closed",
     "The posting date falls in a closed MM/FI period (often a UTC vs local date issue at month end).",
     "Open the period (MMPV / OB52, by the right people) or correct the posting date; reprocess."),
    (r"unit of measure|iso code|uom",
     "Unit of measure not recognised",
     "The IDoc carries a UoM or ISO code that isn't mapped (T006 / CUNI ISO codes).",
     "Map the partner's unit to an SAP unit or ISO code; fix the middleware mapping."),
    (r"batch .* (?:does not exist|not found)",
     "Batch missing",
     "The batch number in the IDoc doesn't exist for the material/plant.",
     "Check batch master data, or stop sending a batch when the receiver does batch determination."),
    (r"(?:already exists|duplicate)|purchase order number .* already",
     "Duplicate document",
     "The customer PO number (E1EDK02 QUALF 001) or reference already exists and the duplicate check is on.",
     "Confirm it's a real duplicate before reprocessing; if it is, set the IDoc to 68 instead."),
    (r"date .* (?:invalid|incorrect)|conversion .* failed|format .* (?:incorrect|invalid)|not a valid (?:number|date)",
     "Field format",
     "A date, number or decimal arrived in the wrong format (YYYYMMDD, decimal point, signs, field length).",
     "Fix it in the sender or middleware mapping; editing in WE02 creates status 69/70 copies."),
    (r"function module.*not allowed|process code|inbound function module",
     "Wrong process code",
     "The inbound process code in WE20 points at the wrong function module for this message type (WE42/WE57).",
     "Correct the process code assignment in WE20."),
    (r"segment .* (?:unknown|not defined|does not exist)|syntax error|idoc type .* not",
     "Structure / version mismatch",
     "Sender and receiver disagree on the IDoc type, extension or segment release.",
     "Compare the segment definitions (WE30/WE31) and the partner profile's IDoc type/extension."),
    (r"delivery .* (?:not found|does not exist)|reference document .* not found",
     "Reference document missing",
     "The IDoc refers to a delivery/order that doesn't exist yet or under that number (timing or ID remap).",
     "Check whether the preceding document was created; check serialization and number mappings."),
]
_COMPILED = [(re.compile(p, re.I), t, c, f) for p, t, c, f in PLAYBOOKS]


def explain_status(code: str, message: str = "") -> dict:
    code = str(code).strip().zfill(2)
    info = STATUS.get(code)
    out = {"status": code}
    if info:
        direction, meaning, is_error, next_step = info
        out.update(direction=direction, meaning=meaning, is_error=is_error, next_step=next_step)
    else:
        out.update(direction="?", meaning="Unknown or customer-specific status", is_error=None,
                   next_step="Look it up in table TEDS1 / transaction WE47.")
    out["playbooks"] = match_playbooks(message) if message else []
    return out


def match_playbooks(message: str, limit: int = 3) -> list[dict]:
    hits = []
    for rx, title, cause, fix in _COMPILED:
        if rx.search(message or ""):
            hits.append({"title": title, "likely_cause": cause, "fix": fix})
        if len(hits) >= limit:
            break
    return hits
