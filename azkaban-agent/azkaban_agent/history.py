"""On-disk flow history, so a session's findings outlive the process.

Everything else in the agent is in memory: the hub keeps the last 500 messages, the
dashboard keeps 2000 flows in a tab, and the extension keeps its own in storage.session.
Close any of them and the record is gone. This keeps a durable copy so "what did my apps
do yesterday" has an answer.

Stored per flow: the redacted Flow the dashboard already receives, nothing more. PII hits
are stored exactly as they are emitted (already redacted by pii.py); raw values never
reach here, which `test_history.py` asserts. Bodies are never stored.

SQLite because it ships with Python, survives a crash mid-write, and lets the dashboard
ask for a time range without loading everything. The file lives under the repo's evidence/
directory alongside the other operator-visible artefacts, and the user can delete it at
any time -- `azkaban history --forget` does it for them.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_KEEP_DAYS = 30
#: Written in batches: one commit per flow would fsync on every request.
FLUSH_EVERY = 25
FLUSH_SECONDS = 2.0


class FlowHistory:
    """Append-only flow log with a retention window. Safe to call from the capture path."""

    def __init__(self, path: Path, keep_days: int = DEFAULT_KEEP_DAYS, enabled: bool = True):
        self.path = Path(path)
        self.keep_days = max(0, int(keep_days))
        self.enabled = enabled
        self._lock = threading.Lock()
        self._pending: list[tuple] = []
        self._last_flush = time.monotonic()
        self._db: sqlite3.Connection | None = None
        self.session_id = f"{int(time.time())}-{id(self):x}"
        if self.enabled:
            self._open()

    # ------------------------------------------------------------------ setup
    def _open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")      # survives a crash mid-write
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS flows (
                id TEXT PRIMARY KEY, ts INTEGER NOT NULL, session TEXT NOT NULL,
                app TEXT, host TEXT, company TEXT, country TEXT,
                severity INTEGER, pii_count INTEGER, tracker INTEGER,
                flow TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS flows_ts ON flows(ts);
            CREATE INDEX IF NOT EXISTS flows_host ON flows(host);
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        """)
        self._db.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema', ?)",
                         (str(SCHEMA_VERSION),))
        self._db.commit()
        self.purge()

    # ------------------------------------------------------------------ writing
    def add(self, flow: dict) -> None:
        """Queue one redacted flow. Never raises: history must not break capture."""
        if not self.enabled or self._db is None or not isinstance(flow, dict):
            return
        try:
            row = (
                str(flow.get("id", "")), int(flow.get("ts", 0)), self.session_id,
                str(flow.get("app", ""))[:128], str(flow.get("host", ""))[:255],
                str(flow.get("company", ""))[:128], str(flow.get("country", ""))[:8],
                int(flow.get("severity", 0) or 0), len(flow.get("pii") or []),
                1 if flow.get("tracker") else 0, json.dumps(flow, separators=(",", ":")),
            )
        except (AttributeError, TypeError, ValueError):
            return      # one bad flow must never break capture
        with self._lock:
            self._pending.append(row)
            due = (len(self._pending) >= FLUSH_EVERY
                   or time.monotonic() - self._last_flush >= FLUSH_SECONDS)
        if due:
            self.flush()

    def flush(self) -> int:
        if not self.enabled or self._db is None:
            return 0
        with self._lock:
            batch, self._pending = self._pending, []
            self._last_flush = time.monotonic()
        if not batch:
            return 0
        try:
            self._db.executemany(
                "INSERT OR REPLACE INTO flows"
                "(id, ts, session, app, host, company, country, severity, pii_count, tracker, flow)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?)", batch)
            self._db.commit()
        except sqlite3.Error:
            return 0
        return len(batch)

    # ------------------------------------------------------------------ reading
    def recent(self, limit: int = 500, *, since_ms: int | None = None,
               host: str | None = None, min_severity: int = 0,
               pii_only: bool = False) -> list[dict]:
        """Most recent flows first, as the same dicts the dashboard already renders."""
        if not self.enabled or self._db is None:
            return []
        self.flush()
        where, args = ["1=1"], []
        if since_ms is not None:
            where.append("ts >= ?")
            args.append(int(since_ms))
        if host:
            where.append("host LIKE ?")
            args.append(f"%{host}%")
        if min_severity:
            where.append("severity >= ?")
            args.append(int(min_severity))
        if pii_only:
            where.append("pii_count > 0")
        args.append(max(1, min(int(limit), 5000)))
        try:
            rows = self._db.execute(
                f"SELECT flow FROM flows WHERE {' AND '.join(where)} ORDER BY ts DESC LIMIT ?",
                args).fetchall()
        except sqlite3.Error:
            return []
        out = []
        for (raw,) in rows:
            try:
                out.append(json.loads(raw))
            except ValueError:
                continue
        return out

    def stats(self) -> dict:
        if not self.enabled or self._db is None:
            return {"enabled": False, "flows": 0, "sessions": 0, "oldest": None, "newest": None}
        self.flush()
        try:
            n, oldest, newest, sessions = self._db.execute(
                "SELECT COUNT(*), MIN(ts), MAX(ts), COUNT(DISTINCT session) FROM flows").fetchone()
            leaks = self._db.execute("SELECT COUNT(*) FROM flows WHERE pii_count > 0").fetchone()[0]
        except sqlite3.Error:
            return {"enabled": True, "flows": 0, "sessions": 0, "oldest": None, "newest": None}
        return {"enabled": True, "flows": n or 0, "sessions": sessions or 0,
                "oldest": oldest, "newest": newest, "withPii": leaks or 0,
                "path": str(self.path), "keepDays": self.keep_days}

    # ------------------------------------------------------------------ retention
    def purge(self) -> int:
        """Drop anything past the retention window. keep_days=0 keeps everything."""
        if not self.enabled or self._db is None or not self.keep_days:
            return 0
        cutoff = int((time.time() - self.keep_days * 86400) * 1000)
        try:
            removed = self._db.execute("DELETE FROM flows WHERE ts < ?", (cutoff,)).rowcount
            self._db.commit()
        except sqlite3.Error:
            return 0
        return max(0, removed)

    def forget_all(self) -> int:
        """Delete every stored flow. The user's data, the user's call."""
        if self._db is None:
            return 0
        with self._lock:
            queued = len(self._pending)     # count these too: the user asked for everything
            self._pending.clear()
        try:
            n = queued + self._db.execute("SELECT COUNT(*) FROM flows").fetchone()[0]
            self._db.execute("DELETE FROM flows")
            self._db.commit()          # commit BEFORE vacuum: it cannot run in a transaction
        except sqlite3.Error:
            return 0
        try:
            # Reclaim the file so the deleted rows are not still readable on disk. Needs
            # autocommit; a failure here leaves the rows deleted, just not compacted.
            level = self._db.isolation_level
            self._db.isolation_level = None
            self._db.execute("VACUUM")
            self._db.isolation_level = level
        except sqlite3.Error:
            pass
        return n

    def close(self) -> None:
        self.flush()
        if self._db is not None:
            try:
                self._db.close()
            finally:
                self._db = None
