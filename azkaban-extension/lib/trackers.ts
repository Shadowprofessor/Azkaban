// Host -> tracker -> parent company, from the same bundled Exodus Privacy + DuckDuckGo
// Tracker Radar data the agent uses (built by azkaban-agent/scripts/build_trackers.py).
import data from "../../azkaban-agent/azkaban_agent/data/trackers.json";

interface TrackerData {
  trackers: Record<string, [string, string, string]>;
  owners: Record<string, string>;
}
const db = data as unknown as TrackerData;

function* suffixes(host: string) {
  const parts = host.toLowerCase().replace(/\.$/, "").split(".");
  for (let i = 0; i < parts.length - 1; i++) yield parts.slice(i).join(".");
}

const cache = new Map<string, { tracker: { name: string; category: string } | null; company: string }>();

export function lookup(host: string) {
  const hit = cache.get(host);
  if (hit) return hit;
  let tracker: { name: string; category: string } | null = null;
  let company = "";
  for (const s of suffixes(host)) {
    if (!tracker && db.trackers[s]) {
      const [name, category, owner] = db.trackers[s];
      tracker = { name, category };
      company ||= owner;
    }
  }
  for (const s of suffixes(host)) {
    if (db.owners[s]) {
      company = db.owners[s];
      break;
    }
  }
  const res = { tracker, company };
  if (cache.size > 5000) cache.clear();
  cache.set(host, res);
  return res;
}

export function isTrackerDomain(domain: string): boolean {
  return [...suffixes(domain)].some((s) => !!db.trackers[s]);
}
