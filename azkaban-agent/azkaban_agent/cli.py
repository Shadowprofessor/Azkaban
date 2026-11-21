"""azkaban CLI entry point."""
from __future__ import annotations

import argparse
import asyncio
import sys

from . import __version__
from .config import Config


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

    ds = sub.add_parser("demo-session", help="Write a synthetic (fake-identity) demo .azk file")
    ds.add_argument("file", nargs="?", default="azkaban-agent/demo/demo.azk")

    sub.add_parser("fetch-geo", help="Download the offline DB-IP country database")
    return p


def _cfg(args) -> Config:
    cfg = Config.from_env()
    if getattr(args, "proxy_port", None):
        cfg.proxy_port = args.proxy_port
    if getattr(args, "ws_port", None):
        cfg.ws_port = args.ws_port
    return cfg


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from .agent import Agent

    if args.cmd == "capture":
        from .safety import require_loopback, require_ownership
        require_ownership(args.owns)
        require_loopback(args.listen_host, "proxy")
        try:
            asyncio.run(Agent(_cfg(args), mode="live", record=args.record).run())
        except KeyboardInterrupt:
            pass
        return 0

    if args.cmd == "replay":
        from .session import parse_speed
        try:
            asyncio.run(Agent(_cfg(args), mode="replay").run_replay(
                args.file, parse_speed(args.speed), args.loop, args.wait))
        except KeyboardInterrupt:
            pass
        return 0

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
