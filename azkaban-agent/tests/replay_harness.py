"""Runs the real agent over demo.azk (WebSocket server, pipeline, legal worker, evidence
export, a WebSocket client) and records every message it emits."""
from __future__ import annotations

import asyncio
import json
import socket
import tempfile
from pathlib import Path

from websockets.asyncio.client import connect

from azkaban_agent.agent import Agent
from azkaban_agent.config import Config

DEMO = Path(__file__).resolve().parents[1] / "demo" / "demo.azk"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


async def _run(out_dir: Path) -> dict:
    cfg = Config()
    cfg.ws_port = free_port()
    cfg.ollama_url = f"http://127.0.0.1:{free_port()}"   # closed loopback port: LLM path runs, fails fast
    agent = Agent(cfg, mode="replay")
    published: list[str] = []
    orig = agent.hub.publish

    def spy(msg, keep=True):
        published.append(json.dumps(msg))
        orig(msg, keep)

    agent.hub.publish = spy
    task = asyncio.create_task(agent.run_replay(str(DEMO), speed=2000.0, loop_forever=False, wait_client=0))
    received: list[str] = []
    for _ in range(100):
        await asyncio.sleep(0.05)
        if agent.hub is not None and agent.verdict_q is not None:
            try:
                ws = await connect(f"ws://127.0.0.1:{cfg.ws_port}")
                break
            except OSError:
                continue
    else:
        raise RuntimeError("agent socket never came up")
    async with ws:
        for _ in range(200):
            await asyncio.sleep(0.05)
            if agent.flow_count >= 38 and not agent.capturing:
                break
        await ws.send(json.dumps({"type": "blocklist", "action": "apply"}))
        await asyncio.sleep(1.5)
        agent.evidence_dir = out_dir
        await ws.send(json.dumps({"type": "export_evidence"}))
        await asyncio.sleep(2.5)   # score/insight loops tick
        try:
            while True:
                received.append(await asyncio.wait_for(ws.recv(), 0.3))
        except (asyncio.TimeoutError, Exception):
            pass
    task.cancel()
    try:
        await task
    except (asyncio.CancelledError, Exception):
        pass
    evidence_files = [p.read_text(encoding="utf-8", errors="replace") for p in out_dir.glob("*.jsonl")]
    return {"agent": agent, "published": published, "received": received, "evidence": evidence_files}


def run_demo() -> dict:
    out = Path(tempfile.mkdtemp(prefix="azk-evidence-"))
    return asyncio.run(_run(out))
