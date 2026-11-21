"""Tamper-evident, hash-chained capture log and forensic evidence pack (PDF + JSONL).

Each entry stores sha256 of the previous entry; editing, removing or reordering any
entry breaks every hash after it. Entries hold REDACTED flow data only. The chain
lives in memory and is written to disk only when the operator exports it.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import platform
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

GENESIS_PREV = "0" * 64


def _canon(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class EvidenceChain:
    def __init__(self, mode: str, operator_consent: bool):
        self.entries: list[dict] = []
        self.verdicts: dict[str, dict] = {}
        self.started = int(time.time() * 1000)
        self._append("session_start", {
            "tool": f"azkaban-agent {__version__}",
            "mode": mode,
            "device": {"hostname": socket.gethostname(), "os": platform.platform(), "machine": platform.machine()},
            "operator": getpass.getuser(),
            "operator_consent": {
                "flag": "--i-own-this-device" if mode == "live" else "n/a (replay of a recorded session)",
                "asserted": operator_consent,
                "statement": "Operator affirmed that only a device and network they own were captured.",
            },
        })

    def _append(self, kind: str, data: dict) -> dict:
        prev = self.entries[-1]["hash"] if self.entries else GENESIS_PREV
        body = {"seq": len(self.entries), "ts": int(time.time() * 1000), "kind": kind, "data": data, "prev": prev}
        entry = {**body, "hash": _sha(_canon(body))}
        self.entries.append(entry)
        return entry

    def add_flow(self, flow: dict) -> dict:
        digest = _sha(_canon(flow))
        return self._append("flow", {"flowId": flow["id"], "flowTs": flow["ts"], "app": flow["app"],
                                     "host": flow["host"], "severity": flow["severity"],
                                     "decrypted": flow["decrypted"], "digest": digest, "flow": flow})

    def add_event(self, kind: str, data: dict) -> dict:
        return self._append(kind, data)

    def add_verdict(self, v: dict) -> None:
        self.verdicts[v["flowId"]] = v
        self._append("verdict", {"flowId": v["flowId"], "status": v["status"],
                                 "citations": [c["section"] for c in v.get("citations", [])],
                                 "digest": _sha(_canon(v))})

    @property
    def head(self) -> str:
        return self.entries[-1]["hash"]

    # ------------------------------------------------------------ export
    def export(self, out_dir: str | Path = "evidence") -> dict:
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        jsonl = out / f"azkaban-evidence-{stamp}.jsonl"
        sealed = self._append("export", {"entries": len(self.entries), "exported": int(time.time() * 1000)})
        with open(jsonl, "w", encoding="utf-8") as f:
            for e in self.entries:
                f.write(_canon(e) + "\n")
        pdf = out / f"azkaban-evidence-{stamp}.pdf"
        _write_pdf(pdf, self.entries, self.verdicts, jsonl.name)
        return {"path": str(pdf.resolve()), "jsonl": str(jsonl.resolve()), "rootHash": sealed["hash"],
                "entries": len(self.entries)}


def verify(path: str | Path) -> tuple[bool, str]:
    prev = GENESIS_PREV
    n = 0
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            e = json.loads(line)
            body = {k: e[k] for k in ("seq", "ts", "kind", "data", "prev")}
            if e["seq"] != i:
                return False, f"entry {i}: sequence number {e['seq']} out of order"
            if e["prev"] != prev:
                return False, f"entry {i}: prev hash does not match entry {i - 1}"
            if _sha(_canon(body)) != e["hash"]:
                return False, f"entry {i}: content was modified (hash mismatch)"
            prev = e["hash"]
            n += 1
    return True, f"OK: {n} entries, chain head {prev}"


def _write_pdf(path: Path, entries: list[dict], verdicts: dict, jsonl_name: str) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    mono = ss["Code"]
    mono.fontSize = 7
    mono.leading = 9
    small = ss["BodyText"]
    small.fontSize = 8
    small.leading = 10
    start = entries[0]
    sd = start["data"]
    flows = [e for e in entries if e["kind"] == "flow"]
    honey = [e for e in entries if e["kind"] == "honeytoken"]
    head = entries[-1]["hash"]

    def esc(s) -> str:
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story = [
        Paragraph("Azkaban - Forensic Evidence Pack", ss["Title"]),
        Paragraph("Chain of custody for network traffic captured from the operator's own device.", ss["Italic"]),
        Spacer(1, 6 * mm),
    ]
    custody = [
        ["Capture start", _iso(start["ts"])],
        ["Export time", _iso(entries[-1]["ts"])],
        ["Tool", sd["tool"]],
        ["Mode", sd["mode"]],
        ["Device", f"{sd['device']['hostname']} - {sd['device']['os']}"],
        ["Operator", sd["operator"]],
        ["Operator consent", f"{sd['operator_consent']['flag']} (asserted: {sd['operator_consent']['asserted']})"],
        ["Entries in chain", str(len(entries))],
        ["Flows", str(len(flows))],
        ["Honeytoken hits", str(len(honey))],
        ["Genesis hash", entries[0]["hash"]],
        ["Chain root (head) hash", head],
        ["Machine-readable log", jsonl_name],
    ]
    t = Table([[Paragraph(f"<b>{esc(a)}</b>", small), Paragraph(esc(b), mono if "hash" in a.lower() else small)]
               for a, b in custody], colWidths=[45 * mm, 125 * mm])
    t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story += [t, Spacer(1, 5 * mm), Paragraph(
        "Integrity: every entry contains the SHA-256 of the previous entry. Editing, removing or reordering any "
        "entry changes every subsequent hash, so the head hash above no longer matches. Verify with "
        f"<font face='Courier'>azkaban verify-evidence {esc(jsonl_name)}</font>. All personal data in this pack "
        "is redacted at capture time; raw values never left the agent.", small)]

    if honey:
        story += [Spacer(1, 5 * mm), Paragraph("Honeytoken canary hits (proof of exfiltration)", ss["Heading2"])]
        rows = [["#", "Time", "App", "Destination", "Canary", "Field / encoding"]]
        for e in honey:
            d = e["data"]
            rows.append([e["seq"], _iso(e["ts"]), d["app"], d["host"], d["label"], f"{d['field']} ({d['via']})"])
        ht = Table([[Paragraph(esc(c), small) for c in r] for r in rows], repeatRows=1,
                   colWidths=[10 * mm, 32 * mm, 25 * mm, 40 * mm, 30 * mm, 33 * mm])
        ht.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#7a1f1f")),
                                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))
        story.append(ht)

    story += [PageBreak(), Paragraph("Flow digests", ss["Heading2"])]
    rows = [["#", "Time", "App", "Host", "Sev", "PII (redacted)", "Entry hash"]]
    for e in flows:
        d = e["data"]
        pii = ", ".join(sorted({p["type"] for p in d["flow"]["pii"]})) or "-"
        rows.append([e["seq"], _iso(d["flowTs"])[11:19], d["app"], d["host"], d["severity"], pii, e["hash"][:16] + "..."])
    ft = Table([[Paragraph(esc(c), small) for c in r] for r in rows], repeatRows=1,
               colWidths=[9 * mm, 16 * mm, 25 * mm, 43 * mm, 11 * mm, 35 * mm, 32 * mm])
    ft.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#222222")),
                            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]))
    story.append(ft)

    if verdicts:
        story += [PageBreak(), Paragraph("Legal assessments (DPDP Act 2023)", ss["Heading2"]),
                  Paragraph("Generated by a local language model restricted to retrieved statute text. "
                            "Observations from network traffic, not legal advice.", ss["Italic"])]
        app_of = {e["data"]["flowId"]: (e["data"]["app"], e["data"]["host"]) for e in flows}
        for fid, v in verdicts.items():
            app, host = app_of.get(fid, ("?", "?"))
            cites = ", ".join(c["section"] for c in v.get("citations", [])) or "none"
            story += [Paragraph(f"<b>{esc(v['status'].upper())}</b> - {esc(app)} -> {esc(host)} "
                                f"<font size=7>(cites: {esc(cites)})</font>", small),
                      Paragraph(esc(v["reasoning"]), small), Spacer(1, 2 * mm)]

    def footer(canvas, doc):
        canvas.setFont("Courier", 6)
        canvas.drawString(15 * mm, 8 * mm, f"azkaban evidence | head {head} | page {doc.page}")

    SimpleDocTemplate(str(path), pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
                      topMargin=15 * mm, bottomMargin=15 * mm, title="Azkaban Evidence Pack").build(
        story, onFirstPage=footer, onLaterPages=footer)
