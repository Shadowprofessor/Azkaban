"""Cross-platform `make security`: static egress check + the full test suite.

    python azkaban-agent/scripts/security.py
"""
import re
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "azkaban_agent"
PATTERN = re.compile(
    r"import requests|from requests|requests\.(get|post|put|request|Session)|httpx|aiohttp|urllib\.request|urlopen|"
    r"http\.client|ftplib|smtplib|socket\.(socket|create_connection)|websockets\.(asyncio\.)?client|"
    r"from websockets\.asyncio\.client|telemetry|sentry|posthog|segment\.io|mixpanel"
)


def egress_check() -> bool:
    bad = []
    for f in sorted(PKG.glob("*.py")):
        if f.name == "net.py":
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if PATTERN.search(line) and "egress-ok:" not in line:
                bad.append(f"{f.name}:{n}: {line.strip()}")
    if bad:
        print("EGRESS CHECK FAILED — network calls outside net.py:\n" + "\n".join(bad))
        return False
    print("egress check OK: only net.py opens outbound connections")
    return True


if __name__ == "__main__":
    ok = egress_check()
    rc = subprocess.call([sys.executable, "-m", "pytest", "-q", str(PKG.parent / "tests")])
    sys.exit(0 if ok and rc == 0 else 1)
