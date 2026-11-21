"""Passive visibility of traffic that bypasses the proxy.

Two sources, both read-only and in-memory:
  1. OS DNS cache (Windows `Get-DnsClientCache`; needs elevation on some systems).
  2. The connection table (psutil): established sockets per process to public IPs
     that do NOT go through our proxy. Works without admin.
"""
from __future__ import annotations

import ipaddress
import json
import os
import subprocess
import sys
from collections import defaultdict

import psutil


def _public(ip: str) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (a.is_private or a.is_loopback or a.is_link_local or a.is_multicast or a.is_unspecified)


def read_dns_cache() -> dict[str, str]:
    """ip -> hostname from the OS resolver cache (best effort)."""
    if sys.platform != "win32":
        return {}
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-DnsClientCache -ErrorAction SilentlyContinue | Where-Object {$_.Type -in 1,28} | "
             "Select-Object Entry,Data | ConvertTo-Json -Compress"],
            capture_output=True, text=True, timeout=8,
        ).stdout.strip()
        if not out:
            return {}
        rows = json.loads(out)
        rows = rows if isinstance(rows, list) else [rows]
        return {r["Data"]: r["Entry"] for r in rows if r.get("Data") and r.get("Entry")}
    except Exception:
        return {}


class NetWatch:
    def __init__(self, proxy_port: int):
        self.proxy_port = proxy_port
        self.me = os.getpid()
        self.ip_host: dict[str, str] = {}      # learned from proxied flows + DNS cache
        self.proxied_apps: set[str] = set()
        self.dns_source = False

    def learn(self, ip: str, host: str, app: str) -> None:
        if ip and host:
            self.ip_host[ip] = host
        if app:
            self.proxied_apps.add(app)

    def scan(self) -> dict[str, list[dict]]:
        """app -> [{ip, port, host}] for direct (non-proxied) connections to the internet."""
        dns = read_dns_cache()
        if dns:
            self.dns_source = True
            self.ip_host.update(dns)
        by_app: dict[str, dict[tuple, dict]] = defaultdict(dict)
        names: dict[int, str] = {}
        try:
            conns = psutil.net_connections(kind="inet")
        except (psutil.AccessDenied, OSError):
            return {}
        for c in conns:
            if c.status != psutil.CONN_ESTABLISHED or not c.raddr or not c.pid or c.pid == self.me:
                continue
            ip, port = c.raddr.ip, c.raddr.port
            if not _public(ip) or port == self.proxy_port:
                continue
            if c.pid not in names:
                try:
                    names[c.pid] = psutil.Process(c.pid).name().removesuffix(".exe")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    names[c.pid] = f"pid:{c.pid}"
            by_app[names[c.pid]][(ip, port)] = {"ip": ip, "port": port, "host": self.ip_host.get(ip, "")}
        return {app: list(v.values()) for app, v in by_app.items()}
