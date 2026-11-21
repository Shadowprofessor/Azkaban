"""Tiny dashboard stand-in: connects to the agent and prints every message with latency.

    python azkaban-agent/scripts/ws_probe.py [seconds]
"""
import asyncio
import json
import sys
import time

from websockets.asyncio.client import connect


async def main(seconds: float) -> None:
    async with connect("ws://127.0.0.1:8787") as ws:
        end = time.time() + seconds
        while time.time() < end:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, end - time.time()))
            except asyncio.TimeoutError:
                break
            msg = json.loads(raw)
            lat = ""
            if msg.get("type") == "flow":
                lat = f" latency={int(time.time()*1000) - msg['flow']['ts']}ms"
            print(msg["type"] + lat, json.dumps(msg), flush=True)


if __name__ == "__main__":
    asyncio.run(main(float(sys.argv[1]) if len(sys.argv) > 1 else 10))
