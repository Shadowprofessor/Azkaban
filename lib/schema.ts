// FROZEN CONTRACT — shared between azkaban-agent (Python) and the dashboard.
// Do not change field names without agreeing with all three owners.
// The Python dataclasses in azkaban-agent/azkaban_agent/schema.py serialise
// to these exact field names.

export type PiiType =
  | 'email'
  | 'phone'
  | 'imei'
  | 'adid'
  | 'gps'
  | 'contact'
  | 'clipboard';

export interface PiiHit {
  type: PiiType;
  /** Always redacted — raw PII never leaves the agent. */
  redacted: string;
  /** 0..1 */
  confidence: number;
}

export interface Flow {
  id: string;
  /** Unix epoch milliseconds */
  ts: number;
  app: string;
  host: string;
  method: string;
  path: string;
  ip: string;
  /** ISO-3166 alpha-2, or 'ZZ' when unknown */
  country: string;
  company: string;
  tracker: { name: string; category: string } | null;
  /** false when TLS could not be intercepted (e.g. certificate pinning) */
  decrypted: boolean;
  pii: PiiHit[];
  /** 0..100 */
  severity: number;
  tcf: { vendors: number[]; purposes: number[] } | null;
  bytes: number;
}

export interface Citation {
  source: string;
  section: string;
  url: string;
}

export interface Verdict {
  flowId: string;
  status: 'compliant' | 'questionable' | 'violation';
  reasoning: string;
  citations: Citation[];
}

export interface Score {
  /** 0..1000 */
  total: number;
  categories: { name: string; value: number }[];
}
