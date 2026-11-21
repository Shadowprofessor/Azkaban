# Ablation (held-out REAL domains, GroupKFold)

| feature set | #features | F1 @0.5 | F1 @tuned | PR-AUC | balanced acc |
|---|---|---|---|---|---|
| lexical only | 62 | 0.5668 | 0.78 | 0.6973 | 0.5363 |
| + structural (request-type mix, sizes) | 72 | 0.7854 | 0.8194 | 0.8472 | 0.7184 |
| + behavioural (= deployed model) | 78 | 0.8146 | 0.822 | 0.8714 | 0.755 |
| behavioural+structural only (no lexical) | 16 | 0.8139 | 0.8113 | 0.8845 | 0.7507 |
| deployed + global-only stats (NOT deployable) | 83 | 0.8219 | 0.8304 | 0.8868 | 0.7626 |
