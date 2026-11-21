// In-browser unknown-tracker classifier: the SAME tracker_clf.onnx the agent uses, run with
// onnxruntime-web (WASM, CPU, single thread) over the browser-observable feature subset.
// Agent-only features are imputed with the training medians shipped in the meta file.
// If onnxruntime-web fails to load, everything degrades to list-only detection.
import { browser } from "wxt/browser";
// Static import: MV3 service workers forbid dynamic import(), so ORT is bundled into the worker.
import * as ort from "onnxruntime-web/wasm";
import { behaviourFromPages, registrable, vector, type PageObs } from "./trackerFeatures";

interface Meta {
  features: string[];
  browser_features: string[];
  impute_medians: Record<string, number>;
  threshold: number;
  classes: string[];
  top_features: { feature: string; gain: number }[];
}

type Session = { run: (feeds: Record<string, unknown>) => Promise<Record<string, { data: ArrayLike<number> | unknown[] }>> };
let state: Promise<{ meta: Meta; bin: Session; cat: Session | null } | null> | null = null;

async function load() {
  try {
    ort.env.wasm.numThreads = 1; // no SharedArrayBuffer in an extension service worker
    ort.env.wasm.proxy = false;
    // The WASM binary is emitted by the bundler next to the worker and resolved via import.meta.url.
    const meta = (await (await fetch(browser.runtime.getURL("/model/tracker_clf_meta.json"))).json()) as Meta;
    const bytes = async (p: "/model/tracker_clf.onnx" | "/model/tracker_clf_cat.onnx") =>
      new Uint8Array(await (await fetch(browser.runtime.getURL(p))).arrayBuffer());
    const bin = (await ort.InferenceSession.create(await bytes("/model/tracker_clf.onnx"))) as unknown as Session;
    let cat: Session | null = null;
    try {
      cat = (await ort.InferenceSession.create(await bytes("/model/tracker_clf_cat.onnx"))) as unknown as Session;
    } catch {
      cat = null;
    }
    return { meta, bin, cat };
  } catch (e) {
    console.warn("[azkaban] onnxruntime-web unavailable, list-only mode:", e);
    return null;
  }
}

export function ready() {
  state ??= load();
  return state;
}

function probsOf(out: Record<string, { data: ArrayLike<number> | unknown[] }>): number[] {
  // XGBoost ONNX exports: [label, probabilities]; probabilities may be a tensor or a sequence of maps.
  const vals = Object.values(out);
  const p = vals[1] ?? vals[0];
  const d = p?.data as ArrayLike<number> | Record<number, number>[] | undefined;
  if (!d) return [];
  const first = (d as unknown[])[0];
  if (first && typeof first === "object") return Object.values(first as Record<number, number>);
  return Array.from(d as ArrayLike<number>);
}

export interface UnknownTracker {
  domain: string;
  category: string;
  confidence: number;
  topFeatures: { feature: string; value: number; median: number }[];
}

export async function classify(host: string, pages: PageObs[]): Promise<UnknownTracker | null> {
  const s = await ready();
  if (!s) return null;
  const domain = registrable(host);
  const x = vector(domain, behaviourFromPages(pages), s.meta.features, s.meta.impute_medians);
  const tensor = new ort.Tensor("float32", x, [1, x.length]);
  const p = probsOf(await s.bin.run({ input: tensor }))[1] ?? 0;
  if (p < s.meta.threshold) return null;
  let category = "tracking";
  if (s.cat) {
    const pc = probsOf(await s.cat.run({ input: tensor }));
    if (pc.length) category = s.meta.classes[pc.indexOf(Math.max(...pc))] ?? category;
  }
  const topFeatures: UnknownTracker["topFeatures"] = [];
  for (const { feature } of s.meta.top_features) {
    const i = s.meta.features.indexOf(feature);
    const med = s.meta.impute_medians[feature] ?? 0;
    if (i >= 0 && Math.abs(x[i]! - med) > 1e-6) topFeatures.push({ feature, value: Math.round(x[i]! * 1000) / 1000, median: Math.round(med * 1000) / 1000 });
    if (topFeatures.length >= 4) break;
  }
  return { domain, category, confidence: Math.round(p * 1000) / 1000, topFeatures };
}

/** Byte-identical to azkaban_agent/tracker_clf.py insight(). */
export function insight(c: UnknownTracker) {
  return {
    type: "insight",
    key: `unknown_tracker:${c.domain}`,
    kind: "unknown_tracker",
    level: "warn",
    title: `Likely tracker not on any list: ${c.domain}`,
    detail: `${c.category}, confidence ${c.confidence.toFixed(2)}; flagged by behaviour+structure, not a blocklist`,
    data: { domain: c.domain, category: c.category, confidence: c.confidence, topFeatures: c.topFeatures },
  };
}
