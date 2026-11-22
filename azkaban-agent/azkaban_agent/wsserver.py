"""WebSocket hub on 127.0.0.1 speaking lib/live/protocol.ts.

Capture never blocks on a slow socket: each client has a bounded queue
(oldest dropped when full) drained by its own sender task in ~50ms batches.
"""
from __future__ import annotations

import asyncio
import json
import logging
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

# A Chrome extension's origin is chrome-extension://<32 chars a-p>. The id changes on every
# unpacked reload, so it cannot be pinned without making the user copy a token around.
# This is acceptable ONLY because the extension path is producer-only: see extbridge.py.
# Consumer paths (the dashboard) never accept this origin.
EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")
ALL_ORIGINS = LOCAL_ORIGINS + [EXTENSION_ORIGIN]

#: Producer path for the browser extension. Everything else is a dashboard consumer.
EXTENSION_PATH = "/ws/extension"


def _path_of(ws) -> str:
    """Request path, defensively: a client may omit it and the library version varies."""
    try:
        return (ws.request.path or "/").split("?")[0].rstrip("/") or "/"
    except Exception:
        return "/"


def _origin_of(ws) -> str:
    try:
        return ws.request.headers.get("Origin", "") or ""
    except Exception:
        return ""

CommandHandler = Callable[[dict], Awaitable[None]]


class Hub:
    def __init__(self, status_fn: Callable[[], dict], on_command: CommandHandler | None = None,
                 extension=None):
        self.status_fn = status_fn
        self.on_command = on_command
        self.extension = extension        # extbridge.ExtensionBridge, or None to refuse producers
        self.history_provider = None      # () -> list[dict]: past flows replayed to new clients
        self.clients: dict[ServerConnection, asyncio.Queue] = {}
        self.history: deque[str] = deque(maxlen=HISTORY)
        self.last_score: str | None = None
        self.insights: dict[str, str] = {}

    # --------------------------------------------------------------- publish
    def publish(self, msg: dict, keep: bool = True) -> None:
        """Non-blocking; safe to call from the capture path."""
        data = json.dumps(msg, separators=(",", ":"))
        if keep and msg.get("type") in ("flow", "verdict"):
            self.history.append(data)
        if msg.get("type") == "score":
            self.last_score = data
        elif msg.get("type") == "insight":
            self.insights[msg["key"]] = data
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
        """Route by path: producers to the extension bridge, everyone else to the feed."""
        path, origin = _path_of(ws), _origin_of(ws)
        is_ext_origin = bool(EXTENSION_ORIGIN.match(origin))
        if path == EXTENSION_PATH:
            if self.extension is None:
                await ws.close(1011, "extension bridge not enabled")
                return
            await self.extension.handle(ws)
            return
        if is_ext_origin:
            # An extension asking for the consumer feed. Refused: that path streams flows
            # and PII, and the permissive extension origin check is only safe one way.
            await ws.close(4003, "extensions may only connect to /ws/extension")
            return
        await self.consumer(ws)

    async def consumer(self, ws: ServerConnection) -> None:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAX)
        await ws.send(json.dumps(self.status_fn()))
        # Durable history first, so the view starts with what already happened.
        if self.history_provider is not None:
            try:
                for msg in self.history_provider():
                    if q.full():
                        break
                    q.put_nowait(json.dumps(msg, separators=(",", ":")))
            except Exception:
                pass
        for data in list(self.history):
            q.put_nowait(data) if not q.full() else None
        if self.last_score:
            q.put_nowait(self.last_score)
        for data in list(self.insights.values()):
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
    # Port probes / aborted handshakes are not errors worth a traceback.
    logging.getLogger("websockets.server").setLevel(logging.CRITICAL)
    # Extension origins are allowed at the transport layer and then confined to the
    # producer path by Hub.handler.
    origins = ALL_ORIGINS if hub.extension is not None else LOCAL_ORIGINS
    return await serve(hub.handler, host, port, origins=origins)
