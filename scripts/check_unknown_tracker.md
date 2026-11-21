# unknown_tracker — end-to-end consistency check

Verifies that the agent emits it, the dashboard renders it, the extension flags it, and the
insight JSON is byte-identical across runtimes.

1. **Agent emits** (branch `Sachit`):
   ```bash
   python scripts/check_unknown_tracker.py --out unknown_expected.json
   ```
   This replays `azkaban-agent/demo/demo.azk` through the real Agent. The demo contains
   `px.quietpixel.io`, a pixel SDK that is on no public list and was not in the training
   data. The script fails if no `unknown_tracker` insight is emitted. It also runs in CI as
   `tests/test_tracker_clf.py::test_agent_emits_unknown_tracker_on_demo_replay`.

2. **Extension flags the same insight, byte-identical** (branch `Chromium-extension`):
   ```bash
   cd azkaban-extension && npx wxt build
   node e2e/insight_parity.mjs ../unknown_expected.json     # prints BYTE-IDENTICAL or DRIFT
   node e2e/feature_parity.mjs                              # TS features == Python features
   node e2e/phase_ml.mjs                                    # live in-browser detection + popup
   ```

3. **Dashboard renders** (branch `feat/ui`):
   run `python -m azkaban_agent replay azkaban-agent/demo/demo.azk` and open `/insights`. The
   "Unlisted tracker" card shows the domain, category, a confidence bar and the top features.

Last run (2026-11-22): agent emitted `quietpixel.io`, the extension output was
BYTE-IDENTICAL, feature parity was 668/668, the popup flagged it in-browser, and the dashboard
rendered the card.
