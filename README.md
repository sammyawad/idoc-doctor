# idoc-doctor

<!-- mcp-name: io.github.sammyawad/idoc-doctor -->

**Explain SAP IDocs without logging in to SAP.** Paste an IDoc status and its message, or an XML IDoc, and get what it means, the usual causes, and what to check next. It also works as an MCP server, so Claude (or any MCP client) can explain the IDocs you paste into a chat.

Offline. It never connects to SAP, CPI or anything else. No dependencies. Python 3.9+.

```bash
pip install git+https://github.com/sammyawad/idoc-doctor

idoc-doctor status 51 -m "Material MAT-100 not maintained in plant 1000"
idoc-doctor explain orders.xml          # summary + lint
idoc-doctor mcp                          # MCP server on stdio
```

```
IDoc 4711001: ORDERS / ORDERS05 (inbound)
- from KU/RETAILER01 via SAPCPI to LS/S4HCLNT100 via SAPS4H
- customer po: PO-2026-11-0000123456-REPLENISHMENT-EAST
- items: 2
- 5 errors, 3 warnings:
  - ERROR E1EDK03.DATUM: '20261131' is not a valid YYYYMMDD date
  - ERROR E1EDK02.BELNR: 40 characters, field holds 35; it will be cut or rejected
  - ERROR E1EDP01.MENGE: '12,5' uses a decimal comma; IDocs expect a decimal point
  - ERROR E1EDP01[000010]: duplicate item number POSEX
  ...
```

## What it knows

- **Statuses:** 01-04, 12, 26, 29, 30 (outbound), and 51, 53, 56, 60, 62, 64-66, 68-70 (inbound). For each one: what it means and what to do next (WE20, WE21, SM59, SM58, BD87, RBDAPP01, RSEOUT00, ...).
- **Status-message playbooks:** missing partner profile, port/RFC errors, material not in plant, customer not in the sales area, plant not allowed, pricing (PR00), credit block, locks, closed posting period, unit of measure / ISO code, missing batch, duplicate PO, field format, wrong process code, segment/version mismatch, missing reference document.
- **XML IDoc summary:** sender, receiver, direction, partners (AG/WE/RE/...), and business fields for ORDERS/ORDCHG, DESADV/DELVRY/SHPCON/WHSCON and INVOIC.
- **Lint:**
  - empty control-record fields;
  - fields longer than their segment allows;
  - invalid YYYYMMDD dates, decimal commas and non-numeric quantities;
  - stray spaces in partner and material numbers;
  - orders with no items, no sold-to, no customer PO, duplicate item numbers, zero quantities or missing materials;
  - deliveries with no header or no items.

This is general SAP knowledge, not a diagnosis of your system. XML with DOCTYPE/ENTITY declarations is refused.

## Use it from Claude (MCP)

```json
{ "mcpServers": { "idoc-doctor": { "command": "idoc-doctor", "args": ["mcp"] } } }
```

Tools: `explain_idoc_status(status, message?)` and `explain_idoc(xml)`.

## Trace (planned)

idoc-doctor explains one IDoc. **Trace** follows one order number across S/4 (sales order, delivery, IDoc), the middleware (CPI/PI message log), the 3PL's EDI (940/945/856) and the carrier. It shows where the order stopped, with evidence, proposes the fix for a person to approve, and checks the order moved afterwards. Self-hosted, read-only collectors, priced per company. If you want it, open an issue titled "trace" and say which systems sit between your SAP and your carriers.

## License

MIT. SAP, S/4HANA and IDoc are trademarks of SAP SE; this project is not affiliated with SAP.
