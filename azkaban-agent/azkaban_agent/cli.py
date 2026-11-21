"""azkaban CLI entry point.

    azkaban capture --i-own-this-device [--record s.azk]
    azkaban replay demo.azk --speed 2x
    azkaban honeytoken add "contact card Dobby" | honeytoken list
    azkaban export-evidence          (asks the running agent to export its chain)
    azkaban verify-evidence file.jsonl
    azkaban train
"""
from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys

from . import __version__
from .config import REPO_ROOT, Config


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="azkaban", description="Azkaban privacy forensics agent")
    p.add_argument("--version", action="version", version=f"azkaban-agent {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    cap = sub.add_parser("capture", help="Start The Trace: live capture of your own device")
    cap.add_argument("--i-own-this-device", dest="owns", action="store_true",
                     help="Confirm you only capture a device and network you own")
    cap.add_argument("--listen-host", default="127.0.0.1", help="Proxy bind host (loopback only)")
    cap.add_argument("--proxy-port", type=int, default=None)
    cap.add_argument("--ws-port", type=int, default=None)
    cap.add_argument("--record", metavar="FILE", default=None,
                     help="Record this session to a .azk file (explicit opt-in; contains unredacted traffic)")

    rp = sub.add_parser("replay", help="Replay a recorded .azk session over the same protocol")
    rp.add_argument("file")
    rp.add_argument("--speed", default="1x", help="e.g. 2x, 0.5x")
    rp.add_argument("--loop", action="store_true", help="Replay forever")
    rp.add_argument("--wait", type=float, default=10.0, help="Seconds to wait for a dashboard before starting")
    rp.add_argument("--ws-port", type=int, default=None)

    ht = sub.add_parser("honeytoken", help="Manage canary values")
    hts = ht.add_subparsers(dest="ht_cmd", required=True)
    hta = hts.add_parser("add", help="Create a new canary token to plant somewhere")
    hta.add_argument("label", help="Where you will plant it, e.g. \"contact card Dobby\"")
    hts.add_parser("list", help="List canary tokens")

    ex = sub.add_parser("export-evidence", help="Ask the running agent to export its evidence pack")
    ex.add_argument("--ws-port", type=int, default=None)
    vf = sub.add_parser("verify-evidence", help="Verify a hash-chained evidence log (.jsonl)")
    vf.add_argument("file")

    tr = sub.add_parser("train", help="Retrain the severity model (XGBoost -> ONNX)")
    tr.add_argument("--n", type=int, default=60000)

    ds = sub.add_parser("demo-session", help="Write a synthetic (fake-identity) demo .azk file")
    ds.add_argument("file", nargs="?", default=str(REPO_ROOT / "azkaban-agent" / "demo" / "demo.azk"))

    sub.add_parser("fetch-geo", help="Download the offline DB-IP country database")

    rc = sub.add_parser("rag-check", help="Show which law sections and remediation a flow retrieves")
    rc.add_argument("--tracker", action="store_true", help="Treat the destination as a tracker")
    rc.add_argument("--cross-border", action="store_true", help="Destination outside the home country")
    rc.add_argument("--no-consent", action="store_true", help="No consent signal observed")
    rc.add_argument("--child-app", action="store_true", help="A children's app")
    rc.add_argument("--pii", default="", help="Comma-separated PII types, e.g. gps,adid")
    rc.add_argument("--company", default="Google", help="Destination company or host")

    nc = sub.add_parser("nim-check", help="Verify the NVIDIA NIM key, model and endpoint end to end")
    nc.add_argument("--prompt", default="Reply with exactly: READY",
                    help="Prompt to send (no user data is involved)")
    return p


def _cfg(args) -> Config:
    cfg = Config.from_env()
    if getattr(args, "proxy_port", None):
        cfg.proxy_port = args.proxy_port
    if getattr(args, "ws_port", None):
        cfg.ws_port = args.ws_port
    return cfg


async def _ask_export(port: int) -> int:
    from websockets.asyncio.client import connect  # egress-ok: URL comes from net.local_ws_url (loopback)

    from .net import local_ws_url
    try:
        async with connect(local_ws_url(port)) as ws:
            await ws.send(json.dumps({"type": "export_evidence"}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 60))
                if msg.get("type") == "evidence":
                    print(f"[azkaban] evidence pack: {msg['path']}\n          entries: {msg['entries']}\n"
                          f"          root hash: {msg['rootHash']}")
                    return 0
                if msg.get("type") == "error" and msg.get("code") == "command_failed":
                    print(f"[azkaban] export failed: {msg['message']}", file=sys.stderr)
                    return 1
    except OSError:
        print(f"[azkaban] no agent running on ws://127.0.0.1:{port}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "capture":
        from .agent import Agent
        from .safety import require_loopback, require_ownership
        require_ownership(args.owns)
        require_loopback(args.listen_host, "proxy")
        try:
            asyncio.run(Agent(_cfg(args), mode="live", record=args.record, consent=args.owns).run())
        except KeyboardInterrupt:
            pass
        return 0

    if args.cmd == "replay":
        from .agent import Agent
        from .session import parse_speed
        try:
            asyncio.run(Agent(_cfg(args), mode="replay").run_replay(
                args.file, parse_speed(args.speed), args.loop, args.wait))
        except KeyboardInterrupt:
            pass
        return 0

    if args.cmd == "honeytoken":
        from . import honeytoken
        if args.ht_cmd == "add":
            t = honeytoken.add(args.label)
            print(f"[azkaban] canary for {t['label']!r}:\n\n    {t['token']}\n\n"
                  "Plant it where only that place could leak it (a contact's name/note, the clipboard, a form "
                  "field). Restart capture; any app that sends it out trips the alarm.")
        else:
            for t in honeytoken.load():
                print(f"{t['token']}  {t['label']}")
        return 0

    if args.cmd == "export-evidence":
        return asyncio.run(_ask_export(_cfg(args).ws_port))

    if args.cmd == "verify-evidence":
        from .evidence import verify
        ok, msg = verify(args.file)
        print(("[azkaban] " if ok else "[azkaban] TAMPERED: ") + msg)
        return 0 if ok else 2

    if args.cmd == "train":
        return subprocess.call([sys.executable, str(REPO_ROOT / "train" / "train_xgb.py"), "--n", str(args.n)])

    if args.cmd == "demo-session":
        from .demo import write
        n = write(args.file)
        print(f"[azkaban] wrote {n} synthetic flows to {args.file}")
        return 0

    if args.cmd == "rag-check":
        sys.path.insert(0, str(REPO_ROOT))
        try:
            from rag.guides import remediate
            from rag.query import explain
        except Exception as ex:
            print(f"[azkaban] retrieval layer not importable: {ex}", file=sys.stderr)
            return 1
        pii = [x.strip() for x in args.pii.split(",") if x.strip()]
        facts = {"pii_types": pii, "company": args.company, "is_tracker": args.tracker,
                 "tracker_category": "advertising" if args.tracker else None,
                 "cross_border": args.cross_border, "consent": not args.no_consent,
                 "child_app": args.child_app, "app_category": "utility",
                 "pii_unexpected_for_app_category": [], "hashed_identifier": False,
                 "same_adid_across_apps": 0, "while_user_idle": False, "decrypted": True}
        print("[azkaban] law retrieved for this flow:")
        print(explain(facts, 5))
        r = remediate(company=args.company, kind="unknown_tracker", pii_types=pii)
        print(f"\n[azkaban] remediation ({r['source']}): {r['title']}")
        for i, step in enumerate(r["steps"], 1):
            print(f"  {i}. {step}")
        if r["url"]:
            print(f"  source: {r['url']}")
        return 0

    if args.cmd == "nim-check":
        from .nim import NimClient
        cfg = _cfg(args)
        c = NimClient(cfg)
        print(f"[azkaban] endpoint {cfg.nim_url}")
        print(f"[azkaban] model    {c.model}")
        print(f"[azkaban] key      {'set (' + cfg.nim_key[:8] + '...)' if cfg.nim_key else 'MISSING'}")
        if not c.configured:
            print("[azkaban] NIM is not configured. Put NVIDIA_API_KEY in .env "
                  "(and do not set AZK_NIM_ENABLED=0).", file=sys.stderr)
            return 1
        if not c.available(force=True):
            print("[azkaban] endpoint did not accept the key (GET /models failed).\n"
                  "          Check the key at build.nvidia.com, and that this machine can\n"
                  "          reach integrate.api.nvidia.com (corporate proxy / firewall).",
                  file=sys.stderr)
            return 2
        print("[azkaban] endpoint reachable, key accepted.")
        ids = c.models()
        if ids and c.model not in ids:
            near = [m for m in ids if "nemotron" in m.lower()][:8]
            print(f"[azkaban] WARNING: '{c.model}' is not in the endpoint's model list.",
                  file=sys.stderr)
            if near:
                print("          nemotron models offered: " + ", ".join(near), file=sys.stderr)
            print("          Set AZK_NIM_MODEL in .env to one of them.", file=sys.stderr)
        elif ids:
            print(f"[azkaban] model is listed by the endpoint ({len(ids)} models available).")
        print(f"[azkaban] probing which models this key may call...")
        usable = []
        for model in c.candidates()[:8]:
            ok, why = c.try_model(model)
            mark = "OK " if ok else "-- "
            print(f"          {mark}{model:48} {'' if ok else why}")
            if ok:
                usable.append(model)
        if not usable:
            print("[azkaban] the key is valid but not entitled to any Nemotron chat model.\n"
                  "          Open https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b,\n"
                  "          sign in, accept the model terms and generate the key from that page,\n"
                  "          then put the new key in .env. Verdicts fall back to local Ollama meanwhile.",
                  file=sys.stderr)
            return 3
        best = usable[0]
        if best != c.configured_model:
            print(f"[azkaban] '{c.configured_model}' is refused for this key. The agent will fall back\n"
                  f"          to '{best}' automatically; to make it permanent put this in .env:\n"
                  f"              AZK_NIM_MODEL={best}")
        c.cfg.nim_model = best
        try:
            out = c.ask("You are terse. Answer in plain text with no markdown.", args.prompt,
                        max_tokens=64, log_payload=False)
        except Exception as ex:
            print(f"[azkaban] chat failed: {type(ex).__name__}: {ex}", file=sys.stderr)
            return 3
        print(f"[azkaban] {best} replied: {out!r}")
        return 0

    if args.cmd == "fetch-geo":
        from .geo import fetch_dbip
        print(f"[azkaban] saved {fetch_dbip()}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
