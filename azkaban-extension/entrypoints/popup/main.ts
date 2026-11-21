import { browser } from "wxt/browser";
import { registrable, hostOf } from "../../lib/domain";
import { getTab, type TabStats } from "../../lib/tabs";
import type { SiteAudit } from "../../lib/audit";

const app = document.getElementById("app")!;
const esc = (s: string) => s.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);

async function activeTab() {
  const forced = Number(new URLSearchParams(location.search).get("tab"));
  if (forced) return browser.tabs.get(forced);
  const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
  return tab;
}

function render(site: string, t: TabStats | null, a: SiteAudit | null) {
  const companies = Object.entries(t?.companies ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const max = companies[0]?.[1] ?? 1;
  app.innerHTML = `
    <header class="row between">
      <div class="row"><span class="logo">Az</span><div><strong>The Trace</strong><div class="muted mono" data-testid="site">${esc(site || "—")}</div></div></div>
    </header>
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
      ${companies.length ? `<ul>${companies.map(([c, n]) => `<li style="margin:4px 0"><div class="row between"><span>${esc(c)}</span><span class="mono muted">${n}</span></div><div class="bar" style="width:${(n / max) * 100}%"></div></li>`).join("")}</ul>` : `<p class="muted">No trackers seen on this page yet.</p>`}
    </section>`;
}

async function refresh() {
  const tab = await activeTab();
  const site = registrable(hostOf(tab?.url));
  const id = tab?.id;
  const audit = id !== undefined ? ((await browser.storage.session.get(`audit:${id}`))[`audit:${id}`] as SiteAudit | undefined) : undefined;
  render(site, id !== undefined ? await getTab(id) : null, audit ?? null);
}

void refresh();
void activeTab().then((t) => t?.id !== undefined && browser.runtime.sendMessage({ type: "audit_request", tabId: t.id }).catch(() => undefined));
browser.storage.session.onChanged.addListener(() => void refresh());
