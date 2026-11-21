"""Shared tracker-classifier features (training side).

The implementation lives in azkaban_agent/tracker_features.py so the agent can import it at
runtime without the train/ directory; this module re-exports it so training and runtime use
byte-identical feature code.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "azkaban-agent"))

from azkaban_agent.tracker_features import *  # noqa: E402,F401,F403
from azkaban_agent.tracker_features import (  # noqa: E402,F401
    AVAILABILITY, BEHAVIOURAL, DEPLOYED, GLOBAL_ONLY, LEXICAL, STRUCTURAL, WTM_COLUMNS,
    behaviour_from_pages, behaviour_from_wtm, group_key, lexical, registrable, vector,
)
