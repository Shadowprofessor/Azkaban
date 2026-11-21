"""Agent runtime: wires capture/replay -> pipeline -> outputs on one asyncio loop."""
from __future__ import annotations

import asyncio
import sys

from . import __version__
from .config import Config
from .pipeline import Pipeline
from .idle import IdleDetector
from .insights import InsightEngine
from .netwatch import NetWatch
from .score import ExposureScore
from .session import Recorder, read_header, replay
from .wsserver import Hub, start_ws


def log(msg: str) -> None:
    print(f"[azkaban] {msg}", file=sys.stderr, flush=True)


class Agent:
    def __init__(self, cfg: Config, mode: str = "live", record: str | None = None):
        self.cfg = cfg
        self.mode = mode
        self.loop: asyncio.AbstractEventLoop | None = None
        self.hub = Hub(self.status, self.on_command)
        self.pipeline = Pipeline(cfg)
        self.exposure = ExposureScore()
        self.insights = InsightEngine()
        self.idle = IdleDetector() if mode == "live" else None
        self.netwatch = NetWatch(cfg.proxy_port) if mode == "live" else None
        self.recorder = Recorder(record) if record else None
        self.addon = None
        if mode == "live":
            from .capture import CaptureAddon
            self.addon = CaptureAddon(self._on_raw_threadsafe)
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
            "engines": {"llm": False, "rag": False, "model": self.pipeline.severity.available, "geo": self.pipeline.geo.available},
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
        if self.idle is not None and "tsi" not in raw:
            raw["tsi"] = round(self.idle.seconds() or 0.0, 1)
        if self.recorder:
            self.recorder.write(raw)
        try:
            enriched = self.pipeline.process(raw)
        except Exception as e:  # never crash capture on one bad flow
            self.hub.error("pipeline", f"{type(e).__name__}: {e}")
            return
        self.flow_count += 1
        self.exposure.add(self.pipeline.fact(enriched))
        self.hub.publish({"type": "flow", "flow": enriched.flow.to_dict()})
        if self.netwatch:
            f = enriched.flow
            self.netwatch.learn(f.ip, f.host, f.app)
        for msg in self.insights.on_flow(enriched):
            self.hub.publish(msg)

    # ------------------------------------------------------------------ commands
    async def on_command(self, cmd: dict) -> None:
        t = cmd["type"]
        if t == "start":
            self.capturing = True
            if self.addon:
                self.addon.paused = False
        elif t == "stop":
            self.capturing = False
            if self.addon:
                self.addon.paused = True
        else:
            self.hub.error("unsupported", f"command '{t}' is not available yet")
            return
        self.hub.broadcast_status()

    # ------------------------------------------------------------------ run
    async def _score_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            if self.exposure.dirty:
                try:
                    self.hub.publish(self.exposure.message(), keep=False)
                except Exception as e:
                    self.hub.error("score", str(e))

    async def _insight_loop(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(2.0)
            tick += 1
            bypass = None
            if self.netwatch and tick % 5 == 0:   # every ~10s, off the event loop
                try:
                    bypass = await asyncio.to_thread(self.netwatch.scan)
                except Exception:
                    bypass = None
            for msg in self.insights.periodic(bypass):
                self.hub.publish(msg)

    async def _serve_ws(self):
        self._bg = [asyncio.create_task(self._score_loop()), asyncio.create_task(self._insight_loop())]
        ws = await start_ws(self.hub, self.cfg.ws_port)
        log(f"dashboard socket ws://127.0.0.1:{self.cfg.ws_port}")
        return ws

    async def run(self) -> None:
        from .capture import run_proxy
        self.loop = asyncio.get_running_loop()
        ws = await self._serve_ws()
        try:
            master = await run_proxy(self.addon, self.cfg.proxy_port)
            log(f"The Trace is listening on 127.0.0.1:{self.cfg.proxy_port} (CA in ~/.mitmproxy)")
            await master.run()
        finally:
            ws.close()
            if self.recorder:
                self.recorder.close()

    async def run_replay(self, path: str, speed: float, loop_forever: bool, wait_client: float) -> None:
        self.loop = asyncio.get_running_loop()
        self.session_header = read_header(path)
        ident = self.session_header.get("identity") or {}
        self.pipeline.identity.add_many(ident.get("emails", []), ident.get("phones", []), ident.get("adids", []))
        ws = await self._serve_ws()
        try:
            # Give the dashboard a moment to connect so it sees the whole story.
            waited = 0.0
            while not self.hub.clients and waited < wait_client:
                await asyncio.sleep(0.25)
                waited += 0.25
            log(f"replaying {path} at {speed}x")
            n = await replay(path, self.on_raw, speed=speed, loop_forever=loop_forever,
                             should_run=lambda: self.capturing)
            log(f"replay finished: {n} flows. Socket stays up; Ctrl+C to exit.")
            self.capturing = False
            self.hub.broadcast_status()
            await asyncio.Event().wait()
        finally:
            ws.close()
