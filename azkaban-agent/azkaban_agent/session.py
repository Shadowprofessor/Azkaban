""".azk session files: newline-delimited JSON of raw capture records.

Line 1 is a header: {"azk": 1, "created": <ms>, "source": "live"|"synthetic"}.
Recording is opt-in (`--record FILE`) because the file holds your unredacted
traffic. Replay feeds the records back through the same pipeline and protocol.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Callable, Iterator


class Recorder:
    def __init__(self, path: str | Path, source: str = "live"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "w", encoding="utf-8", buffering=1)  # line-buffered: survives a crash
        self.f.write(json.dumps({"azk": 1, "created": int(time.time() * 1000), "source": source}) + "\n")
        self.count = 0
        print(f"[azkaban] recording to {self.path} — this file contains UNREDACTED traffic; "
              "keep it private.", file=sys.stderr, flush=True)

    def write(self, raw: dict) -> None:
        self.f.write(json.dumps(raw, separators=(",", ":")) + "\n")
        self.count += 1

    def close(self) -> None:
        self.f.flush()
        self.f.close()


def read_session(path: str | Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if i == 0 and "azk" in obj:
                continue
            yield obj


def read_header(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as f:
        first = json.loads(f.readline() or "{}")
    return first if "azk" in first else {}


def parse_speed(s: str) -> float:
    s = str(s).strip().lower().rstrip("x")
    v = float(s)
    if v <= 0:
        raise ValueError("speed must be > 0")
    return v


async def replay(path: str | Path, emit: Callable[[dict], None], speed: float = 1.0,
                 loop_forever: bool = False, max_gap: float = 3.0,
                 should_run: Callable[[], bool] = lambda: True) -> int:
    """Re-emit records with original pacing / speed. Timestamps are shifted to now and
    ids regenerated so the dashboard sees them as fresh flows. Gaps are capped at max_gap s."""
    records = list(read_session(path))
    if not records:
        return 0
    sent = 0
    while True:
        prev = records[0]["ts"]
        for r in records:
            gap = min(max(0, r["ts"] - prev) / 1000 / speed, max_gap)
            prev = r["ts"]
            if gap:
                await asyncio.sleep(gap)
            while not should_run():
                await asyncio.sleep(0.2)
            rec = dict(r)
            rec["id"] = uuid.uuid4().hex
            rec["orig_ts"] = r["ts"]  # recorded time: keeps page grouping identical at any replay speed
            rec["ts"] = int(time.time() * 1000)
            rec["replayed"] = True
            emit(rec)
            sent += 1
        if not loop_forever:
            return sent
        await asyncio.sleep(1.0)
