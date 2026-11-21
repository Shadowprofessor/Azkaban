"""Agent runtime: wires capture/replay -> pipeline -> outputs on one asyncio loop."""
from __future__ import annotations

import asyncio
import sys
from collections import OrderedDict

from . import __version__
from .config import Config
from .pipeline import Pipeline
from .blocklist import Blocklist, host_blocked
from .config import REPO_ROOT
from .evidence import EvidenceChain
from .extbridge import ExtensionBridge
from .idle import IdleDetector
from .insights import InsightEngine
from . import remediate
from .legal import LegalEngine, build_facts, facts_key
from .mlextra import BeaconAnomaly
from .tracker_clf import TrackerClassifier, insight as tracker_insight
from .netwatch import NetWatch
from .score import ExposureScore
from .session import Recorder, read_header, replay
from .wsserver import Hub, start_ws


def log(msg: str) -> None:
    print(f"[azkaban] {msg}", file=sys.stderr, flush=True)


class Agent:
    def __init__(self, cfg: Config, mode: str = "live", record: str | None = None, consent: bool = False):
        self.cfg = cfg
        self.mode = mode
        self.loop: asyncio.AbstractEventLoop | None = None
        self.ext = ExtensionBridge(self.status, self.on_browser_detection, self.on_site_score)
        self.hub = Hub(self.status, self.on_command, extension=self.ext)
        self.site_scores: dict[str, dict] = {}        # site -> latest extension score
        self.pipeline = Pipeline(cfg)
        self.exposure = ExposureScore()
        self.insights = InsightEngine()
        self.idle = IdleDetector() if mode == "live" else None
        self.netwatch = NetWatch(cfg.proxy_port) if mode == "live" else None
        self.recorder = Recorder(record) if record else None
        self.addon = None
        if mode == "live":
            from .capture import CaptureAddon
            self.addon = CaptureAddon(self._on_raw_threadsafe)
        self.flow_count = 0
        self.capturing = True
        self.legal = LegalEngine(cfg)
        self.llm_ok = False
        self.recent: OrderedDict[str, object] = OrderedDict()   # flowId -> Enriched (memory only)
        self.verdict_q: asyncio.Queue | None = None
        self.pending_keys: set[str] = set()
        self.auto_verdict_min = 60
        self.blocklist = Blocklist()
        self.evidence_dir = REPO_ROOT / "evidence"
        self.beacons = BeaconAnomaly()
        self.tracker_clf = TrackerClassifier()
        self.evidence = EvidenceChain(mode, consent)
        self._blocklist_dirty = False
        self._replay_args: tuple | None = None
        self._replay_task: asyncio.Task | None = None
        if self.addon:
            self.addon.on_blocked = self.on_blocked

    # ------------------------------------------------------------------ insights
    def publish_insight(self, msg: dict) -> None:
        """Single path for every insight, so remediation is attached exactly once."""
        self.hub.publish(remediate.enrich(msg))

    # ------------------------------------------------------------------ extension bridge
    async def on_browser_detection(self, d: dict) -> None:
        """A finding from the browser, already validated by extbridge.

        Deliberately NOT added to the exposure score. When the proxy is also capturing, the
        extension and mitmproxy both see the same browser requests, and counting them twice
        would silently inflate the number the whole UI is built around. These are published
        as their own finding type so the dashboard can show them beside network flows and
        label where they came from.
        """
        self.evidence.add_event("browser_detection", d)
        self.publish_insight({
            "type": "insight",
            "key": f"browser:{d['kind']}:{d['domain']}",
            "kind": d["kind"] if d["kind"] in ("unknown_tracker", "hashed_pii") else "unknown_tracker",
            "level": "critical" if d["kind"] in ("harvest", "hashed_pii") else "warn",
            "title": self._browser_title(d),
            "detail": f"Seen in the browser by the Azkaban extension on {d['site'] or 'a page'}"
                      + (f", category {d['category']}" if d["category"] != "unknown" else "")
                      + (f", confidence {d['confidence']:.2f}" if d["confidence"] else "")
                      + ". The proxy cannot see this: it happens before TLS or inside the page.",
            "data": {**d, "company": d["company"] or d["domain"], "host": d["host"]},
        })

    @staticmethod
    def _browser_title(d: dict) -> str:
        kind, dom = d["kind"], d["domain"]
        if kind == "fingerprinting":
            return f"Fingerprinting in the browser: {dom}"
        if kind == "harvest":
            return f"Form data sent before submit: {dom}"
        if kind == "hashed_pii":
            return f"Hashed identifier sent from the browser to {dom}"
        if kind == "third_party_volume":
            return f"Heavy third-party activity on {d['site'] or dom}"
        return f"Likely tracker not on any list: {dom} (browser)"

    async def on_site_score(self, s: dict) -> None:
        """Latest A-F safety score for a site, from the extension popup."""
        self.site_scores[s["site"]] = s
        self.hub.publish({"type": "insight", "key": f"site_score:{s['site']}",
                          "kind": "unknown_tracker", "level": "info",
                          "title": f"Site safety {s['grade']} ({s['score']}/100): {s['site']}",
                          "detail": f"Scored in the browser from {s['breakdown']['trackerCount']} trackers, "
                                    f"{s['breakdown']['unknownTrackerCount']} on no list, "
                                    f"{s['breakdown']['thirdPartyCount']} third parties and "
                                    f"{s['breakdown']['cookieCount']} cookies"
                                    + (", with fingerprinting" if s["breakdown"]["fingerprintingDetected"] else "")
                                    + ".",
                          "data": s})

    # ------------------------------------------------------------------ status
    def status(self) -> dict:
        return {
            "type": "status",
            "capturing": self.capturing,
            "mode": self.mode if self.capturing else "idle",
            "proxy": f"127.0.0.1:{self.cfg.proxy_port}" if self.mode == "live" else "",
            "flows": self.flow_count,
            "engines": {"llm": self.llm_ok, "rag": self.legal.rag_source == "rag",
                        "model": self.pipeline.severity.available, "geo": self.pipeline.geo.available,
                        "nim": self.legal.nim.configured,
                        "remediation": remediate.available()},
            # Additive (v1): extension bridge state, for the popup's connected indicator.
            "extension": {"connected": self.ext.clients > 0, "version": self.ext.version,
                          "detections": self.ext.detections, "scores": self.ext.scores},
            # Additive (v1): which reasoning engine answered last, for the UI badge.
            "llmEngine": self.legal.engine,
            "llmModel": self.legal.nim.model if self.legal.nim.configured else self.cfg.ollama_model,
            "version": __version__,
        }

    # ------------------------------------------------------------------ ingest
    def _on_raw_threadsafe(self, raw: dict) -> None:
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.on_raw, raw)
        else:
            self.on_raw(raw)

    def on_raw(self, raw: dict) -> None:
        if not self.capturing:
            return
        if self.idle is not None and "tsi" not in raw:
            raw["tsi"] = round(self.idle.seconds() or 0.0, 1)
        if self.blocklist.blocked and host_blocked(raw.get("host", ""), self.blocklist.blocked):
            # Replay: emulate the proxy refusing a blocked destination.
            self.on_blocked(raw.get("host", ""))
            return
        if self.recorder:
            self.recorder.write(raw)
        try:
            enriched = self.pipeline.process(raw)
        except Exception as e:  # never crash capture on one bad flow
            self.hub.error("pipeline", f"{type(e).__name__}: {e}")
            return
        self.flow_count += 1
        self.exposure.add(self.pipeline.fact(enriched))
        self.blocklist.observe(enriched.flow)
        if self.blocklist.applied:
            self._blocklist_dirty = True
        flow_dict = enriched.flow.to_dict()
        self.hub.publish({"type": "flow", "flow": flow_dict})
        self.evidence.add_flow(flow_dict)
        f = enriched.flow
        self.tracker_clf.observe(raw, listed=f.tracker is not None)
        self.beacons.observe(f.app, f.host, f.ts, f.bytes, enriched.tsi, {h.type for h in f.pii},
                             enriched.hashed_hits, listed=f.tracker is not None)
        for hit in enriched.honey:
            self._honeytoken_alert(enriched, hit)
        self.recent[enriched.flow.id] = enriched
        if len(self.recent) > 2000:
            self.recent.popitem(last=False)
        if enriched.flow.severity >= self.auto_verdict_min and enriched.flow.pii:
            self._enqueue_verdict(enriched)
        if self.netwatch:
            f = enriched.flow
            self.netwatch.learn(f.ip, f.host, f.app)
        for msg in self.insights.on_flow(enriched):
            self.publish_insight(msg)

    # ------------------------------------------------------------------ verdicts
    def _enqueue_verdict(self, e, force: bool = False) -> bool:
        if self.verdict_q is None:
            return False
        facts = build_facts(e, self.cfg.home_country)
        key = facts_key(facts)
        if key in self.legal.cache:
            self.hub.publish({"type": "verdict", "verdict": self.legal.verdict(e.flow.id, facts).to_dict()})
            return True
        if key in self.pending_keys and not force:
            return True
        self.pending_keys.add(key)
        self.verdict_q.put_nowait((e.flow.id, facts, key))
        return True

    async def _verdict_worker(self) -> None:
        warned = False
        while True:
            flow_id, facts, key = await self.verdict_q.get()
            try:
                v = await asyncio.to_thread(self.legal.verdict, flow_id, facts)
            except Exception as ex:
                v = None
                self.hub.error("legal", f"{type(ex).__name__}: {ex}")
            finally:
                self.pending_keys.discard(key)
            if v is None:
                if not warned:
                    self.hub.error("llm_unavailable", "Legal engine offline (Ollama not reachable). "
                                   "Flows and severity continue; verdicts paused.")
                    warned = True
                continue
            warned = False
            self.hub.publish({"type": "verdict", "verdict": v.to_dict()})
            self.evidence.add_verdict(v.to_dict())

    async def _health_loop(self) -> None:
        while True:
            ok = await asyncio.to_thread(self.legal.llm_available)
            if ok != self.llm_ok:
                self.llm_ok = ok
                self.hub.broadcast_status()
            await asyncio.sleep(15)

    # ------------------------------------------------------------------ honeytoken / evidence
    def _honeytoken_alert(self, e, hit: dict) -> None:
        f = e.flow
        self.evidence.add_event("honeytoken", {"flowId": f.id, "app": f.app, "host": f.host,
                                               "company": f.company, **hit})
        log(f"!!! HONEYTOKEN '{hit['label']}' leaked by {f.app} to {f.host} ({hit['field']}, {hit['via']})")
        self.publish_insight({"type": "insight", "key": f"honeytoken:{hit['label']}:{f.app}:{f.host}",
                          "kind": "honeytoken", "level": "critical",
                          "title": f"CANARY TRIPPED: {f.app} sent your planted '{hit['label']}' to {f.host}",
                          "detail": "This exact value exists only where you planted it. Its appearance in outbound "
                                    f"traffic proves {f.app} read and transmitted it (field '{hit['field']}', "
                                    f"encoding {hit['via']}).",
                          "data": {"flowId": f.id, "app": f.app, "host": f.host, "company": f.company, **hit}})

    async def _export_evidence(self) -> None:
        res = await asyncio.to_thread(self.evidence.export, self.evidence_dir)
        log(f"evidence pack: {res['path']} (head {res['rootHash'][:16]}…, {res['entries']} entries)")
        self.hub.publish({"type": "evidence", "path": res["path"], "rootHash": res["rootHash"],
                          "entries": res["entries"]}, keep=False)

    # ------------------------------------------------------------------ blocklist
    def on_blocked(self, host: str) -> None:
        self.blocklist.prevented += 1
        self._blocklist_dirty = True

    def _blocklist_command(self, action: str) -> None:
        bl = self.blocklist
        if action == "generate":
            bl.generate()
        elif action == "apply":
            before = self.exposure.score().total
            blocked = bl.apply(before)
            if self.addon:
                self.addon.blocked = blocked
            self.exposure.reset()                         # recheck window starts clean
            self.evidence.add_event("blocklist_applied", {"hosts": sorted(blocked), "baselineLeaks": bl.baseline,
                                                           "baselineScore": before})
            log(f"Patronus applied: {len(blocked)} hosts blocked; baseline {bl.baseline} leaks, score {before}")
            if self.mode == "replay" and self._replay_args:
                self._restart_replay()                    # same session again = apples-to-apples
        elif action == "clear":
            bl.clear()
            if self.addon:
                self.addon.blocked = set()
        else:
            self.hub.error("bad_request", f"blocklist action must be generate|apply|clear, got {action!r}")
            return
        self.hub.publish(bl.message(), keep=False)

    def _recheck_insight(self) -> dict | None:
        bl = self.blocklist
        r = bl.recheck()
        if r is None:
            return None
        after = self.exposure.score().total
        return {"type": "insight", "key": "recheck", "kind": "recheck",
                "level": "info" if r["delta"] <= 0 else "warn",
                "title": f"Patronus: leaks {r['baseline']} → {r['current']}, exposure {bl.baseline_score:.0f} → {after:.0f}",
                "detail": f"{bl.prevented} requests to {len(bl.blocked)} blocked hosts were refused since the "
                          "blocklist was applied.",
                "data": {**r, "scoreBefore": bl.baseline_score, "scoreAfter": after, "prevented": bl.prevented,
                         "blockedHosts": len(bl.blocked)}}

    # ------------------------------------------------------------------ commands
    async def on_command(self, cmd: dict) -> None:
        t = cmd["type"]
        if t == "export_evidence":
            await self._export_evidence()
            return
        if t == "blocklist":
            self._blocklist_command(str(cmd.get("action", "generate")))
            return
        if t == "analyze":
            e = self.recent.get(str(cmd.get("flowId", "")))
            if e is None:
                self.hub.error("not_found", f"flow {cmd.get('flowId')!r} is not in memory")
            elif not self.llm_ok:
                self.hub.error("llm_unavailable", "Legal engine offline (start Ollama with qwen2.5:7b).")
            else:
                self._enqueue_verdict(e, force=True)
            return
        if t == "start":
            self.capturing = True
            if self.addon:
                self.addon.paused = False
        elif t == "stop":
            self.capturing = False
            if self.addon:
                self.addon.paused = True
        else:
            self.hub.error("unsupported", f"command '{t}' is not available yet")
            return
        self.hub.broadcast_status()

    # ------------------------------------------------------------------ run
    async def _score_loop(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            if self.exposure.dirty:
                try:
                    self.hub.publish(self.exposure.message(), keep=False)
                except Exception as e:
                    self.hub.error("score", str(e))
            if self._blocklist_dirty:
                self._blocklist_dirty = False
                self.hub.publish(self.blocklist.message(), keep=False)
                ins = self._recheck_insight()
                if ins:
                    self.publish_insight(ins)

    async def _insight_loop(self) -> None:
        tick = 0
        while True:
            await asyncio.sleep(2.0)
            tick += 1
            bypass = None
            if self.netwatch and tick % 5 == 0:   # every ~10s, off the event loop
                try:
                    bypass = await asyncio.to_thread(self.netwatch.scan)
                except Exception:
                    bypass = None
            for msg in self.insights.periodic(bypass):
                self.publish_insight(msg)
            if tick % 5 == 0:
                for msg in await asyncio.to_thread(self._ml_insights):
                    self.publish_insight(msg)

    def _ml_insights(self) -> list[dict]:
        out = []
        try:
            for a in self.beacons.detect():
                out.append({"type": "insight", "key": f"anomaly:{a['app']}:{a['host']}", "kind": "beacon_anomaly",
                            "level": "info", "title": f"Unusual beacon pattern: {a['app']} -> {a['host']}",
                            "detail": f"{a['requests']} requests, every ~{a['meanGapS']}s (regularity CV "
                                      f"{a['regularityCV']}, {int(a['idleFraction'] * 100)}% while idle). "
                                      "Flagged by an IsolationForest over all observed app/host pairs.",
                            "data": a})
            # Unknown trackers: the ONNX classifier (behaviour + structure + lexical), unlisted domains only.
            for c in self.tracker_clf.candidates():
                out.append(tracker_insight(c))
        except Exception as ex:   # ML is optional; never break the agent
            out.append({"type": "error", "code": "ml", "message": f"{type(ex).__name__}: {ex}"})
        return out

    async def _serve_ws(self):
        self.verdict_q = asyncio.Queue()
        self._bg = [asyncio.create_task(self._score_loop()), asyncio.create_task(self._insight_loop()),
                    asyncio.create_task(self._verdict_worker()), asyncio.create_task(self._health_loop())]
        ws = await start_ws(self.hub, self.cfg.ws_port)
        log(f"dashboard socket ws://127.0.0.1:{self.cfg.ws_port}")
        return ws

    async def run(self) -> None:
        from .capture import run_proxy
        self.loop = asyncio.get_running_loop()
        ws = await self._serve_ws()
        try:
            master = await run_proxy(self.addon, self.cfg.proxy_port)
            log(f"The Trace is listening on 127.0.0.1:{self.cfg.proxy_port} (CA in ~/.mitmproxy)")
            await master.run()
        finally:
            ws.close()
            if self.recorder:
                self.recorder.close()

    async def run_replay(self, path: str, speed: float, loop_forever: bool, wait_client: float) -> None:
        self.loop = asyncio.get_running_loop()
        self.session_header = read_header(path)
        ident = self.session_header.get("identity") or {}
        self.pipeline.identity.add_many(ident.get("emails", []), ident.get("phones", []), ident.get("adids", []))
        for t in self.session_header.get("honeytokens", []):
            self.pipeline.canary.register(t)
        ws = await self._serve_ws()
        try:
            # Give the dashboard a moment to connect so it sees the whole story.
            waited = 0.0
            while not self.hub.clients and waited < wait_client:
                await asyncio.sleep(0.25)
                waited += 0.25
            self._replay_args = (path, speed, loop_forever)
            self._restart_replay()
            await asyncio.Event().wait()
        finally:
            ws.close()

    def _restart_replay(self) -> None:
        if self._replay_task and not self._replay_task.done():
            self._replay_task.cancel()
        self.capturing = True
        self._replay_task = asyncio.create_task(self._replay_once(*self._replay_args))
        self.hub.broadcast_status()

    async def _replay_once(self, path: str, speed: float, loop_forever: bool) -> None:
        log(f"replaying {path} at {speed}x")
        n = await replay(path, self.on_raw, speed=speed, loop_forever=loop_forever,
                         should_run=lambda: self.capturing)
        log(f"replay finished: {n} flows. Socket stays up; Ctrl+C to exit.")
        self.capturing = False
        self.hub.broadcast_status()
