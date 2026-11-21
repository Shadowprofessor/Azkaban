"""azkaban CLI entry point."""
from __future__ import annotations

import argparse
import sys

from . import __version__


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
                     help="Record this session to a .azk file (explicit opt-in)")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.cmd == "capture":
        from .safety import require_loopback, require_ownership
        require_ownership(args.owns)
        require_loopback(args.listen_host, "proxy")
        import asyncio
        from .agent import Agent
        from .config import Config
        cfg = Config.from_env()
        if args.proxy_port:
            cfg.proxy_port = args.proxy_port
        if args.ws_port:
            cfg.ws_port = args.ws_port
        try:
            asyncio.run(Agent(cfg).run())
        except KeyboardInterrupt:
            pass
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
