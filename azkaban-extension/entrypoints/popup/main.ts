import { browser } from "wxt/browser";
import { registrable, hostOf } from "../../lib/domain";
import { getTab, type TabStats } from "../../lib/tabs";
import type { SiteAudit } from "../../lib/audit";
import { getSettings, type Settings } from "../../lib/store";
import { lookup } from "../../lib/trackers";

const app = document.getElementById("app")!;
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

async function activeTab() {
  const forced = Number(new URLSearchParams(location.search).get("tab"));
  if (forced) return browser.tabs.get(forced);
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function render(site: string, t: TabStats | null, a: SiteAudit | null, s: Settings) {
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
  app.innerHTML = `
    <header class="row between">
      <div class="row"><span class="logo">Az</span><div><strong>The Trace</strong><div class="muted mono" data-testid="site">${esc(site || "—")}</div></div></div>
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
    <section class="card grid3" aria-label="This page">
      <div><div class="stat" data-testid="requests">${t?.requests ?? 0}</div><div class="muted">requests</div></div>
      <div><div class="stat" style="color:var(--danger)" data-testid="trackers">${t?.trackers ?? 0}</div><div class="muted">Dementors</div></div>
      <div><div class="stat" style="color:var(--hero)">${t?.pii ?? 0}</div><div class="muted">data leaks</div></div>
    </section>
    ${t?.harvest?.length ? `<section class="card" style="border-color:var(--danger)" data-testid="harvest"><strong style="color:var(--danger)">Form data sent before you pressed submit</strong><ul>${t.harvest.map((h) => `<li class="muted">your <b style="color:var(--text)">${esc(h.field)}</b> → <span class="mono">${esc(h.host)}</span> (${esc(h.via)})</li>`).join("")}</ul></section>` : ""}
    ${t?.fpFlagged ? `<section class="card" style="border-color:var(--danger)" data-testid="fp-flag"><strong style="color:var(--danger)">Fingerprinting detected</strong><div class="muted">${t.fingerprint}/6 surfaces probed in 2s (canvas, WebGL, audio, fonts, device, screen)${t.fpFrames?.length ? ` by ${esc(t.fpFrames.join(", "))}` : ""}.</div></section>` : t?.fingerprint ? `<div class="muted">Fingerprint surfaces touched: ${t.fingerprint}/6</div>` : ""}
    ${a ? `<section class="card" aria-label="Cookies and storage" data-testid="audit">
      <div class="row between"><strong>Cookies &amp; storage</strong><span class="muted mono">${a.cookies.total} cookies</span></div>
      <div class="muted">${a.cookies.thirdParty} third-party · ${a.cookies.longLived} live &gt;1 year · ${a.cookies.tracking} tracking names${a.cookies.insecure ? ` · ${a.cookies.insecure} insecure` : ""}</div>
      ${a.supercookies.length ? `<div style="color:var(--danger)" data-testid="supercookie">Supercookie: the same ID is kept in ${esc(a.supercookies[0]!.places.join(" + "))} (survives cookie clearing)</div>` : ""}
      ${a.synced.length ? `<div style="color:var(--warning)" data-testid="synced">ID syncing: one ID shared across ${esc(a.synced[0]!.domains.join(", "))}</div>` : ""}
    </section>` : ""}
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
  render(site, id !== undefined ? await getTab(id) : null, audit ?? null, await getSettings());
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
