import { browser } from "wxt/browser";
import { registrable, hostOf } from "../../lib/domain";
import { getTab, type TabStats } from "../../lib/tabs";
import type { SiteAudit } from "../../lib/audit";
import { getSettings, type Settings } from "../../lib/store";
import { lookup } from "../../lib/trackers";
import { breakdownLine, computeSiteScore, gradeColor } from "../../lib/scoring";
import { getBridgeState, type BridgeState } from "../../lib/agentBridge";

const app = document.getElementById("app")!;
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

async function activeTab() {
  const forced = Number(new URLSearchParams(location.search).get("tab"));
  if (forced) return browser.tabs.get(forced);
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  return tab;
}

type Unknown = { key: string; data: { domain: string; category: string; confidence: number } };
// Deep link: ?view=radar lands on Leak Radar (the live flow view) instead of the
// marketing landing page. The website asks the ownership question once per browser
// session and then goes straight there.
const DASHBOARD_URL = "http://127.0.0.1:5173/?view=radar";

function render(site: string, t: TabStats | null, a: SiteAudit | null, s: Settings, unknown: Unknown[] = [], bridge: BridgeState = { status: "standalone", agentVersion: "", engines: {}, sent: 0, lastError: "", since: 0, queued: 0 }) {
  const paused = s.allowlist.includes(site);
  // company -> tracker domains this page contacted (for one-click blocking)
  const byCompany = new Map<string, string[]>();
  for (const d of t?.domains ?? []) {
    const { tracker, company } = lookup(d);
    if (!tracker) continue;
    const c = company || tracker.name;
    byCompany.set(c, [...(byCompany.get(c) ?? []), d]);
  }
  const companies = Object.entries(t?.companies ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const max = companies[0]?.[1] ?? 1;
  // Recomputed here rather than trusting the stored value, so an open popup is never
  // showing a grade from before the last request landed.
  const sc = computeSiteScore({
    trackers: t?.trackers ?? 0,
    unknownTrackers: t?.unknown?.length ?? 0,
    thirdParties: t?.domains?.length ?? 0,
    cookies: t?.cookies ?? a?.cookies.total ?? 0,
    fingerprinting: !!t?.fpFlagged,
  });
  const worst = sc.penalties.slice().sort((x, y) => y.points - x.points)[0];
  app.innerHTML = `
    <header class="row between">
      <div class="row"><span class="logo">Az</span><div><strong>The Trace</strong><div class="muted mono" data-testid="site">${esc(site || "—")}</div></div></div>
      <div class="agentState">
        <div class="row" data-testid="bridge" title="${bridge.status === "connected" ? esc(`Agent ${bridge.agentVersion}, ${bridge.sent} findings sent`) : "The extension works on its own; start the agent to combine browser and network views."}">
          <span class="dot ${bridge.status === "connected" ? "dot-on" : "dot-off"}"></span>
          <span class="muted" style="font-size:11px">${bridge.status === "connected" ? "Connected to agent" : "Standalone mode"}</span>
        </div>
        <a class="dashLink" href="${DASHBOARD_URL}" target="_blank" rel="noreferrer" data-testid="dashboard-link" title="${bridge.status === "connected" ? "Opens the live flow view" : "Opens the dashboard; start the agent to see live data"}">Open Dashboard \u2197</a>
      </div>
    </header>
    <section class="card" aria-label="Patronus" data-testid="patronus">
      <div class="row between">
        <div><strong>Patronus</strong> <span class="muted">${s.blockTrackers ? (paused ? "paused on this site" : "blocking trackers") : "off"}</span></div>
        <button data-act="toggle" class="${s.blockTrackers ? "" : "primary"}" data-testid="patronus-toggle">${s.blockTrackers ? "Turn off" : "Cast Patronus"}</button>
      </div>
      ${t?.blocked ? `<div class="muted" style="margin-top:4px" data-testid="blocked">${t.blocked} request${t.blocked === 1 ? "" : "s"} blocked on this page</div>` : ""}
      ${s.blockTrackers || s.customBlocks.length
        ? paused
          ? `<button data-act="resume" style="margin-top:8px;width:100%">Resume blocking on ${esc(site)}</button>`
          : `<button data-act="pause" class="danger" style="margin-top:8px;width:100%" data-testid="pause">Site broken? Pause Patronus on ${esc(site)}</button>`
        : ""}
    </section>
    <section class="card score" aria-label="Site safety score" data-testid="score">
      <div class="gradeBox" style="color:${gradeColor(sc.grade)};border-color:${gradeColor(sc.grade)}">
        <div class="grade" data-testid="grade">${sc.grade}</div>
        <div class="gradeNum" data-testid="score-value">${sc.score}<span class="muted">/100</span></div>
      </div>
      <div class="scoreMeta">
        <strong>Site safety</strong>
        <div class="muted" data-testid="breakdown">${esc(breakdownLine(sc.breakdown))}</div>
        ${worst ? `<div class="muted" style="font-size:11px">Biggest factor: ${esc(worst.label)} (-${worst.points})</div>` : `<div class="muted" style="font-size:11px">No penalties on this page.</div>`}
      </div>
    </section>
    <section class="card grid3" aria-label="This page">
      <div><div class="stat" data-testid="requests">${t?.requests ?? 0}</div><div class="muted">requests</div></div>
      <div><div class="stat" style="color:var(--danger)" data-testid="trackers">${t?.trackers ?? 0}</div><div class="muted">Dementors</div></div>
      <div><div class="stat" style="color:var(--hero)">${t?.pii ?? 0}</div><div class="muted">data leaks</div></div>
    </section>
    ${t?.harvest?.length ? `<section class="card" style="border-color:var(--danger)" data-testid="harvest"><strong style="color:var(--danger)">Form data sent before you pressed submit</strong><ul>${t.harvest.map((h) => `<li class="muted">your <b style="color:var(--text)">${esc(h.field)}</b> → <span class="mono">${esc(h.host)}</span> (${esc(h.via)})</li>`).join("")}</ul></section>` : ""}
    ${t?.fpFlagged ? `<section class="card" style="border-color:var(--danger)" data-testid="fp-flag"><strong style="color:var(--danger)">Fingerprinting detected</strong><div class="muted">${t.fingerprint}/6 surfaces probed in 2s (canvas, WebGL, audio, fonts, device, screen)${t.fpFrames?.length ? ` by ${esc(t.fpFrames.join(", "))}` : ""}.</div></section>` : t?.fingerprint ? `<div class="muted">Fingerprint surfaces touched: ${t.fingerprint}/6</div>` : ""}
    ${unknown.length ? `<section class="card" style="border-color:var(--warning)" data-testid="unknown"><strong style="color:var(--warning)">Likely trackers on no blocklist</strong><ul>${unknown.map((u) => `<li class="row between"><span class="mono">${esc(u.data.domain)}</span><span class="muted">${esc(u.data.category)} · ${u.data.confidence.toFixed(2)}</span></li>`).join("")}</ul><div class="muted" style="font-size:11px">Flagged by an on-device model from behaviour + structure.</div></section>` : ""}
    ${a ? `<section class="card" aria-label="Cookies and storage" data-testid="audit">
      <div class="row between"><strong>Cookies &amp; storage</strong><span class="muted mono">${a.cookies.total} cookies</span></div>
      <div class="muted">${a.cookies.thirdParty} third-party · ${a.cookies.longLived} live &gt;1 year · ${a.cookies.tracking} tracking names${a.cookies.insecure ? ` · ${a.cookies.insecure} insecure` : ""}</div>
      ${a.supercookies.length ? `<div style="color:var(--danger)" data-testid="supercookie">Supercookie: the same ID is kept in ${esc(a.supercookies[0]!.places.join(" + "))} (survives cookie clearing)</div>` : ""}
      ${a.synced.length ? `<div style="color:var(--warning)" data-testid="synced">ID syncing: one ID shared across ${esc(a.synced[0]!.domains.join(", "))}</div>` : ""}
    </section>` : ""}
    <section class="card row between" aria-label="Alerts" data-testid="alerts">
      <div><strong>On-page alerts</strong><div class="muted" style="font-size:11px">${s.muted ? "off" : "warn me about serious leaks as they happen"}</div></div>
      <button data-act="alerts" class="${s.muted ? "primary" : ""}" data-testid="alerts-toggle">${s.muted ? "Turn on" : "Turn off"}</button>
    </section>
    <section class="card row between" aria-label="Agent bridge" data-testid="bridge-card">
      <div><strong>Agent bridge</strong><div class="muted" style="font-size:11px">${s.agentBridge ? (bridge.status === "connected" ? `sent ${bridge.sent} finding${bridge.sent === 1 ? "" : "s"} to the agent` : bridge.queued ? `${bridge.queued} finding${bridge.queued === 1 ? "" : "s"} saved, waiting for the agent` : "on, waiting for the agent on 127.0.0.1:8787") : "off, nothing leaves this browser"}</div></div>
      <button data-act="bridge" class="${s.agentBridge ? "" : "primary"}" data-testid="bridge-toggle">${s.agentBridge ? "Turn off" : "Turn on"}</button>
    </section>
    <section class="card" aria-label="Companies">
      <div class="muted" style="margin-bottom:6px">Companies receiving data from this page</div>
      ${companies.length ? `<ul>${companies.map(([c, n]) => `<li style="margin:4px 0"><div class="row between"><span>${esc(c)}</span><span class="row"><span class="mono muted">${n}</span>${byCompany.get(c) ? (byCompany.get(c)!.every((d) => s.customBlocks.includes(d)) ? `<button data-act="unblock" data-domains="${esc(byCompany.get(c)!.join(","))}">Unblock</button>` : `<button data-act="block" data-domains="${esc(byCompany.get(c)!.join(","))}">Block</button>`) : ""}</span></div><div class="bar" style="width:${(n / max) * 100}%"></div></li>`).join("")}</ul>` : `<p class="muted">No trackers seen on this page yet.</p>`}
    </section>`;
}

async function refresh() {
  const tab = await activeTab();
  const site = registrable(hostOf(tab?.url));
  const id = tab?.id;
  const audit = id !== undefined ? ((await browser.storage.session.get(`audit:${id}`))[`audit:${id}`] as SiteAudit | undefined) : undefined;
  const stats = id !== undefined ? await getTab(id) : null;
  const allUnknown = ((await browser.storage.session.get("unknown"))["unknown"] as Unknown[] | undefined) ?? [];
  // Flagged anywhere, and contacted by the page currently in this tab.
  const mine = allUnknown.filter((u) => stats?.domains?.includes(u.data.domain) || stats?.unknown?.includes(u.data.domain));
  render(site, stats, audit ?? null, await getSettings(), mine, await getBridgeState());
  currentSite = site;
}

let currentSite = "";
app.addEventListener("click", async (ev) => {
  const btn = (ev.target as HTMLElement).closest("button[data-act]") as HTMLButtonElement | null;
  if (!btn) return;
  const act = btn.dataset.act;
  const s = await getSettings();
  const cmd =
    act === "toggle" ? { action: "toggle", on: !s.blockTrackers }
    : act === "block" ? { action: "block", domains: (btn.dataset.domains ?? "").split(",") }
    : act === "unblock" ? { action: "unblock", domains: (btn.dataset.domains ?? "").split(",") }
    : act === "alerts" ? { action: "alerts", muted: !s.muted }
    : act === "bridge" ? { action: "bridge", on: !s.agentBridge }
    : act === "pause" ? { action: "pause", site: currentSite }
    : { action: "resume", site: currentSite };
  btn.disabled = true;
  await browser.runtime.sendMessage({ type: "patronus", ...cmd }).catch(() => undefined);
  await refresh();
});
browser.storage.local.onChanged.addListener(() => void refresh());

void refresh();
void activeTab().then((t) => t?.id !== undefined && browser.runtime.sendMessage({ type: "audit_request", tabId: t.id }).catch(() => undefined));
browser.storage.session.onChanged.addListener(() => void refresh());
