"""Train the unknown-tracker classifier with an honest, leakage-free evaluation.

    python train/train_tracker.py --gpu --model xgboost|lightgbm|ensemble --n-synth 20000

Evaluation protocol (see MODELS.md):
  * TEST rows are only REAL domains with REAL behaviour (WhoTracks.me per-domain aggregates),
    labelled by public blocklists. 5-fold GroupKFold, group = domain name without TLD, so
    doubleclick.net / doubleclick.com never straddle train and test.
  * TRAIN per fold = real rows of the other folds + list-only rows (no behaviour) whose group
    is not in the test fold + optional synthetic behaviour bootstrapped ONLY from that fold's
    real training rows, conditioned on label+category. Synthetic rows never reach a test set.
  * Missing behaviour -> train-set medians + has_behavior flag (same stats ship to runtime).
  * Thresholds are tuned on a validation split carved from the training fold, never on test.
Outputs: azkaban-agent/azkaban_agent/data/tracker_clf.onnx (+ tracker_clf_cat.onnx, meta json)
         reports/ (metrics.json, ablation.md, confusion_matrix.png, feature_importance.png)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, balanced_accuracy_score, confusion_matrix, f1_score,
                             precision_score, recall_score, roc_auc_score)
from sklearn.model_selection import GroupKFold, GroupShuffleSplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "train"))
from features import (AVAILABILITY, BEHAVIOURAL, DEPLOYED, GLOBAL_ONLY, LEXICAL, STRUCTURAL,  # noqa: E402
                      behaviour_from_wtm, group_key, lexical)

DATA = ROOT / "train" / "data" / "tracker_dataset.parquet"
OUT = ROOT / "azkaban-agent" / "azkaban_agent" / "data"
REPORTS = ROOT / "reports"
CLASSES = ["advertising", "analytics", "social", "fingerprinting"]
SEED = 7
REAL_WEIGHT = 4.0
BEH_FEATS = [f for f in STRUCTURAL + BEHAVIOURAL if f != "has_behavior"]
MONTHLY: pd.DataFrame | None = None  # set in main()


# ---------------------------------------------------------------- data
def load(n_max_lex: int | None) -> pd.DataFrame:
    df = pd.read_parquet(DATA)
    real = df[df.is_real_behavior]
    lex = df[~df.is_real_behavior]
    if n_max_lex and len(lex) > n_max_lex:  # keep class balance roughly as in the lists
        lex = lex.sample(n_max_lex, random_state=SEED)
    df = pd.concat([real, lex], ignore_index=True)
    lex_rows = [lexical(d) for d in df.domain]
    beh_rows = [behaviour_from_wtm(r) if r["is_real_behavior"] else {"has_behavior": 0.0}
                for r in df.to_dict("records")]
    feats = pd.DataFrame(lex_rows).join(pd.DataFrame(beh_rows))
    for c in DEPLOYED + GLOBAL_ONLY:
        if c not in feats:
            feats[c] = np.nan
    out = pd.concat([df[["domain", "label", "category", "is_real_behavior", "source", "n_positive_sources"]], feats], axis=1)
    out["group"] = out.domain.map(group_key)
    out["synthetic"] = False
    out["month"] = df.get("wtm_month")
    return out


def load_monthly(main: pd.DataFrame) -> pd.DataFrame:
    """Every (domain, month) REAL observation of real-behaviour domains, minus the month already
    in the main table. Used only to enlarge the TRAINING side (grouped by domain, so a test
    domain's other months can never be in training)."""
    path = DATA.with_name("wtm_monthly.parquet")
    if not path.exists():
        return main.iloc[0:0]
    m = pd.read_parquet(path)
    real = main[main.is_real_behavior].set_index("domain")
    m = m[m.domain.isin(real.index)]
    m = m[m.wtm_month.values != real.loc[m.domain, "month"].values]
    beh = pd.DataFrame([behaviour_from_wtm(r) for r in m.to_dict("records")])
    lex = pd.DataFrame([lexical(d) for d in m.domain])
    out = pd.concat([m[["domain"]].reset_index(drop=True), lex, beh], axis=1)
    for c in DEPLOYED + GLOBAL_ONLY:
        if c not in out:
            out[c] = np.nan
    out["label"] = real.loc[out.domain, "label"].values
    out["category"] = real.loc[out.domain, "category"].values
    out["is_real_behavior"] = True
    out["source"] = "whotracks-monthly"
    out["n_positive_sources"] = real.loc[out.domain, "n_positive_sources"].values
    out["group"] = out.domain.map(group_key)
    out["synthetic"] = False
    out["month"] = m.wtm_month.values
    return out


def synthesize(train_real: pd.DataFrame, lex: pd.DataFrame, n: int, rng: np.random.Generator) -> pd.DataFrame:
    """Give n list-only rows a behaviour vector bootstrapped from REAL training rows of the same
    label (and category for positives), plus small noise. Train-only by construction."""
    if n <= 0 or lex.empty:
        return lex.iloc[0:0]
    picks = lex.sample(min(n, len(lex)), random_state=int(rng.integers(1 << 31))).copy()
    cols = BEH_FEATS + GLOBAL_ONLY
    for key, grp in picks.groupby(["label", "category"]):
        pool = train_real[(train_real.label == key[0]) & (train_real.category == key[1])]
        if len(pool) < 5:
            pool = train_real[train_real.label == key[0]]
        donors = pool[cols].to_numpy()[rng.integers(0, len(pool), size=len(grp))]
        noise = rng.normal(0, 0.03, size=donors.shape)
        picks.loc[grp.index, cols] = np.where(np.isnan(donors), np.nan, donors + noise)
    for c in BEH_FEATS:
        if not c.startswith("beh_log"):
            picks[c] = picks[c].clip(0, 1)
    picks["has_behavior"] = 1.0
    picks["synthetic"] = True
    return picks


def impute(train: pd.DataFrame, cols: list[str]) -> dict[str, float]:
    med = train[train.has_behavior == 1][cols].median(numeric_only=True)
    return {c: (float(med[c]) if c in med and pd.notna(med[c]) else 0.0) for c in cols}


def matrix(df: pd.DataFrame, cols: list[str], med: dict[str, float]) -> np.ndarray:
    X = df[cols].astype(float).copy()
    for c in cols:
        if c in med:
            X[c] = X[c].fillna(med[c])
    return X.to_numpy(dtype=np.float32)


# ---------------------------------------------------------------- models
def device_for(gpu: bool) -> str:
    return "cuda" if gpu else "cpu"


def fit_xgb(X, y, w, gpu: bool, multi: int = 0):
    import xgboost as xgb
    params = dict(n_estimators=600, max_depth=7, learning_rate=0.05, subsample=0.9, colsample_bytree=0.8,
                  min_child_weight=2, tree_method="hist", device=device_for(gpu), random_state=SEED)
    if multi:
        m = xgb.XGBClassifier(objective="multi:softprob", num_class=multi, **params)
    else:
        pos = max(1.0, float((y == 1).sum()))
        m = xgb.XGBClassifier(objective="binary:logistic", scale_pos_weight=float((y == 0).sum()) / pos, **params)
    with warnings.catch_warnings(record=True) as w_:
        warnings.simplefilter("always")
        m.fit(X, y, sample_weight=w)
    ran = "cpu (CUDA requested but unavailable)" if gpu and any("GPU to CPU" in str(x.message) for x in w_) else device_for(gpu)
    return m, ran


def fit_lgbm(X, y, w, gpu: bool):
    import lightgbm as lgb
    kw = dict(n_estimators=600, learning_rate=0.05, num_leaves=63, subsample=0.9, subsample_freq=1,
              colsample_bytree=0.8, is_unbalance=True, random_state=SEED, verbose=-1)
    if gpu:
        try:
            m = lgb.LGBMClassifier(device_type="gpu", **kw)
            m.fit(X, y, sample_weight=w)
            return m, "gpu (OpenCL)"
        except Exception as e:  # pip wheels may lack GPU support
            print(f"  lightgbm gpu unavailable ({type(e).__name__}); using cpu")
    m = lgb.LGBMClassifier(**kw)
    m.fit(X, y, sample_weight=w)
    return m, "cpu"


# Character CNN over the registrable domain name (optional ensemble member).
def fit_cnn(domains: list[str], y: np.ndarray, gpu: bool, epochs: int = 6):
    import torch
    from torch import nn
    dev = "cuda" if gpu and torch.cuda.is_available() else "cpu"
    vocab = {c: i + 1 for i, c in enumerate("abcdefghijklmnopqrstuvwxyz0123456789-.")}
    L = 40

    def enc(ds):
        arr = np.zeros((len(ds), L), dtype=np.int64)
        for i, d in enumerate(ds):
            for j, ch in enumerate(d[:L]):
                arr[i, j] = vocab.get(ch, 0)
        return torch.from_numpy(arr)

    class Net(nn.Module):
        def __init__(self):
            super().__init__()
            self.emb = nn.Embedding(len(vocab) + 1, 32, padding_idx=0)
            self.convs = nn.ModuleList([nn.Conv1d(32, 64, k, padding=k // 2) for k in (3, 4, 5)])
            self.head = nn.Sequential(nn.Dropout(0.2), nn.Linear(192, 64), nn.ReLU(), nn.Linear(64, 1))

        def forward(self, x):
            e = self.emb(x).transpose(1, 2)
            h = torch.cat([torch.relu(c(e)).amax(dim=2) for c in self.convs], dim=1)
            return self.head(h).squeeze(1)

    torch.manual_seed(SEED)
    net = Net().to(dev)
    X = enc(domains)
    Y = torch.from_numpy(y.astype(np.float32))
    pos = float(Y.sum())
    loss_fn = nn.BCEWithLogitsLoss(pos_weight=torch.tensor((len(Y) - pos) / max(pos, 1.0), device=dev))
    opt = torch.optim.AdamW(net.parameters(), lr=2e-3, weight_decay=1e-4)
    for _ in range(epochs):
        perm = torch.randperm(len(X))
        net.train()
        for i in range(0, len(X), 512):
            idx = perm[i:i + 512]
            opt.zero_grad()
            loss_fn(net(X[idx].to(dev)), Y[idx].to(dev)).backward()
            opt.step()
    net.eval()

    def predict(ds):
        with torch.no_grad():
            out = []
            for i in range(0, len(ds), 4096):
                out.append(torch.sigmoid(net(enc(ds[i:i + 4096]).to(dev))).cpu().numpy())
            return np.concatenate(out) if out else np.zeros(0)
    return predict, dev


# ---------------------------------------------------------------- metrics
def binary_metrics(y, p, thr) -> dict:
    yhat = (p >= thr).astype(int)
    return {
        "threshold": round(float(thr), 3),
        "f1": round(f1_score(y, yhat), 4),
        "precision": round(precision_score(y, yhat, zero_division=0), 4),
        "recall": round(recall_score(y, yhat), 4),
        "balanced_accuracy": round(balanced_accuracy_score(y, yhat), 4),
        "pr_auc": round(average_precision_score(y, p), 4),
        "roc_auc": round(roc_auc_score(y, p), 4),
        "confusion_matrix": confusion_matrix(y, yhat).tolist(),  # [[TN, FP], [FN, TP]]
        "n": int(len(y)), "positives": int(y.sum()),
    }


def best_threshold(y, p) -> float:
    grid = np.linspace(0.05, 0.95, 91)
    return float(grid[int(np.argmax([f1_score(y, (p >= t).astype(int)) for t in grid]))])


# ---------------------------------------------------------------- CV
def run_cv(df: pd.DataFrame, cols: list[str], args, label: str, browser_eval: bool = False, use_cnn: bool = False):
    """Returns OOF predictions on REAL rows for one feature set."""
    rng = np.random.default_rng(SEED)
    real = df[df.is_real_behavior].reset_index(drop=True)
    lex = df[~df.is_real_behavior]
    max_lex = getattr(args, "lex_rows", None)
    if max_lex is not None and len(lex) > max_lex:
        lex = lex.sample(max_lex, random_state=SEED) if max_lex > 0 else lex.iloc[0:0]
    oof = np.zeros(len(real))
    oof_thr = np.zeros(len(real))
    folds, devices = [], set()
    for k, (tr, te) in enumerate(GroupKFold(n_splits=5).split(real, real.label, real.group)):
        test = real.iloc[te]
        train_real = real.iloc[tr]
        tgroups = set(test.group)
        lex_k = lex[~lex.group.isin(tgroups)]
        # Validation split (from the training fold) for threshold tuning.
        vs = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=SEED).split(train_real, train_real.label, train_real.group)
        fit_idx, val_idx = next(vs)
        fit_real, val_real = train_real.iloc[fit_idx], train_real.iloc[val_idx]

        def make_train(base_real):
            if getattr(args, "monthly", False) and MONTHLY is not None and len(MONTHLY):
                base_real = pd.concat([base_real, MONTHLY[MONTHLY.domain.isin(set(base_real.domain))]], ignore_index=True)
            # Synthetic behaviour is bootstrapped ONLY from the real rows being fit, so neither the
            # validation split nor the test fold can leak into training through synthesis.
            synth = synthesize(base_real, lex_k, args.n_synth, rng)
            t = pd.concat([base_real, lex_k.drop(index=synth.index), synth], ignore_index=True)
            w = np.where(t.is_real_behavior, getattr(args, "real_weight", REAL_WEIGHT), 1.0)
            return t, w

        t_fit, w_fit = make_train(fit_real)
        med = impute(t_fit, cols)
        model, dev = fit(args.model_kind, matrix(t_fit, cols, med), t_fit.label.to_numpy(), w_fit, args.gpu)
        val_p = model.predict_proba(matrix(val_real, cols, med))[:, 1]
        thr = best_threshold(val_real.label.to_numpy(), val_p)
        val_f1 = f1_score(val_real.label.to_numpy(), (val_p >= thr).astype(int))
        # Refit on the whole training fold, predict the held-out REAL fold.
        t_all, w_all = make_train(train_real)
        med = impute(t_all, cols)
        model, dev = fit(args.model_kind, matrix(t_all, cols, med), t_all.label.to_numpy(), w_all, args.gpu)
        devices.add(dev)
        Xte = test.copy()
        if browser_eval:  # extension parity: agent-only features are unobservable in the browser
            for c in cols:
                if AVAILABILITY.get(c) == "agent":
                    Xte[c] = np.nan
        p = model.predict_proba(matrix(Xte, cols, med))[:, 1]
        if use_cnn:
            cnn, cdev = fit_cnn(list(t_all.domain), t_all.label.to_numpy(), args.gpu)
            devices.add(f"cnn:{cdev}")
            p = (p + cnn(list(test.domain))) / 2
        oof[te] = p
        oof_thr[te] = thr
        y = test.label.to_numpy()
        folds.append({"fold": k, "n_test": int(len(te)), "threshold": round(thr, 3), "val_f1": round(val_f1, 4),
                      "f1@0.5": round(f1_score(y, (p >= 0.5).astype(int)), 4),
                      "f1@tuned": round(f1_score(y, (p >= thr).astype(int)), 4)})
        print(f"  [{label}] fold {k}: n={len(te)} f1@0.5={folds[-1]['f1@0.5']} f1@tuned={folds[-1]['f1@tuned']} ({dev})", flush=True)
    y = real.label.to_numpy()
    tuned = (oof >= oof_thr).astype(int)
    res = {
        "features": len(cols),
        "at_0.5": binary_metrics(y, oof, 0.5),
        "at_tuned_threshold": {**binary_metrics(y, oof, 0.5), "f1": round(f1_score(y, tuned), 4),
                               "precision": round(precision_score(y, tuned), 4), "recall": round(recall_score(y, tuned), 4),
                               "balanced_accuracy": round(balanced_accuracy_score(y, tuned), 4),
                               "confusion_matrix": confusion_matrix(y, tuned).tolist(),
                               "threshold": "per-fold, tuned on a validation split of the training fold"},
        "folds": folds, "devices": sorted(devices),
    }
    return res, oof, real


def fit(kind: str, X, y, w, gpu):
    if kind == "lightgbm":
        return fit_lgbm(X, y, w, gpu)
    return fit_xgb(X, y, w, gpu)


def category_cv(df: pd.DataFrame, cols: list[str], args) -> dict:
    """Multi-class head (category among positives) on REAL positive rows, GroupKFold."""
    real = df[df.is_real_behavior & (df.label == 1)].reset_index(drop=True)
    lexp = df[~df.is_real_behavior & (df.label == 1)]
    y_all = real.category.map(CLASSES.index).to_numpy()
    pred = np.zeros(len(real), dtype=int)
    for tr, te in GroupKFold(n_splits=5).split(real, y_all, real.group):
        tgroups = set(real.iloc[te].group)
        t = pd.concat([real.iloc[tr], lexp[~lexp.group.isin(tgroups)]], ignore_index=True)
        med = impute(t, cols)
        w = np.where(t.is_real_behavior, REAL_WEIGHT, 1.0)
        m, _ = fit_xgb(matrix(t, cols, med), t.category.map(CLASSES.index).to_numpy(), w, args.gpu, multi=len(CLASSES))
        pred[te] = m.predict_proba(matrix(real.iloc[te], cols, med)).argmax(1)
    return {"macro_f1": round(f1_score(y_all, pred, average="macro"), 4),
            "per_class_f1": dict(zip(CLASSES, np.round(f1_score(y_all, pred, average=None, labels=range(4)), 4).tolist())),
            "confusion_matrix": confusion_matrix(y_all, pred, labels=range(4)).tolist(), "classes": CLASSES,
            "n": int(len(real)), "support": {c: int((y_all == i).sum()) for i, c in enumerate(CLASSES)}}


# ---------------------------------------------------------------- export
def export(df: pd.DataFrame, args, primary: dict, cat: dict, ablation: dict) -> None:
    from onnxmltools import convert_xgboost
    from onnxmltools.convert.common.data_types import FloatTensorType
    import onnxruntime as ort

    rng = np.random.default_rng(SEED)
    real = df[df.is_real_behavior]
    lex = df[~df.is_real_behavior]
    if args.lex_rows is not None and len(lex) > args.lex_rows:
        lex = lex.sample(args.lex_rows, random_state=SEED) if args.lex_rows > 0 else lex.iloc[0:0]
    if args.monthly and MONTHLY is not None:
        real = pd.concat([real, MONTHLY], ignore_index=True)
    synth = synthesize(real, lex, args.n_synth, rng)
    full = pd.concat([real, lex.drop(index=synth.index), synth], ignore_index=True)
    cols = DEPLOYED
    med = impute(full, cols)
    X = matrix(full, cols, med)
    w = np.where(full.is_real_behavior, args.real_weight, 1.0)
    model, dev = fit_xgb(X, full.label.to_numpy(), w, args.gpu)
    model.get_booster().feature_names = None
    onx = convert_xgboost(model, initial_types=[("input", FloatTensorType([None, len(cols)]))], target_opset=15)
    (OUT / "tracker_clf.onnx").write_bytes(onx.SerializeToString())

    pos = full[full.label == 1]
    mc, _ = fit_xgb(matrix(pos, cols, med), pos.category.map(CLASSES.index).to_numpy(),
                    np.where(pos.is_real_behavior, args.real_weight, 1.0), args.gpu, multi=len(CLASSES))
    mc.get_booster().feature_names = None
    onx_c = convert_xgboost(mc, initial_types=[("input", FloatTensorType([None, len(cols)]))], target_opset=15)
    (OUT / "tracker_clf_cat.onnx").write_bytes(onx_c.SerializeToString())

    # Parity: ONNX == trainer to 1e-4
    sample = X[rng.choice(len(X), size=min(2000, len(X)), replace=False)]
    sess = ort.InferenceSession(str(OUT / "tracker_clf.onnx"), providers=["CPUExecutionProvider"])
    out = sess.run(None, {"input": sample})
    onnx_p = np.asarray(out[1])[:, 1] if np.asarray(out[1]).ndim == 2 else np.array([o[1] for o in out[1]])
    parity = float(np.max(np.abs(onnx_p - model.predict_proba(sample)[:, 1])))
    sess_c = ort.InferenceSession(str(OUT / "tracker_clf_cat.onnx"), providers=["CPUExecutionProvider"])
    pc = np.asarray(sess_c.run(None, {"input": sample})[1])
    parity_c = float(np.max(np.abs(pc - mc.predict_proba(sample))))
    print(f"ONNX parity: binary {parity:.2e}, category {parity_c:.2e}")
    assert parity <= 1e-4 and parity_c <= 1e-4, "ONNX does not match the trainer"

    gain = model.get_booster().get_score(importance_type="gain")
    tot = sum(gain.values()) or 1.0
    importances = sorted(({"feature": cols[int(k[1:])], "gain": round(v / tot, 4)} for k, v in gain.items()),
                         key=lambda d: -d["gain"])
    # Deployment threshold: median of the per-fold validation-tuned thresholds (never test-tuned).
    thr = float(np.median([f["threshold"] for f in primary["folds"]]))
    meta = {
        "model": "xgboost binary (tracker vs not) + xgboost multi-class (category)",
        "features": cols, "availability": {c: AVAILABILITY[c] for c in cols},
        "browser_features": [c for c in cols if AVAILABILITY[c] == "browser"],
        "impute_medians": {c: round(v, 6) for c, v in med.items()},
        "threshold": round(thr, 3), "classes": CLASSES,
        "metrics_heldout_real": primary, "category_metrics": cat, "ablation": ablation,
        "onnx_parity_max_abs_err": {"binary": parity, "category": parity_c},
        "train_device": dev, "n_train": int(len(full)), "n_real_behavior": int(len(real)),
        "data_mix": {"lex_rows": args.lex_rows, "real_weight": args.real_weight, "n_synth": args.n_synth,
                     "monthly_augmentation": bool(args.monthly), "selected_by": "inner-validation F1 (reports/sweep.json)"},
        "n_synthetic": int(len(synth)), "top_features": importances[:15],
        "data": json.loads((ROOT / "train" / "data" / "dataset_info.json").read_text()) if (ROOT / "train" / "data" / "dataset_info.json").exists() else {},
    }
    (OUT / "tracker_clf_meta.json").write_text(json.dumps(meta, indent=1))
    (REPORTS / "feature_importance.json").write_text(json.dumps(importances, indent=1))
    plot(primary, importances)


def plot(primary: dict, importances: list[dict]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    cm = np.array(primary["at_0.5"]["confusion_matrix"])
    fig, ax = plt.subplots(figsize=(4.2, 3.6))
    ax.imshow(cm, cmap="Blues")
    for (i, j), v in np.ndenumerate(cm):
        ax.text(j, i, str(v), ha="center", va="center", color="black", fontsize=12)
    ax.set_xticks([0, 1], ["not tracker", "tracker"])
    ax.set_yticks([0, 1], ["not tracker", "tracker"])
    ax.set_xlabel("predicted")
    ax.set_ylabel("actual (public lists)")
    ax.set_title(f"Held-out REAL domains, F1={primary['at_0.5']['f1']}")
    fig.tight_layout()
    fig.savefig(REPORTS / "confusion_matrix.png", dpi=150)
    top = importances[:20][::-1]
    fig, ax = plt.subplots(figsize=(6, 5.5))
    ax.barh([t["feature"] for t in top], [t["gain"] for t in top], color="#8b5cf6")
    ax.set_title("Feature importance (gain), deployed model")
    fig.tight_layout()
    fig.savefig(REPORTS / "feature_importance.png", dpi=150)


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gpu", action="store_true")
    ap.add_argument("--model", default="xgboost", choices=["xgboost", "lightgbm", "ensemble"])
    ap.add_argument("--n-synth", type=int, default=20000)
    ap.add_argument("--max-lex", type=int, default=120000, help="cap on list-only (lexical) rows")
    ap.add_argument("--skip-ablation", action="store_true")
    ap.add_argument("--sweep", action="store_true", help="select data mix by INNER validation F1 (never test)")
    ap.add_argument("--real-weight", type=float, default=REAL_WEIGHT)
    ap.add_argument("--lex-rows", type=int, default=None, help="list-only rows used per fold (None = all loaded)")
    ap.add_argument("--sweep-only-monthly", action="store_true")
    ap.add_argument("--monthly", action="store_true", help="train on every month of real behaviour (train-side only)")
    args = ap.parse_args()
    args.model_kind = "lightgbm" if args.model == "lightgbm" else "xgboost"
    REPORTS.mkdir(exist_ok=True)
    t0 = time.time()

    global MONTHLY
    df = load(args.max_lex)
    MONTHLY = load_monthly(df)
    print(f"monthly real observations for train-side augmentation: {len(MONTHLY)}", flush=True)
    real = df[df.is_real_behavior]
    print(f"rows={len(df)} real={len(real)} (pos {int(real.label.sum())} / neg {int((1 - real.label).sum())})", flush=True)

    if args.sweep:
        rows = []
        grid = [(None, 4, 20000, False), (0, 1, 0, False), (None, 30, 0, False), (30000, 10, 20000, False),
                (30000, 10, 0, False), (10000, 20, 10000, False), (None, 60, 20000, False),
                (0, 1, 0, True), (None, 30, 0, True), (30000, 10, 0, True)]
        if args.sweep_only_monthly:
            grid = [g for g in grid if g[3]]
        for lex_rows, rw, ns, mo in grid:
            a = argparse.Namespace(**{**vars(args), "model_kind": "xgboost", "lex_rows": lex_rows, "real_weight": rw,
                                      "n_synth": ns, "monthly": mo})
            r, _, _ = run_cv(df, DEPLOYED, a, f"lex={lex_rows} w={rw} synth={ns}")
            val = float(np.mean([f["val_f1"] for f in r["folds"]]))
            rows.append({"lex_rows": lex_rows, "real_weight": rw, "n_synth": ns, "monthly": mo, "inner_val_f1": round(val, 4),
                         "heldout_f1_tuned": r["at_tuned_threshold"]["f1"], "heldout_pr_auc": r["at_0.5"]["pr_auc"]})
            print(rows[-1], flush=True)
        best = max(rows, key=lambda r: r["inner_val_f1"])
        print("SELECTED by inner validation:", best)
        (REPORTS / "sweep.json").write_text(json.dumps({"selected_by": "mean inner-validation F1", "rows": rows, "best": best}, indent=1))
        return

    results = {}
    results["xgboost"], oof, real_df = run_cv(df, DEPLOYED, argparse.Namespace(**{**vars(args), "model_kind": "xgboost"}), "xgboost")
    results["lightgbm"], _, _ = run_cv(df, DEPLOYED, argparse.Namespace(**{**vars(args), "model_kind": "lightgbm"}), "lightgbm")
    if args.model == "ensemble":
        results["ensemble_xgb_cnn"], _, _ = run_cv(df, DEPLOYED, argparse.Namespace(**{**vars(args), "model_kind": "xgboost"}),
                                                    "xgb+cnn", use_cnn=True)
    results["xgboost_browser_subset"], _, _ = run_cv(df, DEPLOYED, argparse.Namespace(**{**vars(args), "model_kind": "xgboost"}),
                                                     "browser", browser_eval=True)

    ablation = {}
    if not args.skip_ablation:
        xa = argparse.Namespace(**{**vars(args), "model_kind": "xgboost"})
        for name, cols in [
            ("lexical only", LEXICAL),
            ("+ structural (request-type mix, sizes)", LEXICAL + STRUCTURAL),
            ("+ behavioural (= deployed model)", DEPLOYED),
            ("behavioural+structural only (no lexical)", STRUCTURAL + BEHAVIOURAL),
            ("deployed + global-only stats (NOT deployable)", DEPLOYED + GLOBAL_ONLY),
        ]:
            r, _, _ = run_cv(df, cols, xa, name)
            ablation[name] = {"features": len(cols), "f1@0.5": r["at_0.5"]["f1"], "f1@tuned": r["at_tuned_threshold"]["f1"],
                              "pr_auc": r["at_0.5"]["pr_auc"], "balanced_accuracy": r["at_0.5"]["balanced_accuracy"]}
    cat = category_cv(df, DEPLOYED, args)
    print("category head:", cat["macro_f1"], cat["per_class_f1"], flush=True)

    primary_name = max((k for k in results if k != "xgboost_browser_subset"), key=lambda k: results[k]["at_tuned_threshold"]["f1"])
    metrics = {"primary_model": primary_name, "results": results, "category_head": cat, "ablation": ablation,
               "protocol": {"test_set": "REAL domains with REAL WhoTracks.me behaviour only", "cv": "GroupKFold(5) by domain name sans TLD",
                            "synthetic_rows": "train only, bootstrapped from the training fold's real rows",
                            "threshold": "tuned on a validation split of each training fold"},
               "seconds": round(time.time() - t0, 1)}
    (REPORTS / "metrics.json").write_text(json.dumps(metrics, indent=1))
    lines = ["| feature set | #features | F1 @0.5 | F1 @tuned | PR-AUC | balanced acc |", "|---|---|---|---|---|---|"]
    for k, v in ablation.items():
        lines.append(f"| {k} | {v['features']} | {v['f1@0.5']} | {v['f1@tuned']} | {v['pr_auc']} | {v['balanced_accuracy']} |")
    (REPORTS / "ablation.md").write_text("# Ablation (held-out REAL domains, GroupKFold)\n\n" + "\n".join(lines) + "\n")
    print(json.dumps({k: {"f1@0.5": v["at_0.5"]["f1"], "f1@tuned": v["at_tuned_threshold"]["f1"], "pr_auc": v["at_0.5"]["pr_auc"],
                          "bal_acc": v["at_0.5"]["balanced_accuracy"], "devices": v["devices"]} for k, v in results.items()}, indent=1))
    print(open(REPORTS / "ablation.md").read())
    # The deployed artifact is XGBoost (one ONNX graph that runs in agent + browser).
    export(df, args, results["xgboost"], cat, ablation)
    print(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
