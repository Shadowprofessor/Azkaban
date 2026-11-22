"""Run from anywhere: put the repo root on sys.path so `import ghostprint` resolves."""
import sys
from pathlib import Path

ROOT = str(Path(__file__).resolve().parents[2])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
