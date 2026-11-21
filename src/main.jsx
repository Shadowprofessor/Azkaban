import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { useVirtualizer } from '@tanstack/react-virtual';
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowRight, ArrowUpRight, BadgeCheck,
  Ban, Bell, Blocks, BookOpenCheck, Check, CheckCircle2, ChevronDown, ChevronRight,
  CircleHelp, Clipboard, Clock3, Code2, Cookie, Copy, Database, Download, ExternalLink,
  Eye, EyeOff, Fingerprint, FileArchive, FileCheck2, FileKey2, FileText, Filter, Github,
  Globe2, HardDrive, Hash, Hexagon, Info, KeyRound, Laptop, Link2, ListFilter, LoaderCircle,
  LockKeyhole, Mail, MapPin, Menu, Network, Radar, RefreshCw, Search, Send, Settings2,
  Shield, ShieldAlert, ShieldCheck, Smartphone, Sparkles, SquareArrowOutUpRight, Terminal,
  TriangleAlert, Wifi, X, Zap
} from 'lucide-react';
import { AGENT_SOCKET_DEFAULT, formatBytes, validateInbound } from './schema';
import { OUTBOUND } from './protocol';
import { useGhostStore } from './store';
import { availableCorrelationCategories, deriveIdentityCorrelations, deriveIdleActivity } from './privacyFeatures';
import { verifyEvidenceChain } from './integrity';
import { LEGAL_KINDS, LEGAL_REFERENCES, LEGAL_TOPICS } from './legalReferences';
import './styles.css';
import './ledger.css';

const wsOverride = (import.meta.env.VITE_AGENT_WS_URL || '').trim();
const socketKey = 'ghostprint-agent-url';
const getAgentUrl = () => localStorage.getItem(socketKey) || wsOverride || AGENT_SOCKET_DEFAULT;
const countryNames = { US: 'United States', IL: 'Israel', IE: 'Ireland', IN: 'India', SG: 'Singapore', GB: 'United Kingdom', DE: 'Germany' };
const piiNames = { adid: 'Advertising ID', gps: 'Location', imei: 'IMEI', email: 'Email', phone: 'Phone', contact: 'Contacts', clipboard: 'Clipboard' };
const piiShort = { adid: 'AD ID', gps: 'GPS', imei: 'IMEI', email: 'EMAIL', phone: 'PHONE', contact: 'CONTACT', clipboard: 'CLIPBOARD' };
const navItems = [
  { id: 'report', label: 'Privacy report', icon: ShieldCheck, priority: 'SUMMARY' },
  { id: 'radar', label: 'Leak Radar', icon: Radar, priority: 'FLOWS' },
  { id: 'idle', label: 'While away', icon: Clock3, priority: 'BACKGROUND' },
  { id: 'insights', label: 'Insights', icon: Sparkles, priority: 'SUMMARY' },
  { id: 'map', label: 'Shadow Map', icon: Network, priority: 'MAP' },
  { id: 'correlation', label: 'Same ID across apps', icon: Fingerprint, priority: 'CROSS-APP' },
  { id: 'legal', label: 'Legal', icon: BookOpenCheck, priority: 'GUIDANCE' },
  { id: 'actions', label: 'Actions', icon: CheckCircle2, priority: 'OPTIONS' },
  { id: 'evidence', label: 'Proof & records', icon: FileCheck2, priority: 'EXPORT' },
  { id: 'footprint', label: 'Link apps', icon: Link2, priority: 'ACCOUNTS' },
];

function App() {
  const agent = useGhostStore((s) => s.agent);
  const connected = useGhostStore((s) => s.agent.connected);
  const flows = useGhostStore((s) => s.flows);
  const score = useGhostStore((s) => s.score);
  const linkedApps = useGhostStore((s) => s.linkedApps);
  const verdicts = useGhostStore((s) => s.verdicts);
  const consent = useGhostStore((s) => s.consent);
  const selectedFlowId = useGhostStore((s) => s.selectedFlowId);
  const filters = useGhostStore((s) => s.filters);
  const selectedVerdict = useGhostStore((s) => selectedFlowId ? s.verdicts[selectedFlowId] : undefined);
  const [page, setPage] = useState('report');
  const [device, setDevice] = useState('laptop');
  const [socketUrl, setSocketUrl] = useState(getAgentUrl());
  const [urlDraft, setUrlDraft] = useState(getAgentUrl());
  const [drawer, setDrawer] = useState(false);
  const [toast, setToast] = useState('');
  const [search, setSearch] = useState('');
  const [settings, setSettings] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [notifications, setNotifications] = useState(false);
  const [idleThresholdMs, setIdleThresholdMs] = useState(5 * 60 * 1000);
  const [toastTimer, setToastTimer] = useState(0);
  const socketRef = useRef(null);
  const flushRef = useRef([]);
  const socketUrlRef = useRef(socketUrl);
  const store = useGhostStore;
  const notify = useCallback((message) => {
    setToast(message);
    window.clearTimeout(toastTimer);
    setToastTimer(window.setTimeout(() => setToast(''), 3000));
  }, [toastTimer]);

  useEffect(() => { socketUrlRef.current = socketUrl; }, [socketUrl]);
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const outcome = params.get('oauth');
    if (outcome !== 'connected' && outcome !== 'disconnected') return;
    const provider = params.get('provider');
    const providerName = { instagram: 'Instagram', reddit: 'Reddit', spotify: 'Spotify', google: 'Google', github: 'GitHub' }[provider];
    if (providerName && outcome === 'connected') {
      const linked = store.getState().linkedApps;
      if (!linked.includes(providerName)) store.getState().setLinkedApps([...linked, providerName]);
      notify(`${providerName} account connected.`);
    }
    if (providerName && outcome === 'disconnected') {
      const linked = store.getState().linkedApps;
      store.getState().setLinkedApps(linked.filter((item) => item !== providerName));
      notify(`${providerName} account disconnected.`);
    }
    window.history.replaceState({}, '', window.location.pathname + window.location.hash);
  }, [notify, store]);
  useEffect(() => {
    let alive = true;
    let retryTimer;
    let flushTimer;
    let attempts = 0;
    const connect = () => {
      if (!alive) return;
      store.getState().setAgent({ connected: false, known: false });
      let socket;
      try { socket = new WebSocket(socketUrlRef.current); }
      catch (error) {
        store.getState().setAgent({ connected: false, known: true, capturing: false });
        store.getState().setError(`Could not open ${socketUrlRef.current}. ${error.message || ''}`);
        retryTimer = window.setTimeout(connect, Math.min(1000 * (2 ** attempts++), 5000));
        return;
      }
      socketRef.current = socket;
      socket.onopen = () => {
        attempts = 0;
        store.getState().setAgent({ connected: true, known: true });
        store.getState().clearError();
      };
      socket.onmessage = (event) => {
        let message;
        try { message = JSON.parse(event.data); } catch { return; }
        if (!validateInbound(message)) return;
        const { type, data } = message;
        if (type === 'status') {
          store.getState().setAgent({ connected: true, known: true, capturing: !!data.capturing, device: data.device || device, version: data.agentVersion || '', idleMonitoring: data.idleMonitoring || null, idleThresholdMs: data.idleThresholdMs || null });
          if (Number.isFinite(data.idleThresholdMs) && data.idleThresholdMs > 0) setIdleThresholdMs(data.idleThresholdMs);
        }
        if (type === 'flow') flushRef.current.push(data);
        if (type === 'verdict') store.getState().setVerdict(data);
        if (type === 'score') store.getState().setScore(data);
        if (type === 'blocklist') store.getState().setBlocklist(data);
        if (type === 'evidence') store.getState().setEvidence(data);
        if (type === 'error') store.getState().setError(data.message || 'The local agent reported an error.');
      };
      socket.onerror = () => {
        store.getState().setAgent({ connected: false, known: true });
      };
      socket.onclose = () => {
        store.getState().setAgent({ connected: false, known: true });
        if (alive) retryTimer = window.setTimeout(connect, Math.min(1000 * (2 ** attempts++), 5000));
      };
    };
    connect();
    flushTimer = window.setInterval(() => {
      if (!flushRef.current.length) return;
      const batch = flushRef.current.splice(0, 250);
      store.getState().addFlows(batch);
    }, 100);
    return () => {
      alive = false;
      window.clearTimeout(retryTimer);
      window.clearInterval(flushTimer);
      if (socketRef.current) { socketRef.current.onclose = null; socketRef.current.close(); }
    };
  }, [socketUrl, store, device]);

  useEffect(() => {
    const keydown = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); document.querySelector('#flow-search')?.focus(); }
      if (event.key === 'Escape') { setDrawer(false); setSettings(false); setNotifications(false); }
    };
    window.addEventListener('keydown', keydown);
    return () => window.removeEventListener('keydown', keydown);
  }, []);
  const selectedFlow = flows.find((flow) => flow.id === selectedFlowId);
  const send = useCallback((payload) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) { notify('Local agent is offline. Start it, then wait for the connection.'); return false; }
    socket.send(JSON.stringify(payload));
    return true;
  }, [notify]);
  const selectFlow = (id) => { store.getState().selectFlow(id); setDrawer(true); };

  if (!consent) return <ConsentGate agent={agent} device={device} setDevice={setDevice} socketUrl={socketUrl} onAccept={() => { store.getState().setConsent(true); setPage('report'); }} onSettings={() => setSettings(true)} />;

  const filteredFlows = flows.filter((flow) => {
    const query = search.trim().toLowerCase();
    return (!query || `${flow.app} ${flow.host} ${flow.company || ''} ${flow.id}`.toLowerCase().includes(query))
      && (!filters.app || flow.app === filters.app)
      && (!filters.piiType || flow.pii?.some((item) => item.type === filters.piiType))
      && flow.severity >= filters.minSeverity;
  });

  return <div className="console-shell">
    <aside className={`sidebar ${mobileNav ? 'mobile-open' : ''}`}>
      <button className="brand-home" onClick={() => store.getState().setConsent(false)} aria-label="Return to GhostPrint landing page"><Brand/><span>HOME</span></button>
      <div className="local-device"><div className="device-icon"><Laptop size={15}/></div><div><b>This device</b><span>Local audit session</span></div><span className={`presence ${connected ? 'online' : ''}`}/></div>
      <div className="side-label">YOUR PRIVACY</div>
      <nav className="side-nav">{navItems.map(({ id, label, icon: Icon, priority }) => <button key={id} className={`side-link ${page === id ? 'active' : ''}`} onClick={() => { setPage(id); setMobileNav(false); }}><Icon size={17}/><span>{label}</span><small>{priority}</small></button>)}</nav>
      <div className="sidebar-rule"/>
      <div className="side-label section-label">APP LINKS</div>
      <div className="session-card"><div className="session-head"><span className="session-pulse"/><b>Linked accounts</b><small>{linkedApps.length} LINKED</small></div><span className="session-url">{linkedApps.length ? linkedApps.join(' · ') : 'Instagram · Reddit · Spotify'}</span><button onClick={() => setPage('footprint')}><Link2 size={13}/> Manage app links</button></div>
      <div className="sidebar-rule"/>
      <div className="privacy-note"><Shield size={15}/><p><b>Choose your apps. Review their permissions.</b><br/>Choose which accounts to link. Review the requested access before authorizing each service.</p></div>
      <div className="sidebar-bottom"><div className="agent-version"><span>GHOSTPRINT</span><b>v2.0.0 <i>LOCAL-FIRST</i></b></div><button title="About GhostPrint" onClick={() => notify('GhostPrint audits only devices and networks you own.') }><CircleHelp size={15}/></button></div>
    </aside>

    <main className="main-column">
      <header className="topbar"><div className="top-left"><button className="icon-btn mobile-menu" onClick={() => setMobileNav(!mobileNav)}><Menu size={17}/></button><div className="crumb"><span>Workspace</span><ChevronRight size={13}/><b>{navItems.find((item) => item.id === page)?.label}</b></div></div><div className="top-right"><div className={`agent-pill ${connected ? 'connected' : 'offline'} ${agent.version?.startsWith('mock-')?'demo-agent':''}`}><span/><b>{agent.version?.startsWith('mock-')?'Synthetic demo agent':connected?'Audit service connected':'Audit service offline'}</b><small>{agent.version?.startsWith('mock-')?'DEMO DATA':'LOCAL AUDIT'}</small></div><button className="icon-btn" onClick={() => setNotifications(!notifications)} title="Alerts"><Bell size={16}/>{flows.some((flow) => flow.severity >= 75) && <i className="alert-dot"/>}</button>{notifications && <div className="alerts-pop"><div><b>Recent alerts</b><button onClick={() => setNotifications(false)}><X size={13}/></button></div>{flows.filter((flow) => flow.severity >= 75).slice(0, 4).map((flow) => <button key={flow.id} onClick={() => { setNotifications(false); selectFlow(flow.id); }}><ShieldAlert size={14}/><span><b>{flow.app}</b> sent {flow.pii?.[0] ? piiNames[flow.pii[0].type] : 'high-severity traffic'}<small>{flow.host}</small></span></button>)}{!flows.some((flow) => flow.severity >= 75) && <p>No high-severity alerts yet.</p>}</div>}<div className="avatar">N</div></div></header>
      {!connected && <div className="offline-banner"><div><Wifi size={15}/><span><b>Local audit service offline</b><small>Showing the latest data received. Reconnecting automatically.</small></span></div><button onClick={() => setSettings(true)}>Connection settings <ArrowRight size={13}/></button></div>}
      {page === 'report' && <ReportPage flows={flows} score={score} verdicts={verdicts} agent={agent} device={device} send={send} selectFlow={selectFlow} openActivity={() => setPage('radar')} openApps={() => setPage('footprint')} openGuidance={() => setPage('legal')}/>}
      {page === 'radar' && <RadarPage flows={filteredFlows} allFlows={flows} search={search} setSearch={setSearch} agent={agent} device={device} send={send} selectFlow={selectFlow} notify={notify}/>}
      {page === 'idle' && <IdleActivityPage flows={flows} agent={agent} threshold={idleThresholdMs} onThresholdChange={(value) => { setIdleThresholdMs(value); send(OUTBOUND.configureIdle(value)); }} selectFlow={selectFlow} openLegal={() => setPage('legal')}/>}
      {page === 'insights' && <InsightsPage flows={flows} verdicts={verdicts} openRadar={() => setPage('radar')}/>}
      {page === 'map' && <ShadowMapPage flows={flows} selectFlow={selectFlow} openRadar={(app) => { if (app) store.getState().setFilter('app', app); setPage('radar'); }}/>}
      {page === 'correlation' && <CorrelationPage flows={flows} selectFlow={selectFlow} openLegal={() => setPage('legal')}/>}
      {page === 'legal' && <LegalPage allFlows={flows} send={send} notify={notify}/>}
      {page === 'actions' && <ActionsPage flows={flows} send={send} openLegal={() => setPage('legal')} notify={notify}/>}
      {page === 'evidence' && <EvidencePage flows={flows} send={send}/>}
      {page === 'footprint' && <FootprintPage notify={notify} onFindings={() => setPage('legal')}/>}
      <footer className="app-footer"><span><span className="footer-lock"><LockKeyhole size={11}/></span> AUDITING YOUR OWN DEVICE · APP LINKS SESSION</span><span>GHOSTPRINT <i/> PRIVACY FORENSICS</span></footer>
    </main>

    {drawer && selectedFlow && <FlowDrawer flow={selectedFlow} verdict={selectedVerdict} close={() => setDrawer(false)} send={send}/>}
    {settings && <Modal title="Agent connection" eyebrow="APP LINKS SESSION" onClose={() => setSettings(false)}><div className="modal-copy">Link this dashboard to the local capture agent. By default it uses the loopback WebSocket in the frozen team contract.</div><label className="field-label" htmlFor="agent-url">WebSocket address</label><input id="agent-url" className="text-input mono-input" value={urlDraft} onChange={(event) => setUrlDraft(event.target.value)} placeholder="ws://localhost:8787"/><div className="inline-note"><ShieldCheck size={14}/> Keep the capture agent bound to <code>127.0.0.1</code>. For a forwarded port, use its WebSocket URL here.</div><div className="modal-status"><span className={`presence ${connected ? 'online' : ''}`}/>{connected ? `Linked${agent.version ? ` · ${agent.version}` : ''}` : 'Offline · reconnecting automatically'}</div><div className="modal-actions"><button className="btn secondary" onClick={() => setSettings(false)}>Cancel</button><button className="btn primary" onClick={() => { const normalized = urlDraft.trim(); if (!/^wss?:\/\//i.test(normalized)) { notify('Use a ws:// or wss:// WebSocket URL.'); return; } localStorage.setItem(socketKey, normalized); setSocketUrl(normalized); setSettings(false); notify('Agent address updated'); }}>Save connection</button></div></Modal>}
    {toast && <div className="toast"><Info size={15}/>{toast}<button onClick={() => setToast('')}><X size={13}/></button></div>}
  </div>;
}

function Brand() { return <div className="brand"><div className="brand-mark"><span/><span/><span/></div><div><b>ghostprint</b><small>PRIVACY FORENSICS</small></div><span className="brand-v2">V2</span></div>; }

function ConsentGate({ agent, device, setDevice, socketUrl, onAccept, onSettings }) {
  const [showSetup, setShowSetup] = useState(false);
  const [checked, setChecked] = useState(false);
  return <div className="consent-screen">
    <header className="consent-top">
      <Brand/>
      <nav className="landing-nav" aria-label="Main navigation">
        <a href="#method">How it works</a><a href="#evidence">Evidence</a><button onClick={() => setShowSetup(true)}>Explore your footprint <ArrowRight size={14}/></button>
      </nav>
      <span className="consent-top-status"><i/> LOCAL AUDIT</span>
    </header>
    <main className="landing-main">
      <section className="landing-hero">
        <div className="landing-hero-copy">
          <div className="hero-overline"><span>LOCAL PRIVACY FORENSICS</span><span>01 — OBSERVE</span></div>
          <h1>See what leaves.<br/><em>Know where it goes.</em></h1>
          <p className="hero-deck">A clear map of the data signals your apps send.</p>
          <div className="hero-actions"><button className="btn primary landing-cta" onClick={() => setShowSetup(true)}>Explore your footprint <ArrowRight size={15}/></button><a className="hero-text-link" href="#method">How it works <ArrowDownToLine size={13}/></a></div>
          <div className="landing-trust"><LockKeyhole size={13}/> ON YOUR DEVICE <span/> YOUR DATA, YOUR CALL</div>
        </div>
        <LandingProductVisual/>
        <div className="hero-caption"><span>FIG. 01 / A CONNECTION, MADE VISIBLE</span><span>ILLUSTRATIVE VIEW</span></div>
      </section>
      <section className="landing-proof" id="method">
        <div className="proof-intro"><span>THE METHOD / 02</span><h2>From signal<br/>to a clearer picture.</h2></div>
        <article><span className="proof-number">01</span><b>Observe</b><small>Connections on your device.</small></article>
        <article><span className="proof-number">02</span><b>Trace</b><small>Apps, companies, data signals.</small></article>
        <article id="evidence"><span className="proof-number">03</span><b>Review</b><small>Evidence and practical options.</small></article>
      </section>
    </main>
    <footer className="consent-bottom"><span><Brand/><small>LOCAL PRIVACY FORENSICS</small></span><span>BUILT FOR YOUR OWN DEVICES <i/> YOUR EVIDENCE, YOUR DECISION</span><a href="#top" onClick={(event)=>{event.preventDefault();window.scrollTo({top:0,behavior:'smooth'});}}>Back to top</a></footer>
    {showSetup && <div className="setup-overlay"><section className="consent-card setup-card" role="dialog" aria-modal="true" aria-labelledby="setup-heading"><button className="setup-close" aria-label="Close setup" onClick={() => setShowSetup(false)}><X size={17}/></button><div className="consent-card-top"><div className="consent-emblem"><Radar size={22}/><span/></div><div><span className="card-overline">BEFORE YOU BEGIN</span><h2 id="setup-heading">Choose what to review</h2></div></div><label className="field-label">DEVICE & ACCOUNT SCOPE</label><div className="device-choices"><button className={device === 'laptop' ? 'chosen' : ''} onClick={() => setDevice('laptop')}><Laptop size={16}/>My laptop<span>{device === 'laptop' && <Check size={13}/>}</span></button><button className={device === 'phone' ? 'chosen' : ''} onClick={() => setDevice('phone')}><Smartphone size={16}/>My phone<span>{device === 'phone' && <Check size={13}/>}</span></button></div><div className="agent-check-card"><span className={`agent-check-icon ${agent.connected ? 'online' : ''}`}><Link2 size={16}/></span><span><b>{agent.connected ? 'Local audit service connected' : 'Local audit service not connected'}</b><small>{agent.connected ? `Ready${agent.version ? ` ? ${agent.version}` : ''} to receive a local audit.` : 'You can review the interface now. Connect your local audit service to receive observations.'}</small></span><button onClick={onSettings}><Settings2 size={14}/> Configure</button></div><label className="consent-check"><input type="checkbox" checked={checked} onChange={(event) => setChecked(event.target.checked)}/><span className="custom-check"><Check size={12}/></span><span><b>I own this device and accounts, or have permission to review them</b><small>I authorize review only of the apps I choose to link. Capture is limited to devices and networks I own or may audit.</small></span></label><button className="btn primary continue-btn" disabled={!checked} onClick={() => { setShowSetup(false); onAccept(); }}>I confirm and continue <ArrowRight size={15}/></button><div className="consent-card-footer"><ShieldCheck size={13}/> Your account, your choice</div></section></div>}
  </div>;
}

function LandingProductVisual() {
  return <figure className="landing-product" aria-label="Illustration showing an app connection to a company and the data signal"><div className="atlas-top"><span>01 / SAMPLE TRACE</span><span><i/> LOCAL VIEW</span></div><div className="atlas-labels"><span>APPLICATION</span><span>DESTINATION</span><span>DATA SIGNAL</span></div><svg className="atlas-map" viewBox="0 0 720 300" role="img" aria-label="Sample app routes to an analytics company and an advertising company, carrying an identifier signal"><defs><pattern id="atlas-grid" width="36" height="36" patternUnits="userSpaceOnUse"><path d="M36 0H0V36" fill="none" stroke="currentColor" strokeOpacity=".09" strokeWidth="1"/></pattern></defs><rect width="720" height="300" fill="url(#atlas-grid)"/><path className="atlas-route atlas-route-one" d="M145 72 C245 72 256 114 357 114 S476 72 575 72"/><path className="atlas-route atlas-route-two" d="M145 72 C245 72 256 207 357 207 S476 224 575 224"/><path className="atlas-route atlas-route-three" d="M145 224 C245 224 256 114 357 114 S476 114 575 114"/><circle className="atlas-packet packet-one" r="4"><animateMotion dur="5s" repeatCount="indefinite" path="M145 72 C245 72 256 114 357 114 S476 72 575 72"/></circle><circle className="atlas-packet packet-two" r="4"><animateMotion dur="6.5s" begin="-3s" repeatCount="indefinite" path="M145 72 C245 72 256 207 357 207 S476 224 575 224"/></circle><g className="atlas-node app-node"><circle cx="145" cy="72" r="19"/><path d="M140 72h10M145 67v10"/></g><g className="atlas-node company-node"><circle cx="357" cy="114" r="19"/><path d="M349 114h16m-8-8v16"/></g><g className="atlas-node company-node secondary-node"><circle cx="357" cy="207" r="15"/><path d="M351 207h12m-6-6v12"/></g><g className="atlas-node data-node"><circle cx="575" cy="72" r="17"/><circle cx="575" cy="72" r="5"/></g><g className="atlas-node data-node secondary-node"><circle cx="575" cy="224" r="17"/><circle cx="575" cy="224" r="5"/></g><text x="145" y="119" textAnchor="middle">SOCIAL APP</text><text x="357" y="156" textAnchor="middle">ANALYTICS CO.</text><text x="357" y="244" textAnchor="middle">AD NETWORK</text><text x="575" y="112" textAnchor="middle">DEVICE ID</text><text x="575" y="264" textAnchor="middle">LOCATION</text></svg><div className="atlas-foot"><span><b>3</b> CONNECTIONS</span><span><b>2</b> COMPANIES</span><span>EXAMPLE / NOT LIVE DATA</span></div></figure>;
}

function IdleActivityPage({ flows, agent, threshold, onThresholdChange, selectFlow, openLegal }) {
  const { idleFlows, activeFlows, apps, destinations, uploadedBytes, hasUploadMeasurements, activeUploadedBytes, hasActiveUploadMeasurements, sensitiveSignals } = deriveIdleActivity(flows);
  const confirmed = agent.idleMonitoring?.enabled === true;
  const options = [60_000, 180_000, 300_000, 600_000];
  const formatThreshold = (value) => `${Math.round(value / 60_000)} min`;
  return <div className="page-wrap feature-page idle-page">
    <PageHeading kicker="WHEN YOU ARE AWAY" title="While you are away" description="See which apps connect when you are not using them." actions={<label className="idle-threshold">MARK AS AWAY AFTER <select value={threshold} onChange={(event) => onThresholdChange(Number(event.target.value))}>{options.map((value) => <option key={value} value={value}>{formatThreshold(value)}</option>)}</select></label>}/>
    {!confirmed && <div className="capability-note"><Info size={16}/><span><b>Waiting for the local helper</b><small>Your computer helper must report when you are away and which apps connect.</small></span></div>}
    <section className="idle-status-band"><div><span className={`presence ${confirmed ? 'online' : ''}`}/><span><b>{confirmed ? agent.idleMonitoring.state === 'idle' ? 'You are marked away' : 'Watching for away-time connections' : 'Away-time tracking unavailable'}</b><small>{confirmed && agent.idleMonitoring.since ? `Since ${new Date(agent.idleMonitoring.since).toLocaleString()}` : 'No away-time activity in this session'}</small></span></div><span className="idle-status-meta">{confirmed ? Number.isFinite(agent.idleThresholdMs) ? `HELPER ON · ${formatThreshold(agent.idleThresholdMs)}` : 'HELPER DEFAULT · THRESHOLD UNKNOWN' : 'HELPER NEEDED'}</span></section>
    <div className="idle-metrics"><article><span>Connections while away</span><b>{idleFlows.length}</b></article><article><span>Apps used</span><b>{apps.size}</b></article><article><span>Destinations</span><b>{destinations.size}</b></article><article><span>Uploaded</span><b>{hasUploadMeasurements ? formatBytes(uploadedBytes) : '—'}</b></article></div>
    <section className="feature-section"><div className="feature-section-head"><div><span className="report-kicker">BY APP</span><h2>Apps connecting while away</h2></div><span className="feature-count">{idleFlows.length} OBSERVED</span></div>{apps.size ? <div className="feature-rows">{[...apps.values()].sort((a,b) => b.connections-a.connections).map((row) => <article className="idle-app-row" key={row.app}><span className="app-glyph">{row.app.slice(0,1).toUpperCase()}</span><div className="idle-app-name"><b>{row.app}</b><small>{row.destinations.size} destination{row.destinations.size===1?'':'s'}</small></div><div><b>{row.connections}</b><small>connections</small></div><div><b>{row.hasUploadMeasurements?formatBytes(row.uploadedBytes):'—'}</b><small>uploaded</small></div><div><b>{row.signals}</b><small>data signals</small></div><button className="btn secondary compact" onClick={() => selectFlow(row.last.id)}>Inspect <ArrowRight size={12}/></button></article>)}</div> : <FeatureEmpty icon={Clock3} title={confirmed ? 'No connections found while away' : 'No away-time data yet'} detail={confirmed ? 'No connections were reported while your device was marked away.' : 'This appears when the local helper reports away-time activity.'}/>}</section>
    <section className="feature-section destination-section"><div className="feature-section-head"><div><span className="report-kicker">COMPARE</span><h2>Using apps vs. away</h2></div></div><div className="activity-compare"><div><span>ACTIVE</span><b>{activeFlows.length}</b><small>{hasActiveUploadMeasurements?`${formatBytes(activeUploadedBytes)} uploaded`:'Upload volume unreported'}</small></div><i/><div><span>IDLE</span><b>{idleFlows.length}</b><small>{hasUploadMeasurements?`${formatBytes(uploadedBytes)} uploaded`:'Upload volume unreported'}</small></div><div className="compare-note">Personal-data signals while away: <strong>{sensitiveSignals}</strong></div></div></section>
    <section className="feature-section destination-section"><div className="feature-section-head"><div><span className="report-kicker">MOST OFTEN CONTACTED</span><h2>Places apps connect to</h2></div></div>{destinations.size ? <div className="feature-rows">{[...destinations.values()].sort((a,b)=>b.connections-a.connections).slice(0,8).map((row)=><div className="destination-row" key={row.host}><Globe2 size={16}/><b>{row.company || row.host}</b><code>{row.host}</code><span>{row.apps.size} app{row.apps.size===1?'':'s'}</span><strong>{row.connections}</strong></div>)}</div>:<p className="feature-muted">Repeat connections will appear here when found.</p>}</section>
    {idleFlows.length>0&&<section className="feature-section"><div className="feature-section-head"><div><span className="report-kicker">RECENT EVENTS</span><h2>Idle activity timeline</h2></div></div><div className="idle-timeline">{[...idleFlows].sort((a,b)=>new Date(b.ts)-new Date(a.ts)).slice(0,12).map((flow)=><button key={flow.id} onClick={()=>selectFlow(flow.id)}><time>{new Date(flow.ts).toLocaleTimeString()}</time><span><b>{flow.app}{Number.isInteger(flow.process?.pid)?` · PID ${flow.process.pid}`:''}</b><small>{flow.host}</small></span><span>{flow.traffic?.protocol || flow.protocol || 'Protocol unreported'}{Number.isFinite(flow.traffic?.durationMs)?` · ${flow.traffic.durationMs} ms`:''}</span><span>{Number.isFinite(flow.traffic?.uploadBytes)?`${formatBytes(flow.traffic.uploadBytes)} up`:'Bytes unreported'}</span><ArrowRight size={13}/></button>)}</div></section>}
    <div className="feature-footnote"><Shield size={13}/> Background communication alone does not establish tracking or surveillance. Findings need supporting evidence. <button className="inline-feature-link" onClick={openLegal}>Review legal context <ArrowRight size={12}/></button></div>
  </div>;
}

function CorrelationPage({ flows, selectFlow, openLegal }) {
  const [category, setCategory] = useState('all');
  const shared = deriveIdentityCorrelations(flows, category);
  const categories = availableCorrelationCategories(flows);
  const exportResults = () => {
    const payload = shared.map((item) => ({ identifierType: item.type, fingerprint: item.fingerprint, applications: [...item.apps], destinations: [...item.destinations], firstObserved: item.first, lastObserved: item.last, observations: item.flows.length, confidence: item.confidence ?? null, flowIds: item.flows.map((flow)=>flow.id) }));
    const url = URL.createObjectURL(new Blob([JSON.stringify({ exportedAt: new Date().toISOString(), note: 'Shared pseudonym observations do not prove that companies shared data with each other.', correlations: payload }, null, 2)], {type:'application/json'}));
    const link = document.createElement('a'); link.href=url; link.download='ghostprint-correlations.json'; link.click(); URL.revokeObjectURL(url);
  };
  return <div className="page-wrap feature-page correlation-page">
    <PageHeading kicker="SAME ID FOUND IN DIFFERENT APPS" title="Identity links" description="See when the same protected ID appears in more than one app." actions={shared.length>0 && <button className="btn secondary" onClick={exportResults}><Download size={14}/> Export links</button>}/>
    <div className="capability-note"><Fingerprint size={16}/><span><b>Needs data from the local helper</b><small>It compares hidden IDs. Your real ID is not shown here.</small></span></div>
    <div className="correlation-tools"><div className="filter-tabs"><button className={category==='all'?'selected':''} onClick={()=>setCategory('all')}>All types</button>{categories.map((type)=><button key={type} className={category===type?'selected':''} onClick={()=>setCategory(type)}>{piiNames[type]||type}</button>)}</div><span>{shared.length} SHARED IDENTIFIER{shared.length===1?'':'S'}</span></div>
    {shared.length ? <div className="correlation-list">{shared.map((item)=><article className="correlation-item" key={item.fingerprint}><div className="correlation-id"><span className="signal-type">{piiNames[item.type]||item.type}</span><code>{item.fingerprint.slice(0,12)}…</code><small>HMAC-SHA-256 · pseudonymised</small></div><div className="correlation-graph">{[...item.apps].map((app,index)=><React.Fragment key={app}>{index>0&&<span className="correlation-line"/>}<button onClick={()=>selectFlow(item.flows.find((flow)=>flow.app===app)?.id)}><span className="app-glyph">{app.slice(0,1).toUpperCase()}</span><b>{app}</b></button></React.Fragment>)}</div><div className="correlation-meta"><span>{item.flows.length} observations</span><span>{item.destinations.size} destinations</span><span>{item.confidence == null?'Match observed':`${Math.round(item.confidence*100)}% confidence`}</span><time>{new Date(item.first).toLocaleDateString()} — {new Date(item.last).toLocaleDateString()}</time></div><div className="correlation-evidence">FLOW EVIDENCE {item.flows.map((flow)=><button key={flow.id} onClick={()=>selectFlow(flow.id)}>{flow.id}</button>)}</div><div className="correlation-disclaimer">The same identifier appeared in these apps. This does not prove the companies shared data with each other.</div></article>)}</div> : <FeatureEmpty icon={Network} title="No matching IDs found" detail={flows.length ? 'No protected ID was seen in more than one app.' : 'Connect the local helper to look for the same protected ID across apps.'}/>}
    {shared.length>0&&<div className="correlation-legal-link"><span>Explore privacy and data protection sources that may provide context for these observations.</span><button className="btn secondary compact" onClick={openLegal}>Legal guide <ArrowRight size={12}/></button></div>}
    <div className="feature-footnote"><LockKeyhole size={13}/> Fingerprints should be keyed and scoped to this local audit. Raw identifiers are never needed in this view.</div>
  </div>;
}

function FeatureEmpty({ icon: Icon, title, detail }) { return <div className="feature-empty"><Icon size={22}/><b>{title}</b><p>{detail}</p></div>; }

function ReportPage({ flows, score, verdicts, agent, device, send, selectFlow, openActivity, openApps, openGuidance }) {
  const report = useMemo(() => {
    const companies = new Map();
    const apps = new Set();
    const dataTypes = new Map();
    let personalSignals = 0;
    let highAttention = 0;
    flows.forEach((flow) => {
      apps.add(flow.app || 'Unknown app');
      const company = flow.company || flow.host || 'Unknown company';
      const item = companies.get(company) || { name: company, flows: 0, apps: new Set(), types: new Set(), severity: 0, firstFlow: flow };
      item.flows += 1;
      item.apps.add(flow.app || 'Unknown app');
      item.severity = Math.max(item.severity, Number(flow.severity) || 0);
      if ((flow.pii || []).length) {
        highAttention += flow.severity >= 75 ? 1 : 0;
        flow.pii.forEach((signal) => {
          personalSignals += 1;
          const label = piiNames[signal.type] || signal.type;
          item.types.add(label);
          dataTypes.set(label, (dataTypes.get(label) || 0) + 1);
        });
      }
      companies.set(company, item);
    });
    return {
      apps: apps.size,
      companies: [...companies.values()].sort((a, b) => b.types.size - a.types.size || b.flows - a.flows),
      personalSignals,
      highAttention,
      dataTypes: [...dataTypes.entries()].sort((a, b) => b[1] - a[1]),
    };
  }, [flows]);
  const reviewLevel = score?.total >= 750 ? 'High exposure' : score?.total >= 450 ? 'Review signals' : score ? 'Low exposure' : 'No score yet';
  const reviewClass = score?.total >= 750 ? 'high' : score?.total >= 450 ? 'medium' : 'low';
  const topTypes = report.dataTypes.slice(0, 4);
  const findingCount = Object.values(verdicts).filter((item) => item.status === 'violation' || item.status === 'questionable').length;
  return <div className="page-wrap plain-report">
    <PageHeading kicker="AUDIT SUMMARY" title="Your privacy report" description="A clear view of what your apps connect to." actions={<><button className="btn secondary" onClick={openActivity}><ListFilter size={14}/> Detailed activity</button><button className={`btn ${agent.capturing ? 'stop-btn' : 'primary'}`} onClick={() => agent.capturing ? send(OUTBOUND.stop()) : send(OUTBOUND.start(device))}>{agent.capturing ? <><span className="record-dot"/> Pause audit</> : <><Radar size={14}/> {flows.length ? 'Continue audit' : 'Start local audit'}</>}</button></>}/>
    <section className={`report-verdict ${reviewClass}`}><div className="report-verdict-icon"><ShieldCheck size={22}/></div><div className="report-verdict-copy"><span>AT A GLANCE</span><h2>{flows.length ? reviewLevel : agent.connected ? 'Ready to audit' : 'Waiting for report'}</h2><p>{flows.length ? `${report.personalSignals} personal-data signals were found across ${report.apps} ${report.apps === 1 ? 'app' : 'apps'} and ${report.companies.length} ${report.companies.length === 1 ? 'company' : 'companies'}. ` : agent.connected ? 'Start the audit, then use your apps.' : 'Connect the local audit service to begin.'}</p></div><div className="report-verdict-score"><small>CONNECTIONS</small><b>{flows.length.toLocaleString()}</b></div></section>
    <div className="report-metrics"><article><span>Apps</span><b>{report.apps}</b><small>Observed</small></article><article><span>Companies</span><b>{report.companies.length}</b><small>Observed</small></article><article><span>Data signals</span><b>{report.personalSignals}</b><small>Reported</small></article><article><span>Items to review</span><b>{findingCount}</b><small>From analysis</small></article></div>
    <section className="report-section"><div className="report-section-head"><div><span className="report-kicker">WHERE YOUR DATA WENT</span><h2>Apps, companies, and data</h2><p>Select a company to see details.</p></div><button className="text-link" onClick={openActivity}>See every connection <ArrowRight size={14}/></button></div>{report.companies.length ? <div className="report-transfer-list">{report.companies.slice(0, 8).map((company) => <button className="report-transfer" key={company.name} onClick={() => selectFlow(company.firstFlow.id)}><div className="report-app-stack"><span className="report-avatar">{[...company.apps][0]?.slice(0,1).toUpperCase() || '?'}</span><span><b>{[...company.apps].slice(0,2).join(', ')}{company.apps.size > 2 ? ` +${company.apps.size - 2}` : ''}</b><small>{company.apps.size === 1 ? 'sent data to' : 'sent data to'} {company.name}</small></span></div><ArrowRight className="report-transfer-arrow" size={16}/><div className="report-types">{company.types.size ? [...company.types].slice(0,3).map((type) => <span key={type}>{type}</span>) : <span className="no-signals-chip">No personal data signal reported</span>}{company.types.size > 3 && <small>+{company.types.size - 3} more</small>}</div><div className={`report-attention ${company.severity >= 75 && company.types.size ? 'attention-high' : ''}`}>{company.severity >= 75 && company.types.size ? 'Review' : 'Observed'}<small>{company.flows} {company.flows === 1 ? 'connection' : 'connections'}</small></div></button>)}</div> : <div className="report-empty"><div className="report-empty-icon"><Network size={21}/></div><b>Waiting for audit data</b><p>{agent.connected ? 'Start audit, then use your apps.' : 'Waiting for local audit service.'}</p><button className="btn primary" onClick={() => send(OUTBOUND.start(device))}><Radar size={14}/> Start local audit</button></div>}</section>
    <div className="report-bottom-grid"><section className="report-section report-data-types"><div className="report-section-head"><div><span className="report-kicker">WHAT KIND OF DATA</span><h2>Data signals</h2></div></div>{topTypes.length ? <div className="report-type-list">{topTypes.map(([type, count]) => <div key={type}><span className="report-type-icon"><Fingerprint size={15}/></span><span><b>{type}</b><small>Observed</small></span><strong>{count}</strong></div>)}</div> : <p className="report-muted">No data signals reported.</p>}</section><section className="report-next"><span className="report-kicker">ANALYSIS & NEXT STEPS</span><h2>{findingCount ? `${findingCount} items may be worth reviewing` : 'Start with the companies and data that matter most to you.'}</h2><p>{findingCount ? 'The analysis module has returned findings to review with their evidence and source notes. These are decision-support prompts, not legal conclusions.' : 'Check the app’s permissions, compare the finding with its privacy notice, and ask the company for context if anything is unclear. A signal is a reason to review, not proof of wrongdoing.'}</p><div className="report-next-actions"><button className="btn primary" onClick={openGuidance}><BookOpenCheck size={14}/> View findings and options</button><button className="btn secondary" onClick={openApps}><Link2 size={14}/> Manage linked apps</button></div></section></div>
    <div className="report-footnote"><LockKeyhole size={13}/> Observed data only / not a legal finding.</div>
  </div>;
}

function RadarPage({ flows, allFlows, search, setSearch, agent, device, send, selectFlow, notify }) {
  const score = useGhostStore((s) => s.score);
  const filters = useGhostStore((s) => s.filters);
  const setFilter = useGhostStore((s) => s.setFilter);
  const [showGraph, setShowGraph] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [minSeverity, setMinSeverity] = useState(filters.minSeverity);
  const uniqueTrackers = new Set(allFlows.filter((f) => f.tracker).map((f) => f.tracker.name)).size;
  const leakCount = allFlows.filter((flow) => flow.pii?.length).length;
  const idleFlows = allFlows.filter((flow) => flow.idle?.state === 'idle' && flow.idle?.sessionId).length;
  return <div className="page-wrap">
    <PageHeading kicker="OBSERVED CONNECTIONS" title="Leak Radar" description="Observed connections and destinations." actions={<><button className="btn secondary" onClick={() => { setShowGraph(!showGraph); }}><Network size={15}/>{showGraph ? 'Hide data map' : 'Data map'}</button><button className={`btn ${agent.capturing ? 'stop-btn' : 'primary'}`} onClick={() => agent.capturing ? send(OUTBOUND.stop()) : send(OUTBOUND.start(device))}>{agent.capturing ? <><span className="record-dot"/> Pause audit</> : <><Radar size={15}/> Start audit</>}</button></>}/>
    {agent.capturing && <div className="capture-banner"><span className="capture-live"><i/> CAPTURING</span><span>Watching <b>{agent.device === 'phone' ? 'your phone' : 'this laptop'}</b> · local agent {agent.version || 'connected'}</span><span className="capture-time"><Clock3 size={12}/> Session active</span></div>}
    <section className="radar-summary"><div className="score-card"><div className="score-copy"><span className="overline">YOUR EXPOSURE SCORE <Info size={12}/></span><div className="score-number"><strong>{score ? Math.round(score.total) : '—'}</strong><span>/ 1000</span></div><div className="score-trend">{score ? 'Updates as new connections are analyzed' : 'Waiting for the agent to send a score'}</div><div className="score-legend"><i/> LOW <i/> ELEVATED <i/> HIGH <i/> CRITICAL</div></div><ScoreGauge value={score?.total || 0}/><div className="score-bars">{(score?.categories || [{ name: 'Trackers', value: 0 }, { name: 'PII leaked', value: 0 }, { name: 'Cross-border', value: 0 }, { name: 'Consent', value: 0 }]).map((item) => <div className="score-bar" key={item.name}><span>{item.name}</span><div><i style={{ width: `${Math.min(100, item.value)}%` }}/></div><b>{item.value}</b></div>)}</div></div>
      <div className="stat-stack"><Metric icon={Activity} label="Connections" value={allFlows.length} detail={agent.capturing ? 'LIVE THIS SESSION' : 'THIS SESSION'} tone="cyan"/><Metric icon={Fingerprint} label="Data signals" value={leakCount} detail="REDACTED VALUES" tone="violet"/><Metric icon={Blocks} label="Tracker types" value={uniqueTrackers} detail="UNIQUE DESTINATIONS" tone="amber"/><Metric icon={Clock3} label="Idle-marked flows" value={idleFlows} detail="AGENT-REPORTED" tone="red"/></div>
    </section>
    {showGraph && <ShadowMap flows={allFlows} onSelect={(flow) => selectFlow(flow.id)} onFilter={(app) => { setFilter('app', app); setShowGraph(false); }}/>}
    <section className="flow-panel"><div className="flow-toolbar"><div><div className="panel-title"><h2>Connection details</h2><span className="live-count">{allFlows.length.toLocaleString()} FLOWS</span></div><p>Select a connection to inspect evidence.</p></div><div className="toolbar-controls"><label className="flow-search"><Search size={14}/><input id="flow-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search apps, hosts…"/><kbd>⌘ K</kbd></label><div className="filter-anchor"><button className={`btn compact secondary ${filterOpen ? 'filter-on' : ''}`} onClick={() => setFilterOpen(!filterOpen)}><ListFilter size={14}/> Filters<ChevronDown size={13}/></button>{filterOpen && <div className="filter-pop"><div className="filter-pop-head"><b>Filter flows</b><button onClick={() => { setFilter('app', ''); setFilter('piiType', ''); setMinSeverity(0); setFilter('minSeverity', 0); }}><RefreshCw size={12}/> Reset</button></div><label>APP<input value={filters.app} onChange={(event) => setFilter('app', event.target.value)} placeholder="Any app" list="app-options"/></label><datalist id="app-options">{[...new Set(allFlows.map((flow) => flow.app))].map((app) => <option key={app} value={app}/>)}</datalist><label>PERSONAL DATA<select value={filters.piiType} onChange={(event) => setFilter('piiType', event.target.value)}><option value="">Any type</option>{Object.entries(piiNames).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label><label>MINIMUM SEVERITY <b>{minSeverity}</b><input type="range" min="0" max="100" value={minSeverity} onChange={(event) => { setMinSeverity(Number(event.target.value)); setFilter('minSeverity', Number(event.target.value)); }}/></label></div>}</div></div></div>
      <div className="flow-columns"><span>APPLICATION / DESTINATION</span><span>DATA OBSERVED</span><span>METHOD</span><span>DESTINATION</span><span>SEVERITY</span><span/></div>
      <FlowList flows={flows} allCount={allFlows.length} onSelect={onSelectFromList(selectFlow)} agent={agent} search={search}/>
      <div className="flow-footer"><span>Showing <b>{flows.length}</b> of <b>{allFlows.length}</b> observed flows <i/> newest first <i/> max 2,000 kept in memory</span><button onClick={() => { if (agent.connected) notify('Connection details is already connected.'); else notify('Reconnecting to local agent…'); }}><RefreshCw size={12}/> Auto-reconnect enabled</button></div>
    </section>
    <div className="radar-footnotes"><div><span className="note-icon"><ShieldCheck size={14}/></span><span><b>Evidence first.</b> Connection details come from the local helper; this dashboard does not invent detections.</span></div><div><span className="note-icon amber"><AlertTriangle size={14}/></span><span><b>Metadata-only is still evidence.</b> Pinned apps may hide payloads while host, timing, and size remain visible.</span></div></div>
  </div>;
}

function onSelectFromList(selectFlow) { return (flow) => selectFlow(flow.id); }

function ScoreGauge({ value }) {
  const safe = Math.max(0, Math.min(1000, value));
  const radius = 51;
  const circumference = 2 * Math.PI * radius;
  const color = safe >= 750 ? 'var(--red)' : safe >= 450 ? 'var(--amber)' : 'var(--green)';
  return <div className="gauge"><svg viewBox="0 0 128 128" role="img" aria-label={`Exposure score ${Math.round(safe)} of 1000`}><circle className="gauge-track" cx="64" cy="64" r={radius}/><circle className="gauge-value" cx="64" cy="64" r={radius} style={{ strokeDasharray: circumference, strokeDashoffset: circumference * (1 - safe / 1000), stroke: color }}/><text x="64" y="61" textAnchor="middle" className="gauge-num">{Math.round(safe)}</text><text x="64" y="79" textAnchor="middle" className="gauge-caption">EXPOSURE</text></svg></div>;
}

function Metric({ icon: Icon, label, value, detail, tone }) { return <div className="metric-tile"><div className={`metric-icon ${tone}`}><Icon size={15}/></div><div className="metric-text"><span>{label}</span><b>{Number(value).toLocaleString()}</b><small>{detail}</small></div></div>; }

function FlowList({ flows, allCount, onSelect, agent, search }) {
  const parentRef = useRef(null);
  const rowVirtualizer = useVirtualizer({ count: flows.length, getScrollElement: () => parentRef.current, estimateSize: () => 76, overscan: 9 });
  if (!flows.length) return <div className="flow-empty">{allCount === 0 ? agent.connected ? <><div className="empty-orbit"><Radar size={23}/></div><b>Ready when you are</b><p>Start audit, then open an app or website on your device to see its connections here.</p></> : <><div className="empty-orbit offline"><Wifi size={22}/></div><b>{search ? 'No matching flows' : 'No local agent connected'}</b><p>{search ? 'Try a different search.' : 'Start the agent on this device. The dashboard will reconnect automatically.'}</p></> : <><div className="empty-orbit"><Filter size={21}/></div><b>No flows match these filters</b><p>Clear one or more filters to show more connections.</p></>}</div>;
  return <div className="flow-list" ref={parentRef} style={{ height: 'min(56vh, 640px)', minHeight: 330 }}><div style={{ height: rowVirtualizer.getTotalSize(), width: '100%', position: 'relative' }}>{rowVirtualizer.getVirtualItems().map((virtualRow) => { const flow = flows[virtualRow.index]; return <div className="virtual-row-wrap" key={flow.id} data-index={virtualRow.index} ref={rowVirtualizer.measureElement} style={{ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${virtualRow.start}px)` }}><FlowRow flow={flow} onClick={() => onSelect(flow)}/></div>; })}</div></div>;
}

function FlowRow({ flow, onClick }) {
  const pii = flow.pii || [];
  const severityClass = flow.severity >= 75 ? 'high' : flow.severity >= 40 ? 'medium' : 'low';
  const location = countryNames[flow.country] || flow.country || 'Unknown';
  return <button className="flow-row" onClick={onClick}><div className="flow-app"><div className="app-glyph">{flow.app?.slice(0, 1).toUpperCase() || '?'}</div><span><b>{flow.app}</b><code>{flow.host}{flow.path || ''}</code></span><span className={`capture-mode ${flow.decrypted ? 'decrypted' : 'metadata'}`}>{flow.decrypted ? <><Eye size={11}/> DECRYPTED</> : <><EyeOff size={11}/> METADATA</>}</span></div><div className="pii-cell">{pii.length ? pii.slice(0, 3).map((hit, index) => <span className={`pii-chip ${hit.type}`} key={`${hit.type}-${index}`}>{piiShort[hit.type] || hit.type.toUpperCase()}</span>) : <span className="no-pii">NO PERSONAL-DATA SIGNAL REPORTED</span>}</div><div className="method-cell"><span>{flow.method || '—'}</span><code>{formatBytes(flow.bytes)}</code></div><div className="destination-cell"><span className="flag">{flagEmoji(flow.country)}</span><span><b>{flow.company || 'Unknown destination'}</b><small>{location}{flow.tracker?.name ? ` · ${flow.tracker.name}` : ''}</small></span></div><div className={`severity-cell ${severityClass}`}><span className="severity-value">{Math.round(flow.severity)}</span><div><span className="severity-track"><i style={{ width: `${Math.max(3, Math.min(100, flow.severity))}%` }}/></span><small>{severityClass.toUpperCase()}</small></div></div><ArrowRight size={14} className="row-arrow"/></button>;
}

function ShadowMap({ flows, onSelect, onFilter }) {
  const graph = useMemo(() => buildGraph(flows), [flows]);
  if (!flows.length) return <div className="shadow-panel"><div><b>Shadow Map</b><span>Graph builds as the agent observes flows.</span></div><div className="graph-empty"><Network size={19}/> Waiting for evidence</div></div>;
  return <section className="shadow-panel"><div className="shadow-head"><div><div className="panel-title"><h2>How data moves</h2><span className="mini-tag">APP → COMPANY → DATA FOUND</span></div><p>Follow observed connections from an app to a receiving company and any reported data signal.</p></div><div className="graph-legend"><span><i className="app-node-dot"/>APP</span><span><i className="company-node-dot"/>COMPANY</span><span><i className="data-node-dot"/>DATA</span></div></div><div className="graph-wrap"><svg viewBox="0 0 1000 410" className="shadow-svg" role="img" aria-label="Observed applications, companies, and data types">{graph.edges.map((edge) => <line key={edge.id} x1={edge.from.x} y1={edge.from.y} x2={edge.to.x} y2={edge.to.y} className={edge.identity ? 'identity-edge' : 'graph-edge'}/>)}{graph.nodes.map((node) => <g key={node.id} className={`graph-node ${node.kind}`} transform={`translate(${node.x},${node.y})`} onClick={() => node.kind === 'app' ? onFilter(node.label) : node.flow && onSelect(node.flow)} role="button" tabIndex="0"><circle r={node.kind === 'company' ? 19 : node.kind === 'app' ? 15 : 13}/><text textAnchor="middle" dy="4">{node.glyph}</text><text className="node-label" textAnchor="middle" y="32">{short(node.label, 18)}</text></g>)}</svg></div></section>;
}

function buildGraph(flows) {
  const chosen = flows.slice(0, 120);
  const apps = [...new Set(chosen.map((f) => f.app))].slice(0, 7);
  const companies = [...new Set(chosen.map((f) => f.company).filter(Boolean))].slice(0, 8);
  const types = [...new Set(chosen.flatMap((f) => (f.pii || []).map((p) => p.type)))].slice(0, 6);
  const nodes = [];
  apps.forEach((label, i) => nodes.push({ id: `a${i}`, label, kind: 'app', glyph: label[0]?.toUpperCase() || 'A', x: 145, y: 54 + i * 49, flow: chosen.find((f) => f.app === label) }));
  companies.forEach((label, i) => nodes.push({ id: `c${i}`, label, kind: 'company', glyph: label.slice(0, 2).toUpperCase(), x: 500, y: 42 + i * 45, flow: chosen.find((f) => f.company === label) }));
  types.forEach((label, i) => nodes.push({ id: `p${i}`, label: piiNames[label] || label, kind: 'data', glyph: (piiShort[label] || label).slice(0, 3), x: 855, y: 70 + i * 52, flow: chosen.find((f) => f.pii?.some((p) => p.type === label)) }));
  const byApp = new Map(nodes.filter((n) => n.kind === 'app').map((n) => [n.label, n]));
  const byCompany = new Map(nodes.filter((n) => n.kind === 'company').map((n) => [n.label, n]));
  const byType = new Map(nodes.filter((n) => n.kind === 'data').map((n) => [n.label, n]));
  const edges = [];
  chosen.slice(0, 70).forEach((flow, i) => { const from = byApp.get(flow.app); const to = byCompany.get(flow.company); if (from && to) edges.push({ id: `e${i}`, from, to, identity: false }); (flow.pii || []).forEach((pii) => { const dataNode = byType.get(pii.type); if (to && dataNode) edges.push({ id: `p${i}-${pii.type}`, from: to, to: dataNode, identity: false }); }); });
  return { nodes, edges };
}

function ShadowMapPage({ flows, selectFlow, openRadar }) {
  return <div className="page-wrap"><PageHeading kicker="VISUAL DATA SUMMARY" title="Shadow Map" description="Apps / companies / data signals." actions={<button className="btn secondary" onClick={openRadar}><Radar size={14}/> Open Leak Radar</button>}/><ShadowMap flows={flows} onSelect={(flow) => selectFlow(flow.id)} onFilter={openRadar}/><div className="map-explainer"><Info size={13}/> Observed paths only / missing signals are unknown.</div></div>;
}

function InsightsPage({ flows, verdicts, openRadar }) {
  const companies = new Map();
  const apps = new Map();
  flows.forEach((flow) => { const company = flow.company || flow.host || 'Unknown destination'; companies.set(company, (companies.get(company) || 0) + 1); apps.set(flow.app || 'Unknown app', (apps.get(flow.app || 'Unknown app') || 0) + 1); });
  const signals = flows.reduce((sum, flow) => sum + (flow.pii || []).length, 0);
  const top = [...companies].sort((a,b) => b[1]-a[1]).slice(0,5);
  return <div className="page-wrap"><PageHeading kicker="PLAIN-LANGUAGE SUMMARY" title="Insights" description="Patterns in this audit." actions={<button className="btn secondary" onClick={openRadar}><Radar size={14}/> View connections</button>}/><div className="insight-metrics">{[['Connections observed',flows.length],['Companies contacted',companies.size],['Data signals reported',signals],['Findings returned',Object.keys(verdicts).length]].map(([label,value])=><article key={label}><span>{label}</span><b>{value}</b></article>)}</div><div className="insight-grid"><section className="section-panel"><PanelHeading title="Most contacted destinations" sub="Count of connections reported by the local audit."/>{top.length ? <div className="insight-bars">{top.map(([name,count])=><div key={name}><span>{name}</span><i><b style={{width:`${Math.max(4,count/Math.max(...top.map((row)=>row[1]))*100)}%`}}/></i><strong>{count}</strong></div>)}</div>:<div className="legal-empty"><b>No insights yet</b><p>Start an audit to see activity.</p></div>}</section><section className="section-panel"><PanelHeading title="Apps in this report" sub="Observed outgoing connections by app."/>{[...apps].sort((a,b)=>b[1]-a[1]).map(([app,count])=><div className="insight-app-row" key={app}><span className="app-glyph">{app[0]?.toUpperCase()}</span><b>{app}</b><span>{count} connections</span></div>)}</section></div><div className="map-explainer"><Info size={13}/> Session data only / not a legal conclusion.</div></div>;
}

function ActionsPage({ flows, send, openLegal, notify }) {
  const [format, setFormat] = useState('hosts');
  const blocklist = useGhostStore((s) => s.blocklist);
  const hosts = [...new Set(flows.filter((flow) => flow.tracker || flow.severity >= 60).map((flow) => flow.host))].slice(0,8);
  return <div className="page-wrap"><PageHeading kicker="REVIEW BEFORE CHANGING SETTINGS" title="Possible next steps" description="Review destinations. Prepare rules." actions={<button className="btn secondary" onClick={openLegal}><BookOpenCheck size={14}/> Legal guidance</button>}/><section className="section-panel"><PanelHeading title="Destinations to review" sub="Sorted by tracker label and severity." count={`${hosts.length} destinations`}/>{hosts.length ? <div className="action-list">{hosts.map((host,index)=>{const flow=flows.find((item)=>item.host===host);return <div className="action-row" key={host}><span className="action-rank">{String(index+1).padStart(2,'0')}</span><span className="action-lock"><Ban size={15}/></span><div className="action-info"><b>{host}</b><code>{flow?.app || 'Unknown app'} / {flow?.company || 'Company not attributed'} / severity {Math.round(flow?.severity||0)}/100</code></div><span className="impact-pill">Review</span></div>})}</div>:<div className="legal-empty"><b>No priority destinations</b><p>Destinations appear here when the agent reports observed connections.</p></div>}<div className="blocklist-control"><div><b>Prepare a blocklist</b><small>Review the generated rules before applying them on your device.</small></div><select aria-label="Blocklist format" value={format} onChange={(event) => setFormat(event.target.value)}><option value="hosts">hosts file</option><option value="pihole">Pi-hole</option><option value="nextdns">NextDNS</option><option value="pf">pf firewall</option></select><button className="btn secondary compact" onClick={()=>{send(OUTBOUND.blocklist(format));notify('Blocklist request sent to the local audit service.')}}><Blocks size={13}/> Generate rules</button></div>{blocklist?.content&&<pre className="blocklist-preview">{blocklist.content}</pre>}</section><div className="map-explainer"><AlertTriangle size={13}/> Review rules before applying; blocking may affect app features.</div></div>;
}

function EvidencePage({ flows, send }) {
  const evidence = useGhostStore((s) => s.evidence);
  const signals = flows.reduce((sum, flow) => sum + (flow.pii || []).length, 0);
  const [verification, setVerification] = useState(null);
  const [verifying, setVerifying] = useState(false);
  const records = evidence?.chain?.records || evidence?.records || [];
  const verify = async () => { setVerifying(true); try { setVerification(await verifyEvidenceChain(evidence?.chain || { records })); } catch (error) { setVerification({ status: 'incomplete', message: error?.message || 'Verification could not complete.' }); } finally { setVerifying(false); } };
  const statusLabels = { verified: 'Chain verified', modified: 'Record modified', broken: 'Chain broken', missing: 'Record missing', incomplete: 'Verification incomplete' };
  return <div className="page-wrap feature-page"><PageHeading kicker="LOCAL AUDIT RECORD" title="Evidence Vault" description="Records, integrity checks, and export." actions={<button className="btn primary" onClick={() => send(OUTBOUND.exportEvidence())}><Download size={14}/> Request export</button>}/><div className="insight-grid"><section className="section-panel"><PanelHeading title="Current report scope" sub="Observations received in this session."/><div className="evidence-scope"><div><span>Flows received</span><b>{flows.length}</b></div><div><span>Data signals</span><b>{signals}</b></div></div></section><section className="section-panel"><PanelHeading title="Export details" sub="Export metadata reported by the local service."/><div className="evidence-seal"><div><FileCheck2 size={21}/></div><span><b>{evidence?.sha256?'Export received':'No export received yet'}</b><small>{evidence?.sha256?'Hash and path received from the local service.':'Request an export while the local service is connected.'}</small></span></div>{evidence?.path&&<div className="hash-box"><span>FILE LOCATION</span><code>{evidence.path}</code></div>}{evidence?.sha256&&<div className="hash-box"><span>EXPORT SHA-256</span><code>{evidence.sha256}</code></div>}</section></div>
    <section className="feature-section integrity-section"><div className="feature-section-head"><div><span className="report-kicker">CHECK THE RECORD</span><h2>Check your records</h2></div>{records.length>0&&<button className="btn secondary" onClick={verify} disabled={verifying}><Hash size={14}/>{verifying?'Verifying…':'Verify chain'}</button>}</div>{records.length>0 ? <><div className={`integrity-result ${verification?.status || 'pending'}`}><span className="integrity-mark">{verification?.status==='verified'?<CheckCircle2 size={19}/>:verification?<AlertTriangle size={19}/>:<Hash size={19}/>}</span><div><b>{verification ? statusLabels[verification.status] : 'Chain not checked yet'}</b><small>{verification?.message || `${records.length} records received. Verify hashes and previous-record links in this browser.`}{verification?.recordId ? ` · Record ${verification.recordId}`:''}</small></div></div><div className="integrity-record-list">{records.slice(0,12).map((record,index)=><div key={record.recordId || index}><span>{String(index+1).padStart(2,'0')}</span><b>{record.recordId || 'Unidentified record'}</b><code>{record.hash || 'Missing hash'}</code><small>{record.previousHash ? 'LINKED' : index===0?'CHAIN START':'MISSING LINK'}</small></div>)}</div></> : <FeatureEmpty icon={Hash} title="Full chain not supplied" detail={evidence?.sha256 ? 'The current agent sent an export hash, not individual records. Independent chain verification needs the record list, each previous hash, and a chain checkpoint.' : 'The capture agent must export canonical records and previous-hash links before this page can verify the chain.'}/>}<div className="feature-footnote"><Shield size={13}/> A valid chain shows that included records link consistently. It cannot prove the original capture was genuine, complete, or legally admissible.</div></section>
    <div className="map-explainer"><LockKeyhole size={13}/> The local agent remains responsible for append-only storage and protected signing keys.</div></div>;
}

function FlowDrawer({ flow, verdict, close, send }) {
  const [copied, setCopied] = useState('');
  const [rawMessage, setRawMessage] = useState(false);
  const pii = flow.pii || [];
  const copy = async (text, label) => { try { await navigator.clipboard.writeText(text); setCopied(label); window.setTimeout(() => setCopied(''), 1500); } catch { setCopied('Clipboard unavailable'); } };
  return <div className="drawer-backdrop" onMouseDown={(event) => event.target === event.currentTarget && close()}><aside className="flow-drawer"><div className="drawer-head"><div><div className="eyebrow">FLOW EVIDENCE <span className="flow-id">{flow.id}</span></div><h2>{flow.app} <span>→</span> {flow.company || flow.host}</h2></div><button className="icon-btn" onClick={close}><X size={16}/></button></div><div className={`drawer-mode ${flow.decrypted ? 'decrypted' : 'metadata'}`}>{flow.decrypted ? <Eye size={14}/> : <EyeOff size={14}/>}<span><b>{flow.decrypted ? 'Request contents read' : 'Connection details only'}</b><small>{flow.decrypted ? 'The agent inspected this request payload.' : 'Payload unavailable. Connection details remain visible.'}</small></span></div><div className="drawer-section"><div className="drawer-section-title">DESTINATION <button onClick={() => copy(flow.host, 'Copied host')}><Copy size={12}/>{copied === 'Copied host' ? 'Copied' : 'Copy host'}</button></div><div className="evidence-grid"><Evidence label="HOST" value={flow.host} mono/><Evidence label="COMPANY" value={flow.company || 'Not attributed'}/><Evidence label="COUNTRY" value={`${flagEmoji(flow.country)} ${countryNames[flow.country] || flow.country}`} /><Evidence label="IP ADDRESS" value={flow.ip || 'Not provided'} mono/><Evidence label="REQUEST" value={`${flow.method || '—'} ${flow.path || '/'}`} mono/><Evidence label="DATA SENT" value={formatBytes(flow.bytes)}/><Evidence label="OBSERVED AT" value={new Date(flow.ts).toLocaleString()} mono/><Evidence label="TRACKER" value={flow.tracker ? `${flow.tracker.name} · ${flow.tracker.category}` : 'No tracker attribution'} /></div></div><div className="drawer-section"><div className="drawer-section-title">DATA TYPES FOUND <span>{pii.length} DETECTED</span></div>{pii.length ? <div className="pii-evidence">{pii.map((hit, index) => <div className="pii-evidence-row" key={`${hit.type}-${index}`}><span className={`pii-chip ${hit.type}`}>{piiShort[hit.type] || hit.type}</span><code>{hit.redacted}</code><span className="confidence">{Math.round(hit.confidence * 100)}% conf.</span><button title="Raw value status" onClick={() => setRawMessage(!rawMessage)}><Eye size={13}/> Reveal</button></div>)}{rawMessage && <div className="redaction-note"><LockKeyhole size={13}/><span>Values arrive redacted and cannot be revealed here.</span></div>}</div> : <div className="no-signals"><CheckCircle2 size={15}/> No data signal reported.</div>}</div><div className="drawer-section"><div className="drawer-section-title">SEVERITY <span className={`severity-number ${severityWord(flow.severity)}`}>{Math.round(flow.severity)} / 100 · {severityWord(flow.severity).toUpperCase()}</span></div><div className="severity-large"><div><i className={severityWord(flow.severity)} style={{ width: `${Math.max(3, flow.severity)}%` }}/></div><span>Analysis score</span></div></div><div className="drawer-section verdict-drawer"><div className="drawer-section-title">REVIEW NOTE</div>{verdict ? <VerdictCard verdict={verdict} compact/> : <div className="verdict-pending"><span><Clock3 size={14}/></span><p>No verdict has arrived for this flow yet.</p><button onClick={() => send({ type: 'analyze', flowId: flow.id })}>Ask agent to review <ArrowRight size={13}/></button></div>}</div><div className="drawer-bottom"><span>Evidence from local agent stream</span><button className="btn secondary compact" onClick={() => copy(JSON.stringify({ ...flow, pii }), 'Copied flow JSON')}><Copy size={13}/>{copied === 'Copied flow JSON' ? 'Copied' : 'Copy flow record'}</button></div></aside></div>;
}

function Evidence({ label, value, mono = false }) { return <div className="evidence-item"><span>{label}</span><b className={mono ? 'mono' : ''}>{value || '—'}</b></div>; }

function LegalPage({ allFlows, send, notify }) {
  const verdicts = useGhostStore((s) => s.verdicts);
  const score = useGhostStore((s) => s.score);
  const blocklist = useGhostStore((s) => s.blocklist);
  const evidence = useGhostStore((s) => s.evidence);
  const baseline = useGhostStore((s) => s.baseline);
  const setBaseline = useGhostStore((s) => s.setBaseline);
  const [format, setFormat] = useState('hosts');
  const [complaint, setComplaint] = useState('To: Privacy contact / Data Protection Officer\nSubject: Request for information about observed data processing\n\nI observed network activity associated with [application] on [date]. Please explain what personal data is processed, for what purposes, which entities receive it, and where I can find the applicable privacy notice.\n\nEvidence references: [add flow IDs and timestamps]\n\nPlease identify the applicable legal basis and response process for my jurisdiction. This request is based on a technical observation and is not an allegation of unlawful conduct.');
  const [copied, setCopied] = useState(false);
  const grouped = useMemo(() => {
    const rows = Object.values(verdicts);
    const map = new Map();
    rows.forEach((verdict) => { const flow = allFlows.find((f) => f.id === verdict.flowId); const key = flow?.app || 'Unknown app'; if (!map.has(key)) map.set(key, []); map.get(key).push({ verdict, flow }); });
    return [...map.entries()];
  }, [verdicts, allFlows]);
  const rankedFixes = useMemo(() => {
    const hosts = [...new Set(allFlows.filter((f) => f.severity >= 60).map((f) => f.host))];
    return hosts.slice(0, 5).map((host, index) => ({ host, impact: Math.max(8, 32 - index * 5), app: allFlows.find((f) => f.host === host)?.app || 'Unknown app' }));
  }, [allFlows]);
  const leakedCount = allFlows.filter((flow) => flow.pii?.length).length;
  const copyBlocklist = async () => { const content = blocklist?.content || rankedFixes.map((fix) => format === 'hosts' ? `0.0.0.0 ${fix.host}` : fix.host).join('\n'); try { await navigator.clipboard.writeText(content || '# No tracker domains in the current session'); setCopied(true); window.setTimeout(() => setCopied(false), 1800); } catch { notify('Clipboard access is unavailable.'); } };
  const exportDraft = () => { const blob = new Blob([complaint], { type: 'text/plain' }); const link = document.createElement('a'); link.href = URL.createObjectURL(blob); link.download = 'ghostprint-complaint-draft.txt'; link.click(); URL.revokeObjectURL(link.href); notify('Complaint draft downloaded'); };
  return <div className="page-wrap"><PageHeading kicker="LEGAL CONTEXT · INDIA" title="Legal guide" description="What the law says and where to read it." actions={<span className="local-analysis-label"><LockKeyhole size={12}/> SOURCE-LINKED</span>}/>
    <LegalReferenceDirectory/>
    <section className="legal-summary"><div className="legal-intro"><div className="legal-icon"><BookOpenCheck size={19}/></div><div><b>Review notes</b><p>Check each note against its sources. A connection alone does not prove a law was broken.</p></div></div><div className="verdict-counts"><div><b>{Object.values(verdicts).filter((v) => v.status === 'violation').length}</b><span>Check this</span></div><div><b>{Object.values(verdicts).filter((v) => v.status === 'questionable').length}</b><span>Check this</span></div><div><b>{Object.values(verdicts).filter((v) => v.status === 'compliant').length}</b><span>No issue flagged</span></div></div></section>
    <section className="legal-playbook"><div className="playbook-intro"><span className="eyebrow"><span className="eyebrow-line"/> QUICK REVIEW</span><h2>Check before acting.</h2><p>A computer check is not a legal decision.</p></div><div className="playbook-grid"><article><span className="playbook-step">01 · PRESERVE</span><h3>Save the report</h3><p>Keep dates, connection details, links, and the report.</p></article><article><span className="playbook-step">02 · VERIFY</span><h3>Check what happened</h3><p>Confirm which app and account were involved, read the provider’s notice and permissions, and check that linked legal sources support the finding.</p></article><article><span className="playbook-step">03 · CONSIDER</span><h3>Choose a next step</h3><p>Review permissions or ask the provider. Seek qualified advice before formal action.</p></article><article className="avoid-card"><span className="playbook-step">PAUSE BEFORE</span><h3>Avoid rushed action</h3><p>Do not publish accusations, delete evidence, or access systems without permission.</p></article></div><div className="law-sources"><span>PRIMARY SOURCES · CHECK APPLICABILITY AND COMMENCEMENT</span><a href="https://www.indiacode.nic.in/indiacode/handle/123456789/22037?view_type=browse" target="_blank" rel="noreferrer">Digital Personal Data Protection Act, 2023 <ExternalLink size={12}/></a><a href="https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa?pageTitle=Digital-Personal-Data-Protection-Rules-2025686cadad39.pdf" target="_blank" rel="noreferrer">Digital Personal Data Protection Rules, 2025 <ExternalLink size={12}/></a></div></section>
    <div className="legal-grid"><div className="legal-main"><section className="section-panel"><PanelHeading title="Findings & source notes" sub="Agent findings and source references." count={`${Object.keys(verdicts).length} findings`}/>{grouped.length ? <div className="verdict-groups">{grouped.map(([app, entries]) => <div className="verdict-group" key={app}><div className="app-group-head"><span className="app-glyph">{app[0]}</span><b>{app}</b><small>{entries.length} {entries.length === 1 ? 'flow' : 'flows'} reviewed</small></div>{entries.map(({ verdict, flow }) => <VerdictCard key={verdict.flowId} verdict={verdict} flow={flow}/>)}</div>)}</div> : <div className="legal-empty"><div className="empty-orbit"><BookOpenCheck size={20}/></div><b>No analysis yet</b><p>Start audit, select a flow, and request analysis. Agent findings and sources will appear here.</p></div>}</section>
      <section className="section-panel action-report"><PanelHeading title="Possible next steps" sub="Review these options against the evidence and your needs." count={`${rankedFixes.length} suggested`}/><div className="action-list">{rankedFixes.length ? rankedFixes.map((fix, index) => <div className="action-row" key={fix.host}><span className="action-rank">0{index + 1}</span><span className="action-lock"><Ban size={15}/></span><div className="action-info"><b>Review options for {fix.host}</b><code>{fix.app} · tracker destination</code></div><span className="impact-pill">−{fix.impact} score</span></div>) : <div className="action-empty"><CheckCircle2 size={16}/> No priority tracker destinations were observed in this session.</div>}</div><div className="blocklist-control"><div><b>Build a blocklist</b><small>Generated by the agent from observed tracker domains.</small></div><select value={format} onChange={(event) => setFormat(event.target.value)}><option value="hosts">hosts file</option><option value="pihole">Pi-hole</option><option value="nextdns">NextDNS</option><option value="pf">pf firewall</option></select><button className="btn secondary compact" onClick={() => { send(OUTBOUND.blocklist(format)); if (baseline === null) setBaseline(leakedCount); }}><Blocks size={13}/> Generate</button><button className="btn secondary compact" onClick={copyBlocklist}><Copy size={13}/>{copied ? 'Copied' : 'Copy'}</button></div>{blocklist && <pre className="blocklist-preview">{blocklist.content}</pre>}<div className="recheck-row"><span><RefreshCw size={13}/> {baseline === null ? 'Capture a baseline before you re-run.' : `Baseline ${baseline} PII flows · current ${leakedCount} · ${Math.max(0, baseline - leakedCount)} fewer`}</span><button className="btn primary compact" onClick={() => { if (baseline === null) setBaseline(leakedCount); send({ type: 'start', device: 'laptop' }); notify('Capture restarted. Apply the copied rules on the audited device before comparing results.'); }}><Activity size={13}/> Re-run capture</button></div></section>
    </div><aside className="legal-side"><section className="section-panel evidence-pack"><PanelHeading title="Saved report" sub="Saved activity record"/><div className="evidence-seal"><div><FileCheck2 size={21}/></div><span><b>{evidence?.sha256 ? 'Evidence sealed' : 'Export evidence'}</b><small>{evidence?.sha256 ? 'Hash received from local agent.' : 'No export yet.'}</small></span></div>{evidence?.path && <div className="hash-box"><span>AGENT FILE PATH</span><code>{evidence.path}</code></div>}{evidence?.sha256 && <div className="hash-box"><span>SHA-256</span><code>{evidence.sha256}</code></div>}<div className="pack-meta"><span>Flows included</span><b>{allFlows.length}</b><span>Data signals</span><b>{leakedCount}</b><span>Current score</span><b>{score?.total ? Math.round(score.total) : '—'}</b></div><button className="btn primary full-btn" onClick={() => send(OUTBOUND.exportEvidence())}><Download size={14}/> Download report</button><p className="pack-note"><LockKeyhole size={12}/> Path and hash come from the local agent.</p></section>
      <section className="section-panel complaint-panel"><PanelHeading title="Message draft" sub="Editable template · review details before sending"/><div className="draft-toolbar"><span><FileText size={12}/> INFORMATION REQUEST</span><button onClick={exportDraft}><ArrowDownToLine size={12}/> Download</button></div><textarea value={complaint} onChange={(event) => setComplaint(event.target.value)} aria-label="Editable information request draft"/><div className="draft-footer"><span>Check facts, dates, recipient, and local requirements.</span><button className="btn secondary compact" onClick={exportDraft}><Download size={12}/> Export draft</button></div></section>
    </aside></div>
    <div className="legal-disclaimer"><Info size={13}/><span><b>Information only. This is not legal advice.</b> Verify sources; seek qualified advice before formal action.</span></div>
  </div>;
}

function LegalReferenceDirectory() {
  const [query, setQuery] = useState('');
  const [jurisdiction, setJurisdiction] = useState('All jurisdictions');
  const [kind, setKind] = useState('All sources');
  const [topic, setTopic] = useState('All topics');
  const jurisdictions = ['All jurisdictions', ...new Set(LEGAL_REFERENCES.map((reference) => reference.jurisdiction))];
  const matches = LEGAL_REFERENCES.filter((reference) => {
    const searchable = `${reference.title} ${reference.authority} ${reference.citation} ${reference.principle} ${reference.relevance} ${reference.topic}`.toLowerCase();
    return (!query || searchable.includes(query.toLowerCase()))
      && (jurisdiction === 'All jurisdictions' || reference.jurisdiction === jurisdiction)
      && (kind === 'All sources' || reference.kind === kind)
      && (topic === 'All topics' || reference.topic === topic);
  });
  return <section className="legal-library" aria-labelledby="legal-library-title">
    <div className="legal-library-head"><div><span className="report-kicker">CURATED PRIMARY MATERIAL</span><h2 id="legal-library-title">Source library</h2></div><span>{matches.length} REFERENCES</span></div>
    <div className="legal-library-tools"><label className="legal-search"><Search size={15}/><input value={query} onChange={(event)=>setQuery(event.target.value)} placeholder="Search titles, topics, sections" aria-label="Search legal references"/></label><select aria-label="Filter by jurisdiction" value={jurisdiction} onChange={(event)=>setJurisdiction(event.target.value)}>{jurisdictions.map((value)=><option key={value}>{value}</option>)}</select><select aria-label="Filter by source type" value={kind} onChange={(event)=>setKind(event.target.value)}>{LEGAL_KINDS.map((value)=><option key={value}>{value}</option>)}</select><select aria-label="Filter by topic" value={topic} onChange={(event)=>setTopic(event.target.value)}>{LEGAL_TOPICS.map((value)=><option key={value}>{value}</option>)}</select></div>
    <div className="legal-reference-list">{matches.map((reference)=><details className="legal-reference" key={reference.id}><summary><span className="reference-kind">{reference.kind}</span><span className="reference-title"><b>{reference.title}</b><small>{reference.authority} · {new Date(`${reference.date}T00:00:00`).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'})} · {reference.jurisdiction}</small></span><span className="reference-weight">{reference.weight}</span><ChevronDown size={15}/></summary><div className="reference-details"><div className="reference-citation"><span>SOURCE DETAILS</span><b>{reference.caseNo}</b><small>{reference.citation} · {reference.pinpoint}</small></div><div className="reference-explanation"><span>WHAT IT MEANS</span><p>{reference.principle}</p></div><div className="reference-explanation"><span>WHY IT COULD MATTER</span><p>{reference.relevance}</p></div><div className="reference-bottom"><a href={reference.url} target="_blank" rel="noreferrer">{reference.source} <ExternalLink size={12}/></a><span>Source checked {new Date(`${reference.verified}T00:00:00`).toLocaleDateString('en-IN',{day:'numeric',month:'short',year:'numeric'})}</span></div></div></details>)}</div>
    {!matches.length && <FeatureEmpty icon={Search} title="No sources match" detail="Try another search term or filter."/>}
    <div className="legal-library-note"><Info size={13}/> Legal context only. Applicability depends on facts, jurisdiction, commencement, and later changes. Verify the original source before acting.</div>
  </section>;
}

function VerdictCard({ verdict, flow, compact = false }) {
  const [expanded, setExpanded] = useState(!compact);
  const status = verdict.status || 'questionable';
  const citationList = verdict.citations || [];
  const statusLabel = { violation: 'Check this', questionable: 'Check this', compliant: 'No issue flagged' }[status] || 'Check this';
  return <article className={`verdict-card ${status} ${compact ? 'compact-verdict' : ''}`}><button className="verdict-card-head" onClick={() => compact && setExpanded(!expanded)}><span className={`verdict-symbol ${status}`}>{status === 'violation' ? <ShieldAlert size={15}/> : status === 'questionable' ? <AlertTriangle size={15}/> : <BadgeCheck size={15}/>}</span><span className={`verdict-label ${status}`}>{statusLabel}</span>{flow && <span className="verdict-flow-meta"><code>{flow.host}</code> · signal score {Math.round(flow.severity)}</span>}<ChevronDown size={14} className={expanded ? 'rotate' : ''}/></button>{expanded && <div className="verdict-body"><p>{verdict.reasoning}</p>{citationList.length ? <><div className="source-caption">Agent-supplied references · confirm the source and its application to these facts.</div><div className="citations">{citationList.map((citation, index) => <a key={`${citation.url}-${index}`} href={citation.url} target="_blank" rel="noreferrer"><BookOpenCheck size={12}/><span><b>{citation.source}</b><small>{citation.section}{citation.sourceType ? ` · ${citation.sourceType}` : ' · type unspecified'}</small></span><ExternalLink size={11}/></a>)}</div></> : <div className="not-covered"><Info size={12}/> No source returned. Verify this finding.</div>}</div>}</article>;
}

function FootprintPage({ notify, onFindings }) {
  const [email, setEmail] = useState('');
  const [scanState, setScanState] = useState('idle');
  const [scanResult, setScanResult] = useState(null);
  const [zipFile, setZipFile] = useState(null);
  const [showBoundary, setShowBoundary] = useState(false);
  const linkedApps = useGhostStore((s) => s.linkedApps);
  const setLinkedApps = useGhostStore((s) => s.setLinkedApps);
  const flows = useGhostStore((s) => s.flows);
  const linkApp = async (provider) => {
    const connector = window.GhostPrintIntegrations?.connectApp;
    try {
      if (typeof connector === 'function') {
        await connector({ provider: provider.toLowerCase() });
      } else {
        const response = await fetch(`/api/oauth/${provider.toLowerCase()}/start`, { method: 'POST', credentials: 'same-origin' });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || 'The provider authorization route is not configured on this website yet.');
        if (typeof result.authorizationUrl !== 'string' || !result.authorizationUrl.startsWith('https://')) throw new Error('The account service did not return a secure authorization URL.');
        window.location.assign(result.authorizationUrl);
        return;
      }
      setLinkedApps(linkedApps.includes(provider) ? linkedApps : [...linkedApps, provider]);
      notify(`${provider} account connected.`);
    } catch (error) {
      notify(error?.message || `${provider} sign-in was cancelled or could not complete.`);
    }
  };
  const disconnectApp = async (provider) => {
    const connector = window.GhostPrintIntegrations?.disconnectApp;
    try {
      if (typeof connector === 'function') await connector({ provider: provider.toLowerCase() });
      else {
        const response = await fetch(`/api/oauth/${provider.toLowerCase()}/disconnect`, { method: 'POST', credentials: 'same-origin' });
        const result = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(result.error || 'The account service could not disconnect this app.');
      }
      setLinkedApps(linkedApps.filter((item) => item !== provider));
      notify(`${provider} disconnected.`);
    } catch (error) {
      notify(error?.message || `${provider} could not be disconnected.`);
    }
  };
  const scan = async (event) => {
    event.preventDefault();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setScanState('error'); setScanResult('Enter a valid email address.'); return; }
    setScanState('loading'); setScanResult(null);
    try { const response = await fetch('/api/hibp', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }) }); const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Breach proxy is unavailable.'); setScanResult(result); setScanState('done'); }
    catch (error) { setScanResult(error.message || 'The breach scan proxy is not configured yet.'); setScanState('error'); }
  };
  return <div className="page-wrap"><PageHeading kicker="ACCOUNT CONNECTIONS" title="Link your apps" description="Choose which accounts to connect." actions={<button className="btn secondary" onClick={() => setShowBoundary(!showBoundary)}><ShieldCheck size={14}/> Data boundary</button>}/>
    {showBoundary && <div className="boundary-card"><ShieldCheck size={17}/><div><b>Be precise about what leaves this device.</b><p>OAuth uses provider consent. A breach scan sends your email to GhostPrint’s HIBP proxy. Google Takeout ZIP review stays in the browser. This interface does not claim zero network activity.</p></div></div>}
    <section className="footprint-score-strip"><div className="footprint-icon"><Link2 size={19}/></div><div><b>Linked accounts</b><p>Review access before connecting.</p></div><div className="footprint-count"><span>LINKED APPS</span><b>{linkedApps.length} <small>/ 5</small></b></div></section>
    <section className="section-panel providers-panel"><PanelHeading title="Choose apps to link" sub="Select a service to connect."/><div className="provider-grid">{[{ name: 'Instagram', detail: 'Profile and connected activity · permissions vary', icon: Fingerprint }, { name: 'Reddit', detail: 'Profile and public contribution history', icon: CircleHelp }, { name: 'Spotify', detail: 'Listening history and saved library', icon: Activity }, { name: 'Google', detail: 'Account data and Takeout options', icon: Hexagon }, { name: 'GitHub', detail: 'Profile, repositories, and public activity', icon: Github }].map(({ name, detail, icon: Icon }) => { const isLinked = linkedApps.includes(name); return <div className={`provider-card ${isLinked ? 'is-linked' : ''}`} key={name}><div className={`provider-icon ${name.toLowerCase()}`}><Icon size={19}/></div><div className="provider-body"><div className="provider-title"><b>{name}</b><span>{isLinked ? 'CONNECTED' : 'ACCOUNT LINK'}</span></div><p>{detail}</p></div><button className={`btn ${isLinked ? 'secondary' : 'primary'} compact`} onClick={() => isLinked ? disconnectApp(name) : linkApp(name)}>{isLinked ? <>Disconnect <X size={12}/></> : <>Connect account <ArrowRight size={12}/></>}</button></div>; })}</div><div className="scope-note"><KeyRound size={13}/> Review provider permissions before approving.</div></section>
    <section className="guidance-preview"><div className="guidance-preview-icon"><BookOpenCheck size={20}/></div><div><span>AFTER LINKING · EVIDENCE & OPTIONS</span><h2>Findings & next steps</h2><p>Evidence, options, and legal guidance.</p></div><button className="btn secondary" onClick={onFindings}>Open findings & legal guidance <ArrowRight size={14}/></button></section>
    <div className="footprint-grid"><section className="section-panel breach-panel"><PanelHeading title="Breach scan" sub="Check a mailbox against known breach disclosures."/><form onSubmit={scan}><label className="field-label" htmlFor="breach-email">EMAIL ADDRESS</label><div className="email-input"><Mail size={14}/><input id="breach-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com"/><button className="btn primary compact" disabled={scanState === 'loading'}>{scanState === 'loading' ? <LoaderCircle className="spin" size={13}/> : <Search size={13}/>}Scan</button></div></form>{scanState === 'error' && <div className="scan-result error"><AlertTriangle size={14}/><span>{scanResult}<small>A secure breach-check service must be configured before a scan can run.</small></span></div>}{scanState === 'done' && <div className="scan-result success"><CheckCircle2 size={14}/><span>Scan complete<small>{JSON.stringify(scanResult)}</small></span></div>}<div className="privacy-callout"><Info size={13}/> This is the one module where an identifier may reach a server. A local proxy is required; the app will show an error if it is unavailable.</div></section>
      <section className="section-panel takeout-panel"><PanelHeading title="Google Takeout" sub="Optional in-browser archive review."/><label className="takeout-drop"><input type="file" accept=".zip,application/zip" onChange={(event) => setZipFile(event.target.files?.[0] || null)}/><FileArchive size={22}/><b>{zipFile ? zipFile.name : 'Choose a Takeout ZIP'}</b><span>{zipFile ? `${formatBytes(zipFile.size)} · local file selected` : 'Location and YouTube history · processed in browser'}</span></label><p className="takeout-note"><Info size={12}/> Google Takeout has no general public API for this workflow. ZIP parsing is not connected yet; selecting a file does not upload it.</p></section></div>
    <section className="section-panel footprint-signals"><PanelHeading title="Data activity signals" sub="As app connections become available, compare account data with observed activity."/><div className="signal-placeholder"><Network size={17}/><span><b>No account-to-activity matches yet</b><small>Link an account and collect observations to compare what it shares.</small></span><button className="btn secondary compact" onClick={() => notify('Open Detailed activity to begin a local capture.')} >View detailed activity <ArrowRight size={12}/></button></div></section>
  </div>;
}

function PageHeading({ kicker, title, description, actions }) { return <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/>{kicker}</div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="heading-actions">{actions}</div>}</div>; }
function PanelHeading({ title, sub, count }) { return <div className="section-heading"><div><h2>{title}</h2><p>{sub}</p></div>{count && <span className="section-count">{count}</span>}</div>; }
function flagEmoji(code = '') { const country = String(code).toUpperCase(); return /^[A-Z]{2}$/.test(country) ? String.fromCodePoint(...country.split('').map((char) => 127397 + char.charCodeAt())) : '◌'; }
function severityWord(score = 0) { return score >= 75 ? 'high' : score >= 40 ? 'medium' : 'low'; }
function short(label, limit) { return label.length > limit ? `${label.slice(0, limit - 1)}…` : label; }
function Modal({ title, eyebrow, onClose, children }) { return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="modal"><div className="modal-head"><div><div className="eyebrow">{eyebrow}</div><h2>{title}</h2></div><button className="icon-btn" onClick={onClose}><X size={16}/></button></div>{children}</section></div>; }

createRoot(document.getElementById('root')).render(<App/>);
