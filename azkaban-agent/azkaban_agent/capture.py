"""mitmproxy addon: emits one raw record per flow, including pinned (undecryptable) ones.

Raw records live in memory only. They carry payload text for the classifier;
the pipeline turns them into redacted `Flow` objects before anything leaves
the agent.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Callable

from mitmproxy import connection, http, options, tls
from mitmproxy.tools import dump

from .blocklist import host_blocked
from .procmap import ProcessResolver
from .safety import require_loopback

MAX_BODY = 64 * 1024
KEEP_HEADERS = ("user-agent", "cookie", "referer", "x-device-id", "x-advertising-id", "authorization",
                "content-type", "x-client-data")

Sink = Callable[[dict], None]


def _peer_port(client: connection.Client) -> int | None:
    try:
        return int(client.peername[1])
    except Exception:
        return None


def _server_ip(server: connection.Server | None) -> str:
    if server is None:
        return ""
    for addr in (server.peername, server.address):
        if addr and addr[0]:
            return str(addr[0])
    return ""


def _duration_ms(flow) -> int:
    try:
        end = flow.response.timestamp_end if flow.response else None
        start = flow.request.timestamp_start
        return max(0, int(((end or start) - start) * 1000))
    except Exception:
        return 0


class CaptureAddon:
    def __init__(self, sink: Sink, resolver: ProcessResolver | None = None):
        self.sink = sink
        self.resolver = resolver or ProcessResolver()
        self.apps: dict[str, str] = {}          # client.id -> app name
        self.pids: dict[str, int] = {}          # client.id -> pid (for the dashboard)
        self.passthrough: set[str] = set()      # hosts that pin certs
        self.blocked: set[str] = set()          # enforced blocklist (Phase 9)
        self.paused = False
        self.on_blocked: Callable[[str], None] | None = None

    # ---------------------------------------------------------- attribution
    async def client_connected(self, client: connection.Client) -> None:
        port = _peer_port(client)
        if port is not None:
            if hasattr(self.resolver, "lookup_pid"):
                name, pid = await asyncio.to_thread(self.resolver.lookup_pid, port)
                self.apps[client.id] = name
                if pid is not None:
                    self.pids[client.id] = pid
            else:
                self.apps[client.id] = await asyncio.to_thread(self.resolver.lookup, port)

    def client_disconnected(self, client: connection.Client) -> None:
        self.apps.pop(client.id, None)
        self.pids.pop(client.id, None)

    def _app(self, client: connection.Client) -> str:
        return self.apps.get(client.id, "unknown")

    def _is_blocked(self, host: str) -> bool:
        return bool(self.blocked) and host_blocked(host, self.blocked)

    def _refuse(self, flow: http.HTTPFlow, host: str) -> None:
        flow.response = http.Response.make(451, b"blocked by azkaban patronus")
        flow.metadata["azk_blocked"] = True
        if self.on_blocked:
            self.on_blocked(host)

    def http_connect(self, flow: http.HTTPFlow) -> None:
        # Blocks the tunnel itself, so pinned apps are covered too.
        if self._is_blocked(flow.request.host):
            self._refuse(flow, flow.request.host)

    # ---------------------------------------------------------- pinning fallback
    def tls_clienthello(self, data: tls.ClientHelloData) -> None:
        sni = data.client_hello.sni or ""
        if sni and sni in self.passthrough:
            # Known pinned host: don't intercept (keeps the app working) but still report it.
            data.ignore_connection = True
            self._emit_metadata(data.context.client, data.context.server, sni)

    def tls_failed_client(self, data: tls.TlsData) -> None:
        client = data.context.client
        sni = client.sni or (data.context.server.address[0] if data.context.server.address else "")
        if sni:
            self.passthrough.add(sni)
        self._emit_metadata(client, data.context.server, sni, error=str(data.conn.error or ""))

    def _emit_metadata(self, client, server, host: str, error: str = "") -> None:
        if self.paused:
            return
        self.sink({
            "id": uuid.uuid4().hex,
            "ts": int(time.time() * 1000),
            "app": self._app(client),
            "host": host,
            "method": "CONNECT",
            "path": "",
            "ip": _server_ip(server),
            "bytes": 0,
            "decrypted": False,
            "headers": {},
            "query": "",
            "body": "",
            "note": error[:200],
        })

    # ---------------------------------------------------------- decrypted flows
    def request(self, flow: http.HTTPFlow) -> None:
        if self._is_blocked(flow.request.pretty_host):
            self._refuse(flow, flow.request.pretty_host)

    def response(self, flow: http.HTTPFlow) -> None:
        self._emit_http(flow)

    def error(self, flow: http.HTTPFlow) -> None:
        if flow.response is None:
            self._emit_http(flow)

    def _emit_http(self, flow: http.HTTPFlow) -> None:
        if self.paused or flow.metadata.get("azk_blocked"):
            return
        req = flow.request
        body = req.get_text(strict=False) or ""
        if len(body) > MAX_BODY:
            body = body[:MAX_BODY]
        resp_len = len(flow.response.raw_content or b"") if flow.response else 0
        self.sink({
            "id": uuid.uuid4().hex,
            "ts": int(req.timestamp_start * 1000),
            "app": self._app(flow.client_conn),
            "host": req.pretty_host,
            "method": req.method,
            "path": req.path.split("?", 1)[0],
            "ip": _server_ip(flow.server_conn),
            "bytes": len(req.raw_content or b"") + resp_len,
            # Direction, protocol and duration as mitmproxy measured them, for the
            # dashboard's traffic view. Sizes only; no content.
            "up": len(req.raw_content or b""),
            "down": resp_len,
            "proto": str(getattr(req, "http_version", "") or "")[:16],
            "dur_ms": _duration_ms(flow),
            "pid": self.pids.get(flow.client_conn.id),
            "decrypted": True,
            "headers": {k: v for k, v in req.headers.items() if k.lower() in KEEP_HEADERS},
            "query": req.path.split("?", 1)[1] if "?" in req.path else "",
            "body": body,
            "note": "",
            # Response metadata for the tracker classifier's request-structure features.
            "resp_type": (flow.response.headers.get("content-type", "") if flow.response else "")[:100],
            "status": flow.response.status_code if flow.response else 0,
            "samesite_none": any("samesite=none" in v.lower() for v in flow.response.headers.get_all("set-cookie"))
                             if flow.response else None,
        })


def _upstream_spec(upstream: str) -> tuple[str, str]:
    """Split an upstream proxy URL into a mitmproxy mode spec and basic-auth credentials.

    Accepts "host:port", "http://host:port" and "http://user:pass@host:port". Credentials
    are URL-decoded, since a proxy password with reserved characters arrives percent-encoded
    in the environment.
    """
    from urllib.parse import unquote, urlsplit

    raw = upstream.strip()
    if "://" not in raw:
        raw = f"http://{raw}"
    parts = urlsplit(raw)
    host = parts.hostname or "127.0.0.1"
    port = f":{parts.port}" if parts.port else ""
    auth = ""
    if parts.username:
        auth = f"{unquote(parts.username)}:{unquote(parts.password or '')}"
    return f"{parts.scheme}://{host}{port}", auth


async def run_proxy(addon: CaptureAddon, port: int, host: str = "127.0.0.1",
                    upstream: str = "") -> dump.DumpMaster:
    """Start mitmproxy bound to loopback only. Returns the running master.

    `upstream` chains to another HTTP proxy (AZK_UPSTREAM_PROXY), for machines whose
    internet access already goes through one. Without it mitmproxy dials destinations
    directly, and on such a machine every captured request fails. This forwards the user's
    own traffic onward; it is not the agent originating a connection, so it is outside
    net.py's remit the same way ordinary mitmproxy forwarding is.
    """
    host = require_loopback(host, "proxy")
    opts = options.Options()
    master = dump.DumpMaster(opts, with_termlog=False, with_dumper=False)
    opts.update(listen_host=host, listen_port=port)
    if upstream:
        spec, auth = _upstream_spec(upstream)
        opts.update(mode=[f"upstream:{spec}"])
        if auth:
            # mitmproxy refuses credentials inside the mode URL; they go here instead.
            opts.update(upstream_auth=auth)
    master.addons.add(addon)
    return master
