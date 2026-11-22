import argparse
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from .audit import audit
from .cases import BY_CASE
from .demo import write_demo
from .evaluation import evaluate
from .model import MODEL, NVIDIA_URL, bridge_rank
from .archive_signals import KNOWN_PLATFORMS
from .retrieval import BY_ID, retrieve
from .server import bridge, dashboard


def write_json(data, path=None):
    output = json.dumps(data, indent=2) + "\n"
    if path:
        Path(path).write_text(output, encoding="utf-8")
    else:
        print(output, end="")


def load_env():
    """Read the repo-root .env, the same file the agent uses.

    NVIDIA_API_KEY from .env wins over an inherited environment value: a stale key in the
    Windows user environment otherwise shadows the one the user just set (seen in practice).
    """
    root = Path(__file__).resolve().parent.parent
    for path in (Path.cwd() / ".env", root / ".env"):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = (part.strip() for part in line.split("=", 1))
            value = value.strip('"').strip("'")
            if key == "NVIDIA_API_KEY" and value:
                os.environ[key] = value
            else:
                os.environ.setdefault(key, value)
        return


def main():
    load_env()
    parser = argparse.ArgumentParser(prog="python -m ghostprint")
    commands = parser.add_subparsers(dest="command", required=True)

    audit_command = commands.add_parser("audit", help="Audit local ZIPs, directories, or supported export files")
    audit_command.add_argument("archives", nargs="+")
    audit_command.add_argument("--platform", choices=sorted(KNOWN_PLATFORMS[:-1]),
                               help="Use this hint for every input in the command")
    audit_command.add_argument("--output", help="Write report JSON to this local file")
    audit_command.add_argument("--serve", action="store_true", help="Serve report on local loopback")
    audit_command.add_argument("--port", type=int, default=8765)

    demo_command = commands.add_parser("demo", help="Show a synthetic footprint in the local dashboard")
    demo_command.add_argument("--port", type=int, default=8765)
    demo_command.add_argument("--output", help="Write the demo report as JSON and exit")
    demo_command.add_argument("--model-server", help="Ask the second laptop to rank guides for a fixed demo question")

    live = commands.add_parser("live", help="Open a live website dashboard without importing an archive")
    live.add_argument("--port", type=int, default=8765)
    for command in (audit_command, demo_command, live):
        command.add_argument("--voice-model", default=os.getenv("GHOSTPRINT_VOICE_MODEL"),
                             help="Directory containing a downloaded multilingual faster-whisper model")

    lookup = commands.add_parser("retrieve", help="Search the public guide corpus locally")
    lookup.add_argument("query")

    score = commands.add_parser("evaluate", help="Compare retrieval, abstention, and archive integration")
    score.add_argument("--output", help="Write per-case metrics to a JSON file")
    score.add_argument("--model-server", help="Optional model bridge URL on the second laptop")

    model_command = commands.add_parser("bridge", help="Serve the synthetic-only model bridge")
    model_command.add_argument("--host", default="127.0.0.1")
    model_command.add_argument("--port", type=int, default=8766)
    model_command.add_argument("--base-url", default=NVIDIA_URL)
    model_command.add_argument("--model", default=MODEL)

    args = parser.parse_args()
    try:
        if args.command == "audit":
            report = audit([(path, args.platform) for path in args.archives])
            if args.output or not args.serve:
                write_json(report, args.output)
            if args.serve:
                dashboard(report, args.port, args.voice_model)
        elif args.command == "demo":
            with TemporaryDirectory() as directory:
                path = Path(directory) / "demo.zip"
                write_demo(path)
                report = audit([(path, None)])
            report["synthetic"] = True
            if args.model_server:
                try:
                    ids = bridge_rank(args.model_server, "g5")
                    report["model_demo"] = {"question": BY_CASE["g5"], "guides": [BY_ID[id_] for id_ in ids]}
                except (RuntimeError, ValueError) as error:
                    report["model_demo"] = {"question": BY_CASE["g5"], "error": str(error)}
            if args.output:
                write_json(report, args.output)
            else:
                dashboard(report, args.port, args.voice_model)
        elif args.command == "live":
            dashboard({"findings": [], "coverage": [], "activity_utc": {}, "interest_signals": [],
                       "live_only": True}, args.port, args.voice_model)
        elif args.command == "retrieve":
            write_json(retrieve(args.query))
        elif args.command == "evaluate":
            results = evaluate(args.model_server)
            if args.output:
                write_json(results, args.output)
            for mode, metrics in results["retrieval"].items():
                print(f"{mode:16} Top-1 {metrics['top_1']:6.1%}  Recall@5 {metrics['recall_at_5']:6.1%}"
                      f"  MRR@5 {metrics['mrr_at_5']:.3f}  Abstained {metrics['correct_abstentions']}/"
                      f"{metrics['negative_count']}  Median {metrics['median_ms']:.3f} ms"
                      f"  Errors {metrics['errors']}")
            checks = results["archive_smoke_test"]
            print(f"Archive smoke test: {sum(checks.values())}/{len(checks)} checks passed.")
            if not all(checks.values()) or any(row["errors"] for row in results["retrieval"].values()):
                return 1
        elif args.command == "bridge":
            token = os.getenv("GHOSTPRINT_BRIDGE_TOKEN")
            if args.host not in {"127.0.0.1", "localhost"} and not token:
                parser.error("Set GHOSTPRINT_BRIDGE_TOKEN before binding beyond loopback.")
            bridge(args.host, args.port, token, base=args.base_url, model=args.model)
    except (ValueError, OSError) as error:
        print(f"GhostPrint: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
