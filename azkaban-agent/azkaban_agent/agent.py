"""Agent runtime: wires capture -> pipeline -> outputs on one asyncio loop."""
from __future__ import annotations

import asyncio
import json
import sys

from .capture import CaptureAddon, run_proxy
from .config import Config
from .schema import Flow


def raw_to_flow(raw: dict) -> Flow:
    return Flow(
        id=raw["id"], ts=raw["ts"], app=raw.get("app", "unknown"), host=raw.get("host", ""),
        method=raw.get("method", ""), path=raw.get("path", ""), ip=raw.get("ip", ""),
        decrypted=bool(raw.get("decrypted", True)), bytes=int(raw.get("bytes", 0)),
    )


class Agent:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.loop: asyncio.AbstractEventLoop | None = None
        self.addon = CaptureAddon(self._on_raw_threadsafe)

    def _on_raw_threadsafe(self, raw: dict) -> None:
        # mitmproxy hooks run on our loop, but be safe if called from a thread.
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.on_raw, raw)
        else:
            self.on_raw(raw)

    def on_raw(self, raw: dict) -> None:
        flow = raw_to_flow(raw)
        print(json.dumps(flow.to_dict()), flush=True)

    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        master = await run_proxy(self.addon, self.cfg.proxy_port)
        print(f"[azkaban] The Trace is listening on 127.0.0.1:{self.cfg.proxy_port} "
              f"(CA in ~/.mitmproxy)", file=sys.stderr, flush=True)
        await master.run()
