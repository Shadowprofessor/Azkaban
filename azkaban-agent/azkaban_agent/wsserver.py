"""WebSocket hub on 127.0.0.1 speaking lib/live/protocol.ts.

Capture never blocks on a slow socket: each client has a bounded queue
(oldest dropped when full) drained by its own sender task in ~50ms batches.
"""
from __future__ import annotations

import asyncio
import json
import re
from collections import deque
from typing import Awaitable, Callable

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from .safety import require_loopback

BATCH_INTERVAL = 0.05
QUEUE_MAX = 2000
HISTORY = 500

# Only local pages may connect (blocks drive-by websites reading your traffic).
LOCAL_ORIGINS = [re.compile(r"^https?://(localhost|127\.0\.0\.1|\[::1\])(:\d+)?$"), None]

CommandHandler = Callable[[dict], Awaitable[None]]


class Hub:
    def __init__(self, status_fn: Callable[[], dict], on_command: CommandHandler | None = None):
        self.status_fn = status_fn
        self.on_command = on_command
        self.clients: dict[ServerConnection, asyncio.Queue] = {}
        self.history: deque[str] = deque(maxlen=HISTORY)

    # --------------------------------------------------------------- publish
    def publish(self, msg: dict, keep: bool = True) -> None:
        """Non-blocking; safe to call from the capture path."""
        data = json.dumps(msg, separators=(",", ":"))
        if keep and msg.get("type") in ("flow", "verdict"):
            self.history.append(data)
        for q in self.clients.values():
            if q.full():
                try:
                    q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(data)

    def broadcast_status(self) -> None:
        self.publish(self.status_fn(), keep=False)

    def error(self, code: str, message: str) -> None:
        self.publish({"type": "error", "code": code, "message": message}, keep=False)

    # --------------------------------------------------------------- per-client
    async def _sender(self, ws: ServerConnection, q: asyncio.Queue) -> None:
        while True:
            first = await q.get()
            await asyncio.sleep(BATCH_INTERVAL)   # let a batch accumulate
            batch = [first]
            while not q.empty():
                batch.append(q.get_nowait())
            for data in batch:
                await ws.send(data)

    async def handler(self, ws: ServerConnection) -> None:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        await ws.send(json.dumps(self.status_fn()))
        for data in list(self.history):
            q.put_nowait(data) if not q.full() else None
        self.clients[ws] = q
        sender = asyncio.create_task(self._sender(ws, q))
        try:
            async for raw in ws:
                try:
                    cmd = json.loads(raw)
                    if not isinstance(cmd, dict) or not isinstance(cmd.get("type"), str):
                        raise ValueError("message must be an object with a string 'type'")
                except ValueError as e:
                    await ws.send(json.dumps({"type": "error", "code": "bad_request", "message": str(e)}))
                    continue
                if self.on_command:
                    try:
                        await self.on_command(cmd)
                    except Exception as e:  # never let one command kill the socket
                        await ws.send(json.dumps({"type": "error", "code": "command_failed",
                                                  "message": f"{cmd.get('type')}: {e}"}))
        except ConnectionClosed:
            pass
        finally:
            self.clients.pop(ws, None)
            sender.cancel()


async def start_ws(hub: Hub, port: int, host: str = "127.0.0.1"):
    host = require_loopback(host, "websocket")
    return await serve(hub.handler, host, port, origins=LOCAL_ORIGINS)
