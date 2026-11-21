import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { useVirtualizer } from '@tanstack/react-virtual';
import {
  Activity, AlertTriangle, ArrowDownToLine, ArrowRight, ArrowUpRight, BadgeCheck,
  Ban, Bell, Blocks, BookOpenCheck, Check, CheckCircle2, ChevronDown, ChevronRight,
  CircleHelp, Clipboard, Clock3, Code2, Cookie, Copy, Database, Download, ExternalLink,
  Eye, EyeOff, Fingerprint, FileArchive, FileCheck2, FileKey2, FileText, Filter, Github,
  Globe2, HardDrive, Hexagon, Info, KeyRound, Laptop, Link2, ListFilter, LoaderCircle,
  LockKeyhole, Mail, MapPin, Menu, Network, Radar, RefreshCw, Search, Send, Settings2,
  Shield, ShieldAlert, ShieldCheck, Smartphone, Sparkles, SquareArrowOutUpRight, Terminal,
  TriangleAlert, Wifi, X, Zap
} from 'lucide-react';
import { AGENT_SOCKET_DEFAULT, formatBytes, validateInbound } from './schema';
import { OUTBOUND } from './protocol';
import { useGhostStore } from './store';
import './styles.css';

const wsOverride = (import.meta.env.VITE_AGENT_WS_URL || '').trim();
const socketKey = 'ghostprint-agent-url';
const getAgentUrl = () => localStorage.getItem(socketKey) || wsOverride || AGENT_SOCKET_DEFAULT;
const countryNames = { US: 'United States', IL: 'Israel', IE: 'Ireland', IN: 'India', SG: 'Singapore', GB: 'United Kingdom', DE: 'Germany' };
const piiNames = { adid: 'Advertising ID', gps: 'Location', imei: 'IMEI', email: 'Email', phone: 'Phone', contact: 'Contacts', clipboard: 'Clipboard' };
const piiShort = { adid: 'AD ID', gps: 'GPS', imei: 'IMEI', email: 'EMAIL', phone: 'PHONE', contact: 'CONTACT', clipboard: 'CLIPBOARD' };
const navItems = [
  { id: 'radar', label: 'Live Leak Radar', icon: Radar, priority: 'HERO' },
  { id: 'legal', label: 'Findings & Next Steps', icon: ShieldCheck, priority: 'P0' },
  { id: 'footprint', label: 'Stored Footprint', icon: Database, priority: 'P2' },
];

function App() {
  const agent = useGhostStore((s) => s.agent);
  const connected = useGhostStore((s) => s.agent.connected);
  const flows = useGhostStore((s) => s.flows);
  const consent = useGhostStore((s) => s.consent);
  const selectedFlowId = useGhostStore((s) => s.selectedFlowId);
  const filters = useGhostStore((s) => s.filters);
  const selectedVerdict = useGhostStore((s) => selectedFlowId ? s.verdicts[selectedFlowId] : undefined);
  const [page, setPage] = useState('radar');
  const [device, setDevice] = useState('laptop');
  const [socketUrl, setSocketUrl] = useState(getAgentUrl());
  const [urlDraft, setUrlDraft] = useState(getAgentUrl());
  const [drawer, setDrawer] = useState(false);
  const [toast, setToast] = useState('');
  const [search, setSearch] = useState('');
  const [settings, setSettings] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [notifications, setNotifications] = useState(false);
  const [lastInteractionAt, setLastInteractionAt] = useState(Date.now());
  const [clockNow, setClockNow] = useState(Date.now());
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
        if (type === 'status') store.getState().setAgent({ connected: true, known: true, capturing: !!data.capturing, device: data.device || device, version: data.agentVersion || '' });
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
  useEffect(() => {
    const markActive = () => setLastInteractionAt(Date.now());
    const clock = window.setInterval(() => setClockNow(Date.now()), 1000);
    window.addEventListener('pointerdown', markActive);
    window.addEventListener('keydown', markActive);
    return () => { window.clearInterval(clock); window.removeEventListener('pointerdown', markActive); window.removeEventListener('keydown', markActive); };
  }, []);

  const selectedFlow = flows.find((flow) => flow.id === selectedFlowId);
  const send = useCallback((payload) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) { notify('Local agent is offline. Start it, then wait for the connection.'); return false; }
    socket.send(JSON.stringify(payload));
    return true;
  }, [notify]);
  const selectFlow = (id) => { store.getState().selectFlow(id); setDrawer(true); };

  if (!consent) return <ConsentGate agent={agent} device={device} setDevice={setDevice} socketUrl={socketUrl} onAccept={() => store.getState().setConsent(true)} onSettings={() => setSettings(true)} />;

  const filteredFlows = flows.filter((flow) => {
    const query = search.trim().toLowerCase();
    return (!query || `${flow.app} ${flow.host} ${flow.company || ''} ${flow.id}`.toLowerCase().includes(query))
      && (!filters.app || flow.app === filters.app)
      && (!filters.piiType || flow.pii?.some((item) => item.type === filters.piiType))
      && flow.severity >= filters.minSeverity;
  });

  return <div className="console-shell">
    <aside className={`sidebar ${mobileNav ? 'mobile-open' : ''}`}>
      <Brand />
      <div className="local-device"><div className="device-icon"><Laptop size={15}/></div><div><b>This device</b><span>Local audit session</span></div><span className={`presence ${connected ? 'online' : ''}`}/></div>
      <div className="side-label">INVESTIGATE</div>
      <nav className="side-nav">{navItems.map(({ id, label, icon: Icon, priority }) => <button key={id} className={`side-link ${page === id ? 'active' : ''}`} onClick={() => { setPage(id); setMobileNav(false); }}><Icon size={17}/><span>{label}</span><small>{priority}</small></button>)}</nav>
      <div className="sidebar-rule"/>
      <div className="side-label section-label">SESSION</div>
      <div className="session-card"><div className="session-head"><span className="session-pulse"/><b>Local agent</b><small>{connected ? 'CONNECTED' : 'OFFLINE'}</small></div><span className="session-url">{socketUrl.replace(/^wss?:\/\//, '')}</span><button onClick={() => { setUrlDraft(socketUrl); setSettings(true); }}><Settings2 size={13}/> Connection settings</button></div>
      <div className="sidebar-rule"/>
      <div className="privacy-note"><Shield size={15}/><p><b>Your data stays here.</b><br/>Capture and analysis run on your device. Nothing is stored on a GhostPrint server.</p></div>
      <div className="sidebar-bottom"><div className="agent-version"><span>GHOSTPRINT</span><b>v2.0.0 <i>LOCAL-FIRST</i></b></div><button title="About GhostPrint" onClick={() => notify('GhostPrint audits only devices and networks you own.') }><CircleHelp size={15}/></button></div>
    </aside>

    <main className="main-column">
      <header className="topbar"><div className="top-left"><button className="icon-btn mobile-menu" onClick={() => setMobileNav(!mobileNav)}><Menu size={17}/></button><div className="crumb"><span>Workspace</span><ChevronRight size={13}/><b>{navItems.find((item) => item.id === page)?.label}</b></div></div><div className="top-right"><div className={`agent-pill ${connected ? 'connected' : 'offline'}`}><span/><b>{connected ? 'Agent connected' : 'Agent offline'}</b><small>{connected ? agent.version || 'LOCAL' : 'RECONNECTING'}</small></div><button className="icon-btn" onClick={() => setNotifications(!notifications)} title="Alerts"><Bell size={16}/>{flows.some((flow) => flow.severity >= 75) && <i className="alert-dot"/>}</button>{notifications && <div className="alerts-pop"><div><b>Recent alerts</b><button onClick={() => setNotifications(false)}><X size={13}/></button></div>{flows.filter((flow) => flow.severity >= 75).slice(0, 4).map((flow) => <button key={flow.id} onClick={() => { setNotifications(false); selectFlow(flow.id); }}><ShieldAlert size={14}/><span><b>{flow.app}</b> sent {flow.pii?.[0] ? piiNames[flow.pii[0].type] : 'high-severity traffic'}<small>{flow.host}</small></span></button>)}{!flows.some((flow) => flow.severity >= 75) && <p>No high-severity alerts yet.</p>}</div>}<div className="avatar">N</div></div></header>
      {!connected && <div className="offline-banner"><div><Wifi size={15}/><span><b>Agent offline</b><small>Showing the last known state. Reconnecting automatically.</small></span></div><button onClick={() => setSettings(true)}>Connection settings <ArrowRight size={13}/></button></div>}
      {page === 'radar' && <RadarPage flows={filteredFlows} allFlows={flows} search={search} setSearch={setSearch} agent={agent} device={device} lastInteractionAt={lastInteractionAt} clockNow={clockNow} send={send} selectFlow={selectFlow} notify={notify}/>}
      {page === 'legal' && <LegalPage allFlows={flows} send={send} notify={notify}/>}
      {page === 'footprint' && <FootprintPage notify={notify}/>}
      <footer className="app-footer"><span><span className="footer-lock"><LockKeyhole size={11}/></span> AUDITING YOUR OWN DEVICE · LOCAL SESSION</span><span>GHOSTPRINT <i/> PRIVACY FORENSICS</span></footer>
    </main>

    {drawer && selectedFlow && <FlowDrawer flow={selectedFlow} verdict={selectedVerdict} close={() => setDrawer(false)} send={send}/>}
    {settings && <Modal title="Agent connection" eyebrow="LOCAL SESSION" onClose={() => setSettings(false)}><div className="modal-copy">Connect this dashboard to the local capture agent. By default it uses the loopback WebSocket in the frozen team contract.</div><label className="field-label" htmlFor="agent-url">WebSocket address</label><input id="agent-url" className="text-input mono-input" value={urlDraft} onChange={(event) => setUrlDraft(event.target.value)} placeholder="ws://localhost:8787"/><div className="inline-note"><ShieldCheck size={14}/> Keep the capture agent bound to <code>127.0.0.1</code>. For a forwarded port, use its WebSocket URL here.</div><div className="modal-status"><span className={`presence ${connected ? 'online' : ''}`}/>{connected ? `Connected${agent.version ? ` · ${agent.version}` : ''}` : 'Offline · reconnecting automatically'}</div><div className="modal-actions"><button className="btn secondary" onClick={() => setSettings(false)}>Cancel</button><button className="btn primary" onClick={() => { const normalized = urlDraft.trim(); if (!/^wss?:\/\//i.test(normalized)) { notify('Use a ws:// or wss:// WebSocket URL.'); return; } localStorage.setItem(socketKey, normalized); setSocketUrl(normalized); setSettings(false); notify('Agent address updated'); }}>Save connection</button></div></Modal>}
    {toast && <div className="toast"><Info size={15}/>{toast}<button onClick={() => setToast('')}><X size={13}/></button></div>}
  </div>;
}

function Brand() { return <div className="brand"><div className="brand-mark"><span/><span/><span/></div><div><b>ghostprint</b><small>PRIVACY FORENSICS</small></div><span className="brand-v2">V2</span></div>; }

function ConsentGate({ agent, device, setDevice, socketUrl, onAccept, onSettings }) {
  const [showSetup, setShowSetup] = useState(false);
  const [checked, setChecked] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => { if (agent.known) setConfirmed(true); }, [agent.known]);
  return <div className="consent-screen"><div className="consent-top"><Brand/><nav className="landing-nav"><a href="#how-it-works">How it works</a><a href="#legal-guidance">Legal guidance</a><button onClick={onSettings}>Connect agent</button></nav><div className="consent-top-status"><span className={`presence ${agent.connected ? 'online' : ''}`}/>{agent.connected ? 'LOCAL AGENT CONNECTED' : agent.known ? 'AGENT OFFLINE' : 'CHECKING AGENT'}</div></div><main className="landing-main"><section className="landing-hero"><div className="landing-sky"><div className="scene-float float-device"><Laptop size={31}/><span>DEVICE</span></div><div className="scene-float float-shield"><ShieldCheck size={28}/><span>PRIVATE</span></div><div className="scene-float float-packet"><Fingerprint size={27}/><span>DATA FLOW</span></div><div className="scene-float float-cookie"><Cookie size={26}/><span>TRACKER</span></div><div className="scene-float float-globe"><Globe2 size={29}/><span>DESTINATION</span></div><div className="scene-orbit-dash dash-one"/><div className="scene-orbit-dash dash-two"/><div className="sky-orbit sky-orbit-one"/><div className="sky-orbit sky-orbit-two"/><span className="sky-star star-one">✳</span><span className="sky-star star-two">✦</span><span className="sky-star star-three">✳</span><div className="sky-pillars"><i/><i/><i/><i/><i/></div><div className="sky-grid"/></div><div className="landing-hero-content"><div className="eyebrow"><span className="eyebrow-line"/> PRIVACY, MADE VISIBLE</div><h1>See what leaves.<br/><span>Know what to do next.</span></h1><p>GhostPrint maps the data leaving your device, connects each finding to its evidence, and helps you consider practical next steps.</p><button className="btn primary landing-cta" onClick={() => setShowSetup(true)}>Start a privacy audit <ArrowRight size={16}/></button><small className="landing-trust"><LockKeyhole size={12}/> Local-first · Evidence-led · Built for your own devices</small></div><div className="hero-caption"><span>01 / UNDERSTAND YOUR DIGITAL FOOTPRINT</span><span>LIVE PRIVACY FORENSICS</span></div></section><section className="landing-proof" id="how-it-works"><div><span>01</span><b>See the traffic</b><p>Watch connections and reported data signals as the local agent observes them.</p></div><div><span>02</span><b>Understand the context</b><p>Review evidence, source references, and analysis from your team’s RAG pipeline.</p></div><div><span>03</span><b>Choose your next step</b><p>Compare practical options, their trade-offs, and what may need professional advice.</p></div></section><section className="landing-legal" id="legal-guidance"><div className="legal-orb"><BookOpenCheck size={23}/></div><div><div className="eyebrow"><span className="eyebrow-line"/> EVIDENCE BEFORE ACTION</div><h2>Clear options.<br/><span>Thoughtful decisions.</span></h2><p>Findings should help you understand what may be happening, what information supports that view, and which steps you could consider. The analysis agents can outline options such as checking an app’s privacy settings, contacting a provider, or seeking qualified legal advice.</p><div className="guidance-chips"><span><Check size={12}/> What the evidence shows</span><span><Check size={12}/> Possible actions and trade-offs</span><span><Check size={12}/> When to seek professional help</span></div><small>Analysis and legal references are provided by the connected agent and your team’s retrieval pipeline as they become available.</small></div></section></main><div className="consent-bottom"><span>GHOSTPRINT <i/> LOCAL-FIRST PRIVACY TOOL</span><span>NO ACCOUNT REQUIRED <i/> NO SERVER-SIDE STORAGE</span></div>{showSetup && <div className="setup-overlay"><section className="consent-card setup-card"><button className="setup-close" aria-label="Close setup" onClick={() => setShowSetup(false)}><X size={17}/></button><div className="consent-card-top"><div className="consent-emblem"><Radar size={23}/><span/></div><div><span className="card-overline">BEFORE YOU BEGIN</span><h2>Set up your audit</h2></div></div><label className="field-label">DEVICE TO AUDIT</label><div className="device-choices"><button className={device === 'laptop' ? 'chosen' : ''} onClick={() => setDevice('laptop')}><Laptop size={16}/>My laptop<span>{device === 'laptop' && <Check size={13}/>}</span></button><button className={device === 'phone' ? 'chosen' : ''} onClick={() => setDevice('phone')}><Smartphone size={16}/>My phone<span>{device === 'phone' && <Check size={13}/>}</span></button></div><div className="agent-check-card"><span className={`agent-check-icon ${agent.connected ? 'online' : ''}`}>{agent.connected ? <CheckCircle2 size={17}/> : agent.known ? <Wifi size={17}/> : <LoaderCircle size={17} className="spin"/>}</span><span><b>{agent.connected ? 'Agent is ready' : agent.known ? 'Agent not detected yet' : 'Checking local agent'}</b><small>{agent.connected ? `${socketUrl} · ${agent.version || 'connection established'}` : agent.known ? 'You can continue in offline mode or start the local agent first.' : 'Trying to reach your local capture agent…'}</small></span><button onClick={onSettings} aria-label="Connection settings"><Settings2 size={15}/></button></div><label className="consent-check"><input type="checkbox" checked={checked} onChange={(event) => setChecked(event.target.checked)}/><span className="custom-check"><Check size={12}/></span><span><b>I own this device and network</b><small>I have permission to inspect the traffic on this device.</small></span></label><button className="btn primary continue-btn" disabled={!checked || !confirmed} onClick={onAccept}>I confirm and continue <ArrowRight size={15}/></button><div className="consent-card-footer"><ShieldCheck size={13}/> Your data stays on this machine</div></section></div>}<div className="consent-art" aria-hidden="true"/></div>;
}

function RadarPage({ flows, allFlows, search, setSearch, agent, device, lastInteractionAt, clockNow, send, selectFlow, notify }) {
  const score = useGhostStore((s) => s.score);
  const filters = useGhostStore((s) => s.filters);
  const setFilter = useGhostStore((s) => s.setFilter);
  const [showGraph, setShowGraph] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [minSeverity, setMinSeverity] = useState(filters.minSeverity);
  const uniqueTrackers = new Set(allFlows.filter((f) => f.tracker).map((f) => f.tracker.name)).size;
  const leakCount = allFlows.filter((flow) => flow.pii?.length).length;
  const idleAfter = lastInteractionAt + 5 * 60 * 1000;
  const idleCalls = agent.capturing && clockNow >= idleAfter ? allFlows.filter((flow) => new Date(flow.ts).getTime() >= idleAfter).length : 0;
  return <div className="page-wrap">
    <PageHeading kicker="LIVE CAPTURE · LOCAL DEVICE" title="Live Leak Radar" description="See the connections leaving your device, as they happen." actions={<><button className="btn secondary" onClick={() => { setShowGraph(!showGraph); }}><Network size={15}/>{showGraph ? 'Hide shadow map' : 'Shadow map'}</button><button className={`btn ${agent.capturing ? 'stop-btn' : 'primary'}`} onClick={() => agent.capturing ? send(OUTBOUND.stop()) : send(OUTBOUND.start(device))}>{agent.capturing ? <><span className="record-dot"/> Stop capture</> : <><Radar size={15}/> Start capture</>}</button></>}/>
    {agent.capturing && <div className="capture-banner"><span className="capture-live"><i/> CAPTURING</span><span>Watching <b>{agent.device === 'phone' ? 'your phone' : 'this laptop'}</b> · local agent {agent.version || 'connected'}</span><span className="capture-time"><Clock3 size={12}/> Session active</span></div>}
    <section className="radar-summary"><div className="score-card"><div className="score-copy"><span className="overline">YOUR EXPOSURE SCORE <Info size={12}/></span><div className="score-number"><strong>{score ? Math.round(score.total) : '—'}</strong><span>/ 1000</span></div><div className="score-trend">{score ? 'Updates as new connections are analyzed' : 'Waiting for the agent to send a score'}</div><div className="score-legend"><i/> LOW <i/> ELEVATED <i/> HIGH <i/> CRITICAL</div></div><ScoreGauge value={score?.total || 0}/><div className="score-bars">{(score?.categories || [{ name: 'Trackers', value: 0 }, { name: 'PII leaked', value: 0 }, { name: 'Cross-border', value: 0 }, { name: 'Consent', value: 0 }]).map((item) => <div className="score-bar" key={item.name}><span>{item.name}</span><div><i style={{ width: `${Math.min(100, item.value)}%` }}/></div><b>{item.value}</b></div>)}</div></div>
      <div className="stat-stack"><Metric icon={Activity} label="Connections" value={allFlows.length} detail={agent.capturing ? 'LIVE THIS SESSION' : 'THIS SESSION'} tone="cyan"/><Metric icon={Fingerprint} label="PII signals" value={leakCount} detail="REDACTED VALUES" tone="violet"/><Metric icon={Blocks} label="Trackers found" value={uniqueTrackers} detail="UNIQUE DESTINATIONS" tone="amber"/><Metric icon={Clock3} label="Idle calls" value={idleCalls} detail={clockNow < idleAfter ? 'AFTER 5M UNTOUCHED' : 'CURRENT IDLE PERIOD'} tone="red"/></div>
    </section>
    {showGraph && <ShadowMap flows={allFlows} onSelect={(flow) => selectFlow(flow.id)} onFilter={(app) => { setFilter('app', app); setShowGraph(false); }}/>}
    <section className="flow-panel"><div className="flow-toolbar"><div><div className="panel-title"><h2>Connection stream</h2><span className="live-count">{allFlows.length.toLocaleString()} FLOWS</span></div><p>Every row is a connection observed by your local agent.</p></div><div className="toolbar-controls"><label className="flow-search"><Search size={14}/><input id="flow-search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search apps, hosts…"/><kbd>⌘ K</kbd></label><div className="filter-anchor"><button className={`btn compact secondary ${filterOpen ? 'filter-on' : ''}`} onClick={() => setFilterOpen(!filterOpen)}><ListFilter size={14}/> Filters<ChevronDown size={13}/></button>{filterOpen && <div className="filter-pop"><div className="filter-pop-head"><b>Filter flows</b><button onClick={() => { setFilter('app', ''); setFilter('piiType', ''); setMinSeverity(0); setFilter('minSeverity', 0); }}><RefreshCw size={12}/> Reset</button></div><label>APP<input value={filters.app} onChange={(event) => setFilter('app', event.target.value)} placeholder="Any app" list="app-options"/></label><datalist id="app-options">{[...new Set(allFlows.map((flow) => flow.app))].map((app) => <option key={app} value={app}/>)}</datalist><label>PERSONAL DATA<select value={filters.piiType} onChange={(event) => setFilter('piiType', event.target.value)}><option value="">Any type</option>{Object.entries(piiNames).map(([key, value]) => <option key={key} value={key}>{value}</option>)}</select></label><label>MINIMUM SEVERITY <b>{minSeverity}</b><input type="range" min="0" max="100" value={minSeverity} onChange={(event) => { setMinSeverity(Number(event.target.value)); setFilter('minSeverity', Number(event.target.value)); }}/></label></div>}</div></div></div>
      <div className="flow-columns"><span>APPLICATION / DESTINATION</span><span>DATA OBSERVED</span><span>METHOD</span><span>DESTINATION</span><span>SEVERITY</span><span/></div>
      <FlowList flows={flows} allCount={allFlows.length} onSelect={onSelectFromList(selectFlow)} agent={agent} search={search}/>
      <div className="flow-footer"><span>Showing <b>{flows.length}</b> of <b>{allFlows.length}</b> observed flows <i/> newest first <i/> max 2,000 kept in memory</span><button onClick={() => { if (agent.connected) notify('Connection stream is already connected.'); else notify('Reconnecting to local agent…'); }}><RefreshCw size={12}/> Auto-reconnect enabled</button></div>
    </section>
    <div className="radar-footnotes"><div><span className="note-icon"><ShieldCheck size={14}/></span><span><b>Evidence first.</b> Flow facts come from the local agent; this dashboard does not invent detections.</span></div><div><span className="note-icon amber"><AlertTriangle size={14}/></span><span><b>Metadata-only is still evidence.</b> Pinned apps may hide payloads while host, timing, and size remain visible.</span></div></div>
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
  if (!flows.length) return <div className="flow-empty">{allCount === 0 ? agent.connected ? <><div className="empty-orbit"><Radar size={23}/></div><b>Ready when you are</b><p>Start capture, then open an app or website on your device to see its connections here.</p></> : <><div className="empty-orbit offline"><Wifi size={22}/></div><b>{search ? 'No matching flows' : 'No local agent connected'}</b><p>{search ? 'Try a different search.' : 'Start the agent on this device. The dashboard will reconnect automatically.'}</p></> : <><div className="empty-orbit"><Filter size={21}/></div><b>No flows match these filters</b><p>Clear one or more filters to show more connections.</p></>}</div>;
  return <div className="flow-list" ref={parentRef} style={{ height: 'min(56vh, 640px)', minHeight: 330 }}><div style={{ height: rowVirtualizer.getTotalSize(), width: '100%', position: 'relative' }}>{rowVirtualizer.getVirtualItems().map((virtualRow) => { const flow = flows[virtualRow.index]; return <div className="virtual-row-wrap" key={flow.id} data-index={virtualRow.index} ref={rowVirtualizer.measureElement} style={{ position: 'absolute', top: 0, left: 0, width: '100%', transform: `translateY(${virtualRow.start}px)` }}><FlowRow flow={flow} onClick={() => onSelect(flow)}/></div>; })}</div></div>;
}

function FlowRow({ flow, onClick }) {
  const pii = flow.pii || [];
  const severityClass = flow.severity >= 75 ? 'high' : flow.severity >= 40 ? 'medium' : 'low';
  const location = countryNames[flow.country] || flow.country || 'Unknown';
  return <button className="flow-row" onClick={onClick}><div className="flow-app"><div className="app-glyph">{flow.app?.slice(0, 1).toUpperCase() || '?'}</div><span><b>{flow.app}</b><code>{flow.host}{flow.path || ''}</code></span><span className={`capture-mode ${flow.decrypted ? 'decrypted' : 'metadata'}`}>{flow.decrypted ? <><Eye size={11}/> DECRYPTED</> : <><EyeOff size={11}/> METADATA</>}</span></div><div className="pii-cell">{pii.length ? pii.slice(0, 3).map((hit, index) => <span className={`pii-chip ${hit.type}`} key={`${hit.type}-${index}`}>{piiShort[hit.type] || hit.type.toUpperCase()}</span>) : <span className="no-pii">NO PII DETECTED</span>}</div><div className="method-cell"><span>{flow.method || '—'}</span><code>{formatBytes(flow.bytes)}</code></div><div className="destination-cell"><span className="flag">{flagEmoji(flow.country)}</span><span><b>{flow.company || 'Unknown destination'}</b><small>{location}{flow.tracker?.name ? ` · ${flow.tracker.name}` : ''}</small></span></div><div className={`severity-cell ${severityClass}`}><span className="severity-value">{Math.round(flow.severity)}</span><div><span className="severity-track"><i style={{ width: `${Math.max(3, Math.min(100, flow.severity))}%` }}/></span><small>{severityClass.toUpperCase()}</small></div></div><ArrowRight size={14} className="row-arrow"/></button>;
}

function ShadowMap({ flows, onSelect, onFilter }) {
  const graph = useMemo(() => buildGraph(flows), [flows]);
  if (!flows.length) return <div className="shadow-panel"><div><b>Shadow Map</b><span>Graph builds as the agent observes flows.</span></div><div className="graph-empty"><Network size={19}/> Waiting for evidence</div></div>;
  return <section className="shadow-panel"><div className="shadow-head"><div><div className="panel-title"><h2>Shadow Map</h2><span className="mini-tag">APP → COMPANY → DATA</span></div><p>Click an app to filter flows. Select a connection to inspect its evidence.</p></div><div className="graph-legend"><span><i className="app-node-dot"/>APP</span><span><i className="company-node-dot"/>COMPANY</span><span><i className="data-node-dot"/>DATA</span></div></div><div className="graph-wrap"><svg viewBox="0 0 900 230" className="shadow-svg" role="img" aria-label="Observed applications, companies, and data types">{graph.edges.map((edge) => <line key={edge.id} x1={edge.from.x} y1={edge.from.y} x2={edge.to.x} y2={edge.to.y} className={edge.identity ? 'identity-edge' : 'graph-edge'}/>)}{graph.nodes.map((node) => <g key={node.id} className={`graph-node ${node.kind}`} transform={`translate(${node.x},${node.y})`} onClick={() => node.kind === 'app' ? onFilter(node.label) : node.flow && onSelect(node.flow)} role="button" tabIndex="0"><circle r={node.kind === 'company' ? 19 : node.kind === 'app' ? 15 : 13}/><text textAnchor="middle" dy="4">{node.glyph}</text><text className="node-label" textAnchor="middle" y="32">{short(node.label, 18)}</text></g>)}</svg></div></section>;
}

function buildGraph(flows) {
  const chosen = flows.slice(0, 120);
  const apps = [...new Set(chosen.map((f) => f.app))].slice(0, 7);
  const companies = [...new Set(chosen.map((f) => f.company).filter(Boolean))].slice(0, 8);
  const types = [...new Set(chosen.flatMap((f) => (f.pii || []).map((p) => p.type)))].slice(0, 6);
  const nodes = [];
  apps.forEach((label, i) => nodes.push({ id: `a${i}`, label, kind: 'app', glyph: label[0]?.toUpperCase() || 'A', x: 65 + i * 43, y: 62 + (i % 3) * 47, flow: chosen.find((f) => f.app === label) }));
  companies.forEach((label, i) => nodes.push({ id: `c${i}`, label, kind: 'company', glyph: label.slice(0, 2).toUpperCase(), x: 385 + (i % 4) * 37, y: 42 + Math.floor(i / 4) * 108, flow: chosen.find((f) => f.company === label) }));
  types.forEach((label, i) => nodes.push({ id: `p${i}`, label: piiNames[label] || label, kind: 'data', glyph: (piiShort[label] || label).slice(0, 3), x: 770 + (i % 2) * 39, y: 43 + i * 29, flow: chosen.find((f) => f.pii?.some((p) => p.type === label)) }));
  const byApp = new Map(nodes.filter((n) => n.kind === 'app').map((n) => [n.label, n]));
  const byCompany = new Map(nodes.filter((n) => n.kind === 'company').map((n) => [n.label, n]));
  const byType = new Map(nodes.filter((n) => n.kind === 'data').map((n) => [n.label, n]));
  const edges = [];
  chosen.slice(0, 70).forEach((flow, i) => { const from = byApp.get(flow.app); const to = byCompany.get(flow.company); if (from && to) edges.push({ id: `e${i}`, from, to, identity: (flow.pii || []).some((p) => p.type === 'adid') }); (flow.pii || []).forEach((pii) => { const dataNode = byType.get(pii.type); if (to && dataNode) edges.push({ id: `p${i}-${pii.type}`, from: to, to: dataNode, identity: pii.type === 'adid' }); }); });
  return { nodes, edges };
}

function FlowDrawer({ flow, verdict, close, send }) {
  const [copied, setCopied] = useState('');
  const [rawMessage, setRawMessage] = useState(false);
  const pii = flow.pii || [];
  const copy = async (text, label) => { try { await navigator.clipboard.writeText(text); setCopied(label); window.setTimeout(() => setCopied(''), 1500); } catch { setCopied('Clipboard unavailable'); } };
  return <div className="drawer-backdrop" onMouseDown={(event) => event.target === event.currentTarget && close()}><aside className="flow-drawer"><div className="drawer-head"><div><div className="eyebrow">FLOW EVIDENCE <span className="flow-id">{flow.id}</span></div><h2>{flow.app} <span>→</span> {flow.company || flow.host}</h2></div><button className="icon-btn" onClick={close}><X size={16}/></button></div><div className={`drawer-mode ${flow.decrypted ? 'decrypted' : 'metadata'}`}>{flow.decrypted ? <Eye size={14}/> : <EyeOff size={14}/>}<span><b>{flow.decrypted ? 'Decrypted traffic' : 'Metadata-only flow'}</b><small>{flow.decrypted ? 'The agent inspected this request payload.' : 'Payload unavailable; hostname, timing and size remain observable.'}</small></span></div><div className="drawer-section"><div className="drawer-section-title">DESTINATION <button onClick={() => copy(flow.host, 'Copied host')}><Copy size={12}/>{copied === 'Copied host' ? 'Copied' : 'Copy host'}</button></div><div className="evidence-grid"><Evidence label="HOST" value={flow.host} mono/><Evidence label="PARENT COMPANY" value={flow.company || 'Not attributed'}/><Evidence label="JURISDICTION" value={`${flagEmoji(flow.country)} ${countryNames[flow.country] || flow.country}`} /><Evidence label="DESTINATION IP" value={flow.ip || 'Not provided'} mono/><Evidence label="REQUEST" value={`${flow.method || '—'} ${flow.path || '/'}`} mono/><Evidence label="PAYLOAD SIZE" value={formatBytes(flow.bytes)}/><Evidence label="OBSERVED AT" value={new Date(flow.ts).toLocaleString()} mono/><Evidence label="TRACKER" value={flow.tracker ? `${flow.tracker.name} · ${flow.tracker.category}` : 'No tracker attribution'} /></div></div><div className="drawer-section"><div className="drawer-section-title">PERSONAL DATA SIGNALS <span>{pii.length} DETECTED</span></div>{pii.length ? <div className="pii-evidence">{pii.map((hit, index) => <div className="pii-evidence-row" key={`${hit.type}-${index}`}><span className={`pii-chip ${hit.type}`}>{piiShort[hit.type] || hit.type}</span><code>{hit.redacted}</code><span className="confidence">{Math.round(hit.confidence * 100)}% conf.</span><button title="Raw value status" onClick={() => setRawMessage(!rawMessage)}><Eye size={13}/> Reveal</button></div>)}{rawMessage && <div className="redaction-note"><LockKeyhole size={13}/><span>The frozen agent contract sends redacted values only. No raw value is available to reveal in this dashboard.</span></div>}</div> : <div className="no-signals"><CheckCircle2 size={15}/> No personal data signal was reported for this flow.</div>}</div><div className="drawer-section"><div className="drawer-section-title">SEVERITY <span className={`severity-number ${severityWord(flow.severity)}`}>{Math.round(flow.severity)} / 100 · {severityWord(flow.severity).toUpperCase()}</span></div><div className="severity-large"><div><i className={severityWord(flow.severity)} style={{ width: `${Math.max(3, flow.severity)}%` }}/></div><span>Scored by the local detection model</span></div></div><div className="drawer-section verdict-drawer"><div className="drawer-section-title">AGENT FINDING</div>{verdict ? <VerdictCard verdict={verdict} compact/> : <div className="verdict-pending"><span><Clock3 size={14}/></span><p>No verdict has arrived for this flow yet.</p><button onClick={() => send({ type: 'analyze', flowId: flow.id })}>Ask agent to review <ArrowRight size={13}/></button></div>}</div><div className="drawer-bottom"><span>Evidence from local agent stream</span><button className="btn secondary compact" onClick={() => copy(JSON.stringify({ ...flow, pii }), 'Copied flow JSON')}><Copy size={13}/>{copied === 'Copied flow JSON' ? 'Copied' : 'Copy flow record'}</button></div></aside></div>;
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
  const [complaint, setComplaint] = useState('To: Data Protection Officer\nSubject: Request for information regarding processing of my personal data\n\nI am writing to request information about the personal data transmitted by this application, the purpose and legal basis for that processing, and the entities that received it.\n\nEvidence reference: [add flow IDs and timestamps]\n\nPlease respond within the applicable period under the Digital Personal Data Protection Act, 2023.');
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
  return <div className="page-wrap"><PageHeading kicker="DPDP ACT 2023 · EVIDENCE-LED" title="Findings & Next Steps" description="Review what was observed, check the sources, and compare possible next steps." actions={<span className="local-analysis-label"><LockKeyhole size={12}/> VERDICTS FROM LOCAL AGENT</span>}/>
    <section className="legal-summary"><div className="legal-intro"><div className="legal-icon"><BookOpenCheck size={19}/></div><div><b>Understand the evidence. Weigh your options.</b><p>Your team’s retrieval pipeline and analysis agents can connect findings to relevant sources, explain uncertainty, and suggest possible next steps. Review the evidence before acting.</p></div></div><div className="verdict-counts"><div><b>{Object.values(verdicts).filter((v) => v.status === 'violation').length}</b><span>POTENTIAL CONCERN</span></div><div><b>{Object.values(verdicts).filter((v) => v.status === 'questionable').length}</b><span>NEEDS REVIEW</span></div><div><b>{Object.values(verdicts).filter((v) => v.status === 'compliant').length}</b><span>NO ISSUE FLAGGED</span></div></div></section>
    <div className="legal-grid"><div className="legal-main"><section className="section-panel"><PanelHeading title="Findings & source notes" sub="Agent-generated analysis with supporting references, grouped by app." count={`${Object.keys(verdicts).length} findings`}/>{grouped.length ? <div className="verdict-groups">{grouped.map(([app, entries]) => <div className="verdict-group" key={app}><div className="app-group-head"><span className="app-glyph">{app[0]}</span><b>{app}</b><small>{entries.length} {entries.length === 1 ? 'flow' : 'flows'} reviewed</small></div>{entries.map(({ verdict, flow }) => <VerdictCard key={verdict.flowId} verdict={verdict} flow={flow}/>)}</div>)}</div> : <div className="legal-empty"><div className="empty-orbit"><BookOpenCheck size={20}/></div><b>No analysis yet</b><p>Start capture, select a flow, and request analysis. Findings, reasoning, and any available source references will appear here when your connected agent returns them.</p></div>}</section>
      <section className="section-panel action-report"><PanelHeading title="Possible next steps" sub="Review these options against the evidence and your needs." count={`${rankedFixes.length} suggested`}/><div className="action-list">{rankedFixes.length ? rankedFixes.map((fix, index) => <div className="action-row" key={fix.host}><span className="action-rank">0{index + 1}</span><span className="action-lock"><Ban size={15}/></span><div className="action-info"><b>Review options for {fix.host}</b><code>{fix.app} · tracker destination</code></div><span className="impact-pill">−{fix.impact} score</span></div>) : <div className="action-empty"><CheckCircle2 size={16}/> No priority tracker destinations were observed in this session.</div>}</div><div className="blocklist-control"><div><b>Build a blocklist</b><small>Generated by the agent from observed tracker domains.</small></div><select value={format} onChange={(event) => setFormat(event.target.value)}><option value="hosts">hosts file</option><option value="pihole">Pi-hole</option><option value="nextdns">NextDNS</option><option value="pf">pf firewall</option></select><button className="btn secondary compact" onClick={() => { send(OUTBOUND.blocklist(format)); if (baseline === null) setBaseline(leakedCount); }}><Blocks size={13}/> Generate</button><button className="btn secondary compact" onClick={copyBlocklist}><Copy size={13}/>{copied ? 'Copied' : 'Copy'}</button></div>{blocklist && <pre className="blocklist-preview">{blocklist.content}</pre>}<div className="recheck-row"><span><RefreshCw size={13}/> {baseline === null ? 'Capture a baseline before you re-run.' : `Baseline ${baseline} PII flows · current ${leakedCount} · ${Math.max(0, baseline - leakedCount)} fewer`}</span><button className="btn primary compact" onClick={() => { if (baseline === null) setBaseline(leakedCount); send({ type: 'start', device: 'laptop' }); notify('Capture restarted. Apply the copied rules on the audited device before comparing results.'); }}><Activity size={13}/> Re-run capture</button></div></section>
    </div><aside className="legal-side"><section className="section-panel evidence-pack"><PanelHeading title="Evidence pack" sub="Hash-chained capture log"/><div className="evidence-seal"><div><FileCheck2 size={21}/></div><span><b>{evidence?.sha256 ? 'Evidence sealed' : 'Capture evidence'}</b><small>{evidence?.sha256 ? 'Agent returned a SHA-256 chain hash.' : 'Request an export from the local agent.'}</small></span></div>{evidence?.path && <div className="hash-box"><span>AGENT FILE PATH</span><code>{evidence.path}</code></div>}{evidence?.sha256 && <div className="hash-box"><span>SHA-256</span><code>{evidence.sha256}</code></div>}<div className="pack-meta"><span>Flows included</span><b>{allFlows.length}</b><span>PII signals</span><b>{leakedCount}</b><span>Current score</span><b>{score?.total ? Math.round(score.total) : '—'}</b></div><button className="btn primary full-btn" onClick={() => send(OUTBOUND.exportEvidence())}><Download size={14}/> Export evidence pack</button><p className="pack-note"><LockKeyhole size={12}/> The local agent creates the file and returns its path and hash.</p></section>
      <section className="section-panel complaint-panel"><PanelHeading title="Message draft" sub="Editable template · review details before sending"/><div className="draft-toolbar"><span><FileText size={12}/> INFORMATION REQUEST</span><button onClick={exportDraft}><ArrowDownToLine size={12}/> Download</button></div><textarea value={complaint} onChange={(event) => setComplaint(event.target.value)} aria-label="Editable information request draft"/><div className="draft-footer"><span>Check facts, dates, recipient, and local requirements.</span><button className="btn secondary compact" onClick={exportDraft}><Download size={12}/> Export draft</button></div></section>
    </aside></div>
    <div className="legal-disclaimer"><Info size={13}/><span><b>Decision support, not a legal determination.</b> Treat model output as informational: check linked sources and context, compare suggested actions and their trade-offs, and seek qualified advice before formal or high-impact steps. No action is required based on a finding alone.</span></div>
  </div>;
}

function VerdictCard({ verdict, flow, compact = false }) {
  const [expanded, setExpanded] = useState(!compact);
  const status = verdict.status || 'questionable';
  const citationList = verdict.citations || [];
  const statusLabel = { violation: 'POTENTIAL CONCERN', questionable: 'NEEDS REVIEW', compliant: 'NO ISSUE FLAGGED' }[status] || 'NEEDS REVIEW';
  return <article className={`verdict-card ${status} ${compact ? 'compact-verdict' : ''}`}><button className="verdict-card-head" onClick={() => compact && setExpanded(!expanded)}><span className={`verdict-symbol ${status}`}>{status === 'violation' ? <ShieldAlert size={15}/> : status === 'questionable' ? <AlertTriangle size={15}/> : <BadgeCheck size={15}/>}</span><span className={`verdict-label ${status}`}>{statusLabel}</span>{flow && <span className="verdict-flow-meta"><code>{flow.host}</code> · signal score {Math.round(flow.severity)}</span>}<ChevronDown size={14} className={expanded ? 'rotate' : ''}/></button>{expanded && <div className="verdict-body"><p>{verdict.reasoning}</p>{citationList.length ? <><div className="source-caption">References returned by the analysis agent. Check that each source supports this finding.</div><div className="citations">{citationList.map((citation, index) => <a key={`${citation.url}-${index}`} href={citation.url} target="_blank" rel="noreferrer"><BookOpenCheck size={12}/><span><b>{citation.source}</b><small>{citation.section}</small></span><ExternalLink size={11}/></a>)}</div></> : <div className="not-covered"><Info size={12}/> No supporting reference was returned. Treat this finding as unverified.</div>}</div>}</article>;
}

function FootprintPage({ notify }) {
  const [email, setEmail] = useState('');
  const [scanState, setScanState] = useState('idle');
  const [scanResult, setScanResult] = useState(null);
  const [zipFile, setZipFile] = useState(null);
  const [showBoundary, setShowBoundary] = useState(false);
  const scan = async (event) => {
    event.preventDefault();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { setScanState('error'); setScanResult('Enter a valid email address.'); return; }
    setScanState('loading'); setScanResult(null);
    try { const response = await fetch('/api/hibp', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email }) }); const result = await response.json(); if (!response.ok) throw new Error(result.error || 'Breach proxy is unavailable.'); setScanResult(result); setScanState('done'); }
    catch (error) { setScanResult(error.message || 'The breach scan proxy is not configured yet.'); setScanState('error'); }
  };
  return <div className="page-wrap"><PageHeading kicker="SUPPORTING MODULE · P2" title="Stored Footprint" description="Review what services already know about you, then compare it with live signals." actions={<button className="btn secondary" onClick={() => setShowBoundary(!showBoundary)}><ShieldCheck size={14}/> Data boundary</button>}/>
    {showBoundary && <div className="boundary-card"><ShieldCheck size={17}/><div><b>Be precise about what leaves this device.</b><p>OAuth uses provider consent. A breach scan sends your email to GhostPrint’s HIBP proxy. Google Takeout ZIP review stays in the browser. This interface does not claim zero network activity.</p></div></div>}
    <section className="footprint-score-strip"><div className="footprint-icon"><Database size={19}/></div><div><b>Stored and live signals feed the same exposure picture.</b><p>This module is secondary to Live Leak Radar. Connect only accounts you own and review each provider’s requested scopes.</p></div><div className="footprint-count"><span>CONNECTED SOURCES</span><b>0 <small>/ 4</small></b></div></section>
    <section className="section-panel providers-panel"><PanelHeading title="Connect a service" sub="OAuth connects pull account data with your consent. Tokens should stay in session memory."/><div className="provider-grid">{[{ name: 'GitHub', detail: 'Repositories, profile, and public activity', icon: Github, tag: 'LOW FRICTION' }, { name: 'Reddit', detail: 'Profile and public contribution history', icon: CircleHelp, tag: 'LOW FRICTION' }, { name: 'Spotify', detail: 'Listening history and saved library', icon: Activity, tag: 'DEMO CONNECTOR' }, { name: 'Google', detail: 'Limited account data · testing-mode users only', icon: Hexagon, tag: 'LIGHT SCOPES' }].map(({ name, detail, icon: Icon, tag }) => <div className="provider-card" key={name}><div className={`provider-icon ${name.toLowerCase()}`}><Icon size={19}/></div><div className="provider-body"><div className="provider-title"><b>{name}</b><span>{tag}</span></div><p>{detail}</p></div><button className="btn secondary compact" onClick={() => notify(`${name} OAuth route is not configured yet. No data was sent.`)}>Connect <ArrowRight size={12}/></button></div>)}</div><div className="scope-note"><KeyRound size={13}/> Provider tokens are kept in session memory only. Never paste secrets into this dashboard.</div></section>
    <div className="footprint-grid"><section className="section-panel breach-panel"><PanelHeading title="Breach scan" sub="Check a mailbox against known breach disclosures."/><form onSubmit={scan}><label className="field-label" htmlFor="breach-email">EMAIL ADDRESS</label><div className="email-input"><Mail size={14}/><input id="breach-email" type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="you@example.com"/><button className="btn primary compact" disabled={scanState === 'loading'}>{scanState === 'loading' ? <LoaderCircle className="spin" size={13}/> : <Search size={13}/>}Scan</button></div></form>{scanState === 'error' && <div className="scan-result error"><AlertTriangle size={14}/><span>{scanResult}<small>The email is sent only if /api/hibp is configured and you submit the scan.</small></span></div>}{scanState === 'done' && <div className="scan-result success"><CheckCircle2 size={14}/><span>Scan complete<small>{JSON.stringify(scanResult)}</small></span></div>}<div className="privacy-callout"><Info size={13}/> This is the one module where an identifier may reach a server. A local proxy is required; the app will show an error if it is unavailable.</div></section>
      <section className="section-panel takeout-panel"><PanelHeading title="Google Takeout" sub="Optional in-browser archive review."/><label className="takeout-drop"><input type="file" accept=".zip,application/zip" onChange={(event) => setZipFile(event.target.files?.[0] || null)}/><FileArchive size={22}/><b>{zipFile ? zipFile.name : 'Choose a Takeout ZIP'}</b><span>{zipFile ? `${formatBytes(zipFile.size)} · local file selected` : 'Location and YouTube history · processed in browser'}</span></label><p className="takeout-note"><Info size={12}/> Google Takeout has no general public API for this workflow. ZIP parsing is not connected yet; selecting a file does not upload it.</p></section></div>
    <section className="section-panel footprint-signals"><PanelHeading title="Signals from Live Radar" sub="Observed flows can be matched to stored entities once the local agent supplies those results."/><div className="signal-placeholder"><Network size={17}/><span><b>No stored-to-live matches yet</b><small>Connect a source and collect live flows to build the shadow dossier.</small></span><button className="btn secondary compact" onClick={() => notify('Open Live Leak Radar to begin a local capture.')} >Go to Live Radar <ArrowRight size={12}/></button></div></section>
  </div>;
}

function PageHeading({ kicker, title, description, actions }) { return <div className="page-heading"><div><div className="eyebrow"><span className="eyebrow-line"/>{kicker}</div><h1>{title}</h1><p>{description}</p></div>{actions && <div className="heading-actions">{actions}</div>}</div>; }
function PanelHeading({ title, sub, count }) { return <div className="section-heading"><div><h2>{title}</h2><p>{sub}</p></div>{count && <span className="section-count">{count}</span>}</div>; }
function flagEmoji(code = '') { const country = String(code).toUpperCase(); return /^[A-Z]{2}$/.test(country) ? String.fromCodePoint(...country.split('').map((char) => 127397 + char.charCodeAt())) : '◌'; }
function severityWord(score = 0) { return score >= 75 ? 'high' : score >= 40 ? 'medium' : 'low'; }
function short(label, limit) { return label.length > limit ? `${label.slice(0, limit - 1)}…` : label; }
function Modal({ title, eyebrow, onClose, children }) { return <div className="modal-backdrop" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="modal"><div className="modal-head"><div><div className="eyebrow">{eyebrow}</div><h2>{title}</h2></div><button className="icon-btn" onClick={onClose}><X size={16}/></button></div>{children}</section></div>; }

createRoot(document.getElementById('root')).render(<App/>);
