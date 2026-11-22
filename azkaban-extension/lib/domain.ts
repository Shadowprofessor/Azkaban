// Registrable domain (eTLD+1) heuristic — good enough to group a site's requests.
const SECOND_LEVEL = new Set(["co", "com", "net", "org", "gov", "ac", "edu", "ne", "or", "go"]);

export function registrable(host: string): string {
  const h = host.toLowerCase().replace(/\.$/, "");
  if (/^\d+\.\d+\.\d+\.\d+$/.test(h) || h.includes(":")) return h;
  const labels = h.split(".");
  if (labels.length >= 3 && labels.at(-1)!.length === 2 && SECOND_LEVEL.has(labels.at(-2)!)) {
    return labels.slice(-3).join(".");
  }
  return labels.slice(-2).join(".");
}

export function hostOf(url: string | undefined): string {
  if (!url) return "";
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}

export function isWebUrl(url: string | undefined): boolean {
  return !!url && /^https?:/i.test(url);
}

/** Ports Azkaban itself uses on this machine: website, agent socket, proxy, GhostPrint, Ollama. */
export const AZKABAN_PORTS = new Set(["5173", "8787", "8080", "8765", "11434"]);
const LOOPBACK = /^(localhost|127\.\d+\.\d+\.\d+|\[::1\])$/i;

/** True for Azkaban's own traffic (the dashboard page and its calls), which is not the user's. */
export function isAzkabanOwn(url: string | undefined): boolean {
  if (!url) return false;
  try {
    const u = new URL(url);
    return LOOPBACK.test(u.hostname) && AZKABAN_PORTS.has(u.port);
  } catch {
    return false;
  }
}
