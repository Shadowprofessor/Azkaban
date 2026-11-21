"""Agent runtime: wires capture -> pipeline -> outputs on one asyncio loop."""
from __future__ import annotations

import asyncio
import sys

from . import __version__
from .capture import CaptureAddon, run_proxy
from .config import Config
from .pipeline import Pipeline
from .wsserver import Hub, start_ws


class Agent:
    def __init__(self, cfg: Config, mode: str = "live"):
        self.cfg = cfg
        self.mode = mode
        self.loop: asyncio.AbstractEventLoop | None = None
        self.addon = CaptureAddon(self._on_raw_threadsafe)
        self.hub = Hub(self.status, self.on_command)
        self.pipeline = Pipeline(cfg)
        self.flow_count = 0
        self.capturing = True

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        return {
            "type": "status",
            "capturing": self.capturing,
            "mode": self.mode if self.capturing else "idle",
            "proxy": f"127.0.0.1:{self.cfg.proxy_port}" if self.mode == "live" else "",
            "flows": self.flow_count,
            "engines": {"llm": False, "rag": False, "model": False, "geo": self.pipeline.geo.available},
            "version": __version__,
        }

    # ------------------------------------------------------------------ ingest
    def _on_raw_threadsafe(self, raw: dict) -> None:
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.on_raw, raw)
        else:
            self.on_raw(raw)

    def on_raw(self, raw: dict) -> None:
        if not self.capturing:
            return
        try:
            enriched = self.pipeline.process(raw)
        except Exception as e:  # never crash capture on one bad flow
            self.hub.error("pipeline", f"{type(e).__name__}: {e}")
            return
        self.flow_count += 1
        self.hub.publish({"type": "flow", "flow": enriched.flow.to_dict()})

    # ------------------------------------------------------------------ commands
    async def on_command(self, cmd: dict) -> None:
        t = cmd["type"]
        if t == "start":
            self.capturing = True
            self.addon.paused = False
        elif t == "stop":
            self.capturing = False
            self.addon.paused = True
        else:
            self.hub.error("unsupported", f"command '{t}' is not available yet")
            return
        self.hub.broadcast_status()

    # ------------------------------------------------------------------ run
    async def run(self) -> None:
        self.loop = asyncio.get_running_loop()
        ws = await start_ws(self.hub, self.cfg.ws_port)
        print(f"[azkaban] dashboard socket ws://127.0.0.1:{self.cfg.ws_port}", file=sys.stderr, flush=True)
        try:
            master = await run_proxy(self.addon, self.cfg.proxy_port)
            print(f"[azkaban] The Trace is listening on 127.0.0.1:{self.cfg.proxy_port} "
                  f"(CA in ~/.mitmproxy)", file=sys.stderr, flush=True)
            await master.run()
        finally:
            ws.close()
