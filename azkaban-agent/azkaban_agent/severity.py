"""In-agent severity inference (ONNX Runtime), with the rubric as a fallback."""
from __future__ import annotations

import json

import numpy as np

from .config import DATA_DIR
from .features import FEATURES, category_mismatch, rubric, vector


class SeverityModel:
    def __init__(self, path=DATA_DIR / "severity.onnx"):
        self.sess = None
        self.meta = {}
        try:
            import onnxruntime as ort
            if path.is_file():
                self.sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
                self.input = self.sess.get_inputs()[0].name
                meta_p = path.with_name("severity_meta.json")
                if meta_p.is_file():
                    self.meta = json.loads(meta_p.read_text())
        except Exception:
            self.sess = None

    @property
    def available(self) -> bool:
        return self.sess is not None

    def features(self, e, home_country: str) -> list[float]:
        f = e.flow
        types = {h.type for h in f.pii}
        cross = f.country not in ("ZZ", "", home_country)
        return vector(
            pii_types=types, is_tracker=f.tracker is not None, cross_border=cross, nbytes=f.bytes,
            consent=bool(f.tcf and f.tcf.purposes), mismatch=category_mismatch(f.app, types),
            adid_reuse=e.adid_reuse, decrypted=f.decrypted, hashed=e.hashed_hits, tsi=e.tsi,
        )

    def score(self, feats: list[float]) -> int:
        if self.sess is not None:
            try:
                out = self.sess.run(None, {self.input: np.asarray([feats], dtype=np.float32)})[0]
                return int(round(float(np.clip(np.ravel(out)[0], 0, 100))))
            except Exception:
                pass
        return int(round(rubric(feats)))

    def explain(self, feats: list[float]) -> dict:
        return dict(zip(FEATURES, feats))
