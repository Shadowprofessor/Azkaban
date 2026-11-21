"""End-to-end consistency check for the unknown_tracker insight (agent + website + extension).

    python scripts/check_unknown_tracker.py --out unknown_expected.json
    (then, on the Chromium-extension branch)  node azkaban-extension/e2e/insight_parity.mjs unknown_expected.json

1. Replays demo.azk through the real Agent and captures the unknown_tracker insight it emits.
2. Writes that insight together with the exact page observations the agent used, so the
   extension can classify the SAME observations and must produce byte-identical JSON.
See scripts/check_unknown_tracker.md for the dashboard step.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "azkaban-agent"))

from azkaban_agent.agent import Agent  # noqa: E402
from azkaban_agent.config import Config  # noqa: E402
from azkaban_agent.session import read_session  # noqa: E402

DEMO = ROOT / "azkaban-agent" / "demo" / "demo.azk"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="unknown_expected.json")
    a = ap.parse_args()
    agent = Agent(Config(), mode="replay")
    agent.hub.publish = lambda m, keep=True: None
    for r in read_session(DEMO):
        agent.on_raw(dict(r))
    msgs = [m for m in agent._ml_insights() if m.get("kind") == "unknown_tracker"]
    if not msgs:
        print("FAIL: agent emitted no unknown_tracker insight on the demo replay")
        return 1
    m = msgs[0]
    dom = m["data"]["domain"]
    pages = [{**p, "types": sorted(p["types"])} for p in agent.tracker_clf.pages[dom]]
    Path(a.out).write_text(json.dumps({"domain": dom, "pages": pages, "insight": m}, separators=(",", ":")))
    print(f"(1) agent emitted unknown_tracker for {dom}: {json.dumps(m)}")
    print(f"    wrote {a.out} — now run the extension parity script on it")
    return 0


if __name__ == "__main__":
    sys.exit(main())
