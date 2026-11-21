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
    return p


def _cfg(args) -> Config:
    cfg = Config.from_env()
    if getattr(args, "proxy_port", None):
        cfg.proxy_port = args.proxy_port
    if getattr(args, "ws_port", None):
        cfg.ws_port = args.ws_port
    return cfg


async def _ask_export(port: int) -> int:
    from websockets.asyncio.client import connect
    try:
        async with connect(f"ws://127.0.0.1:{port}") as ws:
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

    if args.cmd == "fetch-geo":
        from .geo import fetch_dbip
        print(f"[azkaban] saved {fetch_dbip()}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
