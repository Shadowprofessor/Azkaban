#!/usr/bin/env bash
# Fails if any agent module other than net.py can open an outbound connection.
# A line may opt out only with an explicit "# egress-ok: <reason>" comment.
set -u
cd "$(dirname "$0")/../azkaban_agent" || exit 2
PATTERN='import requests|from requests|requests\.(get|post|put|request|Session)|httpx|aiohttp|urllib\.request|urlopen|http\.client|ftplib|smtplib|socket\.(socket|create_connection)|websockets\.(asyncio\.)?client|from websockets\.asyncio\.client|telemetry|sentry|posthog|segment\.io|mixpanel'
hits=$(grep -nE "$PATTERN" ./*.py | grep -v '^./net.py:' | grep -v 'egress-ok:' || true)
if [ -n "$hits" ]; then
  echo "EGRESS CHECK FAILED — network calls outside net.py:"
  echo "$hits"
  exit 1
fi
echo "egress check OK: only net.py opens outbound connections"
