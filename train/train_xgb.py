"""Train the flow-severity model and export ONNX + feature importances.

    python train/train_xgb.py [--n 60000] [--out azkaban-agent/azkaban_agent/data]

Data: there is no public labelled corpus of "how bad is this flow", so we use weak
supervision — synthetic flows whose feature distributions mimic real captures,
labelled by an expert rubric (azkaban_agent.features.rubric) plus noise. The model
generalises the rubric smoothly and gives judges feature importances to inspect.
Tries device=cuda first, falls back to CPU.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "azkaban-agent"))
from azkaban_agent.features import FEATURES, SENSITIVITY, rubric, vector  # noqa: E402

PII = list(SENSITIVITY)


def synth(n: int, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    X, y = [], []
    for _ in range(n):
        dec = rng.random() > 0.25
        trk = rng.random() < 0.45
        k = rng.choice([0, 0, 0, 1, 1, 2, 3, 4]) if dec else 0
        types = set(rng.choice(PII, size=k, replace=False)) if k else set()
        f = vector(
            pii_types=types, is_tracker=trk, cross_border=rng.random() < 0.55,
            nbytes=int(rng.lognormal(7, 1.6)), consent=rng.random() < 0.3 and trk,
            mismatch=int(bool(types) and rng.random() < 0.3),
            adid_reuse=int(rng.integers(1, 6)) if "adid" in types else 0,
            decrypted=dec, hashed=int(rng.random() < 0.12 and dec),
            tsi=float(rng.exponential(60) if rng.random() < 0.7 else rng.uniform(120, 3600)),
        )
        X.append(f)
        y.append(np.clip(rubric(f) + rng.normal(0, 4), 0, 100))
    return np.asarray(X, dtype=np.float32), np.asarray(y, dtype=np.float32)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60000)
    ap.add_argument("--out", default=str(ROOT / "azkaban-agent" / "azkaban_agent" / "data"))
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    import xgboost as xgb

    X, y = synth(a.n)
    split = int(len(X) * 0.85)
    Xtr, ytr, Xte, yte = X[:split], y[:split], X[split:], y[split:]

    params = dict(n_estimators=300, max_depth=6, learning_rate=0.08, subsample=0.9,
                  colsample_bytree=0.9, tree_method="hist", objective="reg:squarederror")
    device = "cuda"
    t0 = time.time()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        model = xgb.XGBRegressor(device="cuda", **params)
        model.fit(Xtr, ytr)
        if any("GPU to CPU" in str(x.message) for x in w):
            device = "cpu (no CUDA device visible)"
    secs = time.time() - t0

    pred = model.predict(Xte)
    mae = float(np.mean(np.abs(pred - yte)))
    r2 = float(1 - np.sum((pred - yte) ** 2) / np.sum((yte - yte.mean()) ** 2))

    gain = model.get_booster().get_score(importance_type="gain")
    total = sum(gain.values()) or 1.0
    importances = sorted(
        ({"feature": FEATURES[int(k[1:])], "gain": round(v / total, 4)} for k, v in gain.items()),
        key=lambda d: -d["gain"])

    # ONNX export
    from onnxmltools import convert_xgboost
    from onnxmltools.convert.common.data_types import FloatTensorType
    model.get_booster().feature_names = None
    onx = convert_xgboost(model, initial_types=[("input", FloatTensorType([None, len(FEATURES)]))],
                          target_opset=15)
    (out / "severity.onnx").write_bytes(onx.SerializeToString())

    import onnxruntime as ort
    sess = ort.InferenceSession(str(out / "severity.onnx"), providers=["CPUExecutionProvider"])
    onnx_pred = sess.run(None, {"input": Xte[:256]})[0].ravel()
    parity = float(np.max(np.abs(onnx_pred - pred[:256])))

    meta = {
        "features": FEATURES, "importances": importances, "mae": round(mae, 3), "r2": round(r2, 4),
        "n_train": split, "n_test": len(X) - split, "device": device, "train_seconds": round(secs, 2),
        "onnx_parity_max_abs_err": round(parity, 5), "labels": "weak supervision: expert rubric + N(0,4) noise",
    }
    (out / "severity_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
