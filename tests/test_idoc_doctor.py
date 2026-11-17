import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "src")
EX = os.path.join(HERE, "..", "examples")
sys.path.insert(0, SRC)

from idoc_doctor.cli import main  # noqa: E402
from idoc_doctor.idoc import lint, parse, summarize  # noqa: E402
from idoc_doctor.knowledge import PLAYBOOKS, STATUS, explain_status, match_playbooks  # noqa: E402
from idoc_doctor.mcp_server import handle  # noqa: E402


def read(name):
    with open(os.path.join(EX, name), encoding="utf-8") as fh:
        return fh.read()


class Knowledge(unittest.TestCase):
    def test_core_statuses_present(self):
        for code in ("02", "03", "29", "30", "51", "53", "56", "60", "64", "66", "68"):
            self.assertIn(code, STATUS)
        self.assertTrue(STATUS["51"][2])
        self.assertFalse(STATUS["53"][2])

    def test_explain_pads_and_unknown(self):
        self.assertEqual(explain_status("3")["meaning"], "Data passed to port OK")
        self.assertIsNone(explain_status("99")["is_error"])

    def test_playbook_matching(self):
        cases = {
            "Partner profile not available": "Partner profile missing",
            "Material MAT-1 not maintained in plant 1000": "Material not set up",
            "Sold-to party 4711 not defined for sales area 1000/10/00": "Customer / partner not set up for the sales area",
            "Mandatory condition PR00 is missing": "Pricing failed",
            "Sales document 123 is currently being processed by USER1": "Object locked",
            "Posting only possible in periods 2026/10 and 2026/09": "Posting period closed",
            "Unit of measure CS is not defined; ISO code": "Unit of measure not recognised",
            "Purchase order number PO1 already exists": "Duplicate document",
            "Function module not allowed: IDOC_INPUT_ORDERS": "Wrong process code",
            "Credit limit exceeded": "Credit block",
        }
        for msg, title in cases.items():
            hits = match_playbooks(msg)
            self.assertTrue(hits, msg)
            self.assertEqual(hits[0]["title"], title, msg)
        self.assertEqual(match_playbooks("something unrelated happened"), [])

    def test_every_playbook_has_text(self):
        for _, title, cause, fix in PLAYBOOKS:
            self.assertTrue(title and cause and fix)


class Parsing(unittest.TestCase):
    def setUp(self):
        self.bad = parse(read("orders05-bad.xml"))[0]
        self.ok = parse(read("delvry07-ok.xml"))[0]

    def test_summary_orders(self):
        s = summarize(self.bad)
        self.assertEqual(s["docnum"], "4711001")
        self.assertEqual((s["message_type"], s["direction"]), ("ORDERS", "inbound"))
        self.assertEqual(s["partners"], {"ship-to": "STORE-0042"})
        self.assertEqual(s["business"]["customer_po"], "PO-2026-11-0000123456-REPLENISHMENT-EAST")
        self.assertEqual(len(s["business"]["items"]), 2)
        self.assertEqual(s["business"]["items"][0]["material"], "MAT-100")
        self.assertEqual(s["segments"]["E1EDP19"], 1)

    def test_summary_delivery(self):
        s = summarize(self.ok)
        self.assertEqual(s["business"]["delivery"], "0080001234")
        self.assertEqual(s["business"]["bill_of_lading"], "1Z999AA10123456784")
        self.assertEqual([i["qty"] for i in s["business"]["items"]], ["12.000", "3.000"])

    def test_lint_finds_seeded_problems(self):
        got = {(i.level, i.where) for i in lint(self.bad)}
        self.assertEqual(got, {
            ("ERROR", "E1EDK03.DATUM"),             # 31 Nov
            ("WARN", "E1EDKA1.PARTN"),               # trailing space
            ("ERROR", "E1EDK02.BELNR"),              # 40 > 35 chars
            ("ERROR", "E1EDP01.MENGE"),              # decimal comma
            ("WARN", "E1EDKA1"),                     # no sold-to
            ("ERROR", "E1EDP01[000010]"),            # duplicate POSEX
            ("ERROR", "E1EDP01[000010].MENGE"),      # zero quantity
            ("WARN", "E1EDP01[000010]"),             # no material on item 2
        })

    def test_clean_delivery_has_no_issues(self):
        self.assertEqual(lint(self.ok), [])

    def test_empty_control_and_no_items(self):
        xml = "<ORDERS05><IDOC><EDI_DC40><MESTYP>ORDERS</MESTYP><DIRECT>9</DIRECT></EDI_DC40></IDOC></ORDERS05>"
        where = {i.where for i in lint(parse(xml)[0])}
        self.assertTrue({"EDI_DC40.IDOCTYP", "EDI_DC40.SNDPRN", "EDI_DC40.RCVPRN", "EDI_DC40.DIRECT",
                         "E1EDP01", "E1EDK02"} <= where)

    def test_multiple_idocs_and_rejects(self):
        two = "<R><IDOC><EDI_DC40><DOCNUM>1</DOCNUM></EDI_DC40></IDOC><IDOC><EDI_DC40><DOCNUM>2</DOCNUM></EDI_DC40></IDOC></R>"
        self.assertEqual([d.control["DOCNUM"] for d in parse(two)], ["1", "2"])
        with self.assertRaises(ValueError):
            parse("<root><x/></root>")
        with self.assertRaises(ValueError):
            parse('<!DOCTYPE x [<!ENTITY a "b">]><IDOC/>')


class Cli(unittest.TestCase):
    def run_cli(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(list(args))
        return rc, buf.getvalue()

    def test_explain_strict_and_json(self):
        rc, _ = self.run_cli("explain", os.path.join(EX, "orders05-bad.xml"), "--strict")
        self.assertEqual(rc, 2)
        rc, out = self.run_cli("explain", os.path.join(EX, "delvry07-ok.xml"), "--strict", "--json")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)[0]["issues"], [])

    def test_status_text(self):
        rc, out = self.run_cli("status", "64")
        self.assertEqual(rc, 0)
        self.assertIn("RBDAPP01", out)


class Mcp(unittest.TestCase):
    def test_handshake_list_call(self):
        init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                       "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}})
        self.assertEqual(init["result"]["serverInfo"]["name"], "idoc-doctor")
        self.assertIn("tools", init["result"]["capabilities"])
        self.assertIsNone(handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))
        tools = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]
        self.assertEqual({t["name"] for t in tools}, {"explain_idoc_status", "explain_idoc"})
        res = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                      "params": {"name": "explain_idoc", "arguments": {"xml": read("orders05-bad.xml")}}})
        self.assertFalse(res["result"]["isError"])
        self.assertIn("decimal comma", res["result"]["content"][0]["text"])
        bad = handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                      "params": {"name": "explain_idoc", "arguments": {"xml": "<nope/>"}}})
        self.assertTrue(bad["result"]["isError"])
        self.assertEqual(handle({"jsonrpc": "2.0", "id": 5, "method": "nope"})["error"]["code"], -32601)

    def test_stdio_round_trip(self):
        msgs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
             "params": {"name": "explain_idoc_status", "arguments": {"status": "56", "message": "Partner profile not available"}}},
        ]
        env = dict(os.environ, PYTHONPATH=os.path.abspath(SRC))
        proc = subprocess.run([sys.executable, "-m", "idoc_doctor", "mcp"], input="\n".join(json.dumps(m) for m in msgs) + "\n",
                              capture_output=True, text=True, env=env, timeout=30)
        replies = [json.loads(ln) for ln in proc.stdout.splitlines() if ln.strip()]
        self.assertEqual([r["id"] for r in replies], [1, 2])
        self.assertIn("Partner profile missing", replies[1]["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
