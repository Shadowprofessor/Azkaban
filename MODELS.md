# Models — what they are, how they were evaluated, and how good they really are

All inference runs locally on CPU (ONNX Runtime in the agent, onnxruntime-web/WASM in the
extension). Training is offline; the tracker classifier was trained on an NVIDIA RTX 5060
Laptop GPU (`device=cuda`). No user data is used for training.

| model | task | labels | evaluation | headline (honest) |
|---|---|---|---|---|
| Unknown-tracker classifier (XGBoost → ONNX) | is an UNLISTED third-party domain a tracker? + category | REAL: public blocklists | held-out REAL domains with REAL behaviour, GroupKFold by domain | **F1 0.822**, PR-AUC 0.871, balanced acc 0.755 |
| Flow severity (XGBoost → ONNX) | 0-100 risk score per flow | **synthetic, rubric-labelled** | held-out synthetic rows | R² 0.986 — **circular, not evidence of real-world accuracy** |
| Beacon anomaly (IsolationForest) | unusual request patterns | none (unsupervised) | unit tests only | no accuracy claim |

---

## 1. Unknown-tracker classifier (`tracker_clf.onnx`)

**Goal:** catch trackers that are on *no* blocklist, from how they behave rather than their name.

### Data (built by `train/build_dataset.py`, setup-time only, public sources)
- **Positives:** a registrable domain is a tracker if ≥1 public list blocks it domain-wide.
  Lists: DuckDuckGo Tracker Radar (`default: block`), Exodus Privacy, EasyList, EasyPrivacy,
  AdGuard Base, AdGuard Tracking Protection, Disconnect (tracking categories), and Peter
  Lowe's list.
- **Negatives:** Tranco and Cisco Umbrella top-50k domains that are on **no** list.
- **Real behaviour:** WhoTracks.me per-domain monthly aggregates (top-2,000 third parties per
  month, trackers *and* non-trackers), 2025-10 … 2026-10.
- Dataset: 204,339 registrable domains (163,215 positive / 41,124 negative). **2,765 have
  real behaviour** (1,767 positive / 998 negative). Those 2,765 form the only test pool.

### Features (`azkaban_agent/tracker_features.py`, shared by training, agent and extension)
- **Lexical:** registrable name length, entropy, digits, hyphens, vowels, TLD flags, 22
  keyword flags, 32 hashed char-3-gram buckets.
- **Structural:** per-page share of script / iframe / beacon / image / stylesheet / font / xhr /
  media requests, log requests per page, log bytes per page.
- **Behavioural:** per-page share with cookies, UID in the query string, https, referer
  leaked, SameSite=None cookies (agent-only), plus `has_behavior`.
- **Global-only stats** (reach, Ghostery's own tracking heuristic): can't be measured
  locally, so they're used **only in the ablation, never deployed.** `has_blocking` was dropped
  (it is literally the label's cousin, and constant in the data anyway).

### Protocol
- 5-fold **GroupKFold** over the real-behaviour domains. The group is the domain name without
  its TLD, so `doubleclick.net` / `doubleclick.com` never straddle train and test.
- Training side of each fold = the other folds' real rows + list-only rows (no behaviour,
  median-imputed, `has_behavior=0`) whose group is not in the test fold.
- Thresholds are tuned on a **validation split carved from the training fold**, never on test.
- The data mix (how many list-only rows, real-row weight, synthetic rows, extra months) was
  chosen from 10 candidates **by inner-validation F1 only** (`reports/sweep.json`).
- **A bug we found and fixed:** synthetic behaviour was first bootstrapped before the
  validation split, so it leaked validation domains into training. Inner-validation F1 read
  0.90 while held-out read 0.81. After the fix the two agree (0.835 vs 0.822). Synthetic rows
  no longer help, so the shipped model uses **none**. Extra real months also did not help
  (validation 0.829 vs 0.835).

### Results — held-out REAL domains (n = 2,765)
| model | F1 @0.5 | F1 @tuned | precision / recall @tuned | PR-AUC | ROC-AUC | balanced acc |
|---|---|---|---|---|---|---|
| **XGBoost (deployed, GPU)** | 0.815 | **0.822** | 0.760 / 0.895 | 0.871 | 0.824 | 0.755 |
| LightGBM (CPU; pip wheel lacks GPU) | 0.819 | 0.825 | — | 0.880 | — | 0.752 |
| XGBoost + char-CNN ensemble (GPU) | 0.786 | 0.806 | — | 0.851 | — | 0.748 |
| XGBoost, browser-observable features only | 0.796 | 0.822 | — | 0.872 | — | 0.750 |

Confusion matrix (XGBoost, threshold 0.5): TN 709, FP 289, FN 354, TP 1413.
Per-fold F1 at the tuned threshold: 0.801 / 0.824 / 0.839 / 0.837 / 0.810. Deployed threshold:
0.23 (the median of the fold-validation thresholds), which is recall-leaning.

- **Why XGBoost over LightGBM:** the +0.003 difference is within fold-to-fold noise, and
  XGBoost trains on the GPU and exports to one ONNX graph for both runtimes.
- **Why no deep learning:** the char-CNN ensemble *lowered* held-out F1, so it is not shipped.

### Ablation (same folds)
| feature set | F1 @0.5 | F1 @tuned | PR-AUC | balanced acc |
|---|---|---|---|---|
| lexical only | 0.567 | 0.780 | 0.697 | 0.536 |
| + structural | 0.785 | 0.819 | 0.847 | 0.718 |
| + behavioural (= deployed) | 0.815 | 0.822 | 0.871 | 0.755 |
| behavioural + structural only | 0.814 | 0.811 | 0.885 | 0.751 |
| deployed + global-only stats (not deployable) | 0.822 | 0.830 | 0.887 | 0.763 |

Lexical features alone are near-useless: balanced accuracy 0.54, and the 0.78 tuned F1 comes
from calling nearly everything a tracker. **Request structure and behaviour carry the model.**
The earlier lexical RandomForest (ROC-AUC ~0.60) was rightly rejected.

### Category head (advertising / analytics / social / fingerprinting)
Macro-F1 **0.357**: advertising 0.758, analytics 0.598, social 0.000 (12 real examples),
fingerprinting 0.071 (27 real examples). The category is a weak hint, not a finding.

### Why not 0.93
We targeted ≥0.93 F1 and reached **0.82**. Main reasons, in our judgement:
1. **Label noise at the domain level.** "Blocked domain-wide by some list" is not the same as
   "behaves like a tracker". Many of the 998 real "negatives" are third parties with
   tracker-like traffic that no list blocks domain-wide, and some list entries are big
   multi-purpose domains.
2. **Only 2,765 domains have real behaviour.** More months of the same domains added nothing.
3. **Locally computable behaviour is coarser** than population statistics. Even adding those
   statistics only reaches 0.83.

We chose to ship an honest 0.82 rather than a leaky or self-labelled 0.93.

### Runtime and consistency
- **Agent:** an app's 30-second request burst counts as one page. A domain is scored after 3+
  pages, only if it is on no bundled list, and emits `unknown_tracker`.
- **Extension:** one tab navigation counts as one page. The same `tracker_clf.onnx` runs in
  onnxruntime-web inside the MV3 service worker. Agent-only features are median-imputed.
- **Checks:** feature parity Python ↔ TypeScript is 668/668 values. For the same observations,
  the agent's and the extension's insight JSON is **byte-identical**
  (`scripts/check_unknown_tracker.md`). ONNX matches the trainer to 4.8e-7.

### Reproduce
```bash
python train/build_dataset.py --months 12 --tranco 50000
python train/train_tracker.py --gpu --sweep                       # selection by inner validation
python train/train_tracker.py --gpu --model ensemble --lex-rows 30000 --real-weight 10 --n-synth 0
```
Reports: `reports/metrics.json`, `reports/ablation.md`, `reports/sweep.json`,
`reports/confusion_matrix.png`, `reports/feature_importance.png`.

Licences: WhoTracks.me data (CC BY 4.0); Ghostery TrackerDB categories (CC BY-NC-SA 4.0,
non-commercial; used only as category votes); EasyList/EasyPrivacy (GPLv3 / CC BY-SA 3.0);
AdGuard filters (GPLv3); Disconnect (GPLv3); DDG Tracker Radar (CC BY-NC-SA 4.0);
Tranco / Umbrella top lists (free research use).

---

## 2. Flow severity (`severity.onnx`) — read the caveat

An XGBoost regressor (11 features: PII types and sensitivity, tracker, cross-border, consent,
app/PII mismatch, ad-ID reuse, decrypted, hashed PII, idle time) giving a 0-100 score.

**Caveat:** no labelled dataset of "how bad is this flow" exists. We generated synthetic
flows and labelled them with our own expert rubric plus noise, then tested on more of the
same. The reported **R² 0.986 / MAE 3.05 only shows the model reproduces our rubric** —
that is circular and is *not* evidence of real-world accuracy. Treat severity as a
consistent, explainable ranking heuristic. Trained on CPU (before GPU access was set up).

## 3. Beacon anomaly (IsolationForest)

Unsupervised outlier detection over per-(app, host) request series: count, mean gap, gap
regularity, bytes, idle share, PII rate. It complements the classifier at runtime
(`beacon_anomaly` insights) and makes no accuracy claim.
