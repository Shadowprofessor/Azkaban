import React, { useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  Activity, AlertCircle, ArrowRight, ArrowUpRight,
  Bell, Check, CheckCircle2, ChevronDown, ChevronLeft, ChevronRight, CircleHelp,
  Clock3, CloudUpload, Command, File, FileCheck2, FileImage, FileText,
  FolderOpen, LayoutDashboard, ListFilter, LoaderCircle, MoreHorizontal,
  Plus, Printer, RefreshCw, Search, Settings2, ShieldCheck,
  Sparkles, Trash2, Wifi, X, Zap
} from 'lucide-react';
import './styles.css';

const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/$/, '');
const initialJobs = [
  { id: 'GP-4821', name: 'Brand identity — final set.pdf', owner: 'Priya Sharma', initials: 'PS', color: 'peach', printer: 'Studio · Epson P900', pages: 18, copies: 2, size: '24.8 MB', time: 'Just now', status: 'Printing', progress: 68, type: 'PDF' },
  { id: 'GP-4820', name: 'Q4 campaign artwork.pdf', owner: 'Aarav Mehta', initials: 'AM', color: 'lavender', printer: 'Production · HP M608', pages: 42, copies: 1, size: '8.2 MB', time: '2 min ago', status: 'Queued', progress: 0, type: 'PDF' },
  { id: 'GP-4819', name: 'Packaging dieline v3.ai', owner: 'Nisha Patel', initials: 'NP', color: 'mint', printer: 'Studio · Epson P900', pages: 6, copies: 4, size: '16.4 MB', time: '8 min ago', status: 'Ready', progress: 100, type: 'AI' },
  { id: 'GP-4818', name: 'Typography specimens.pdf', owner: 'Rohan Das', initials: 'RD', color: 'blue', printer: 'Editorial · Canon PRO-4100', pages: 12, copies: 1, size: '3.1 MB', time: '14 min ago', status: 'Ready', progress: 100, type: 'PDF' },
  { id: 'GP-4817', name: 'Spring lookbook spreads.pdf', owner: 'Maya Iyer', initials: 'MI', color: 'rose', printer: 'Production · HP M608', pages: 64, copies: 1, size: '31.6 MB', time: '25 min ago', status: 'Completed', progress: 100, type: 'PDF' },
  { id: 'GP-4816', name: 'Event signage — A2.pdf', owner: 'Kabir Rao', initials: 'KR', color: 'yellow', printer: 'Studio · Epson P900', pages: 8, copies: 3, size: '11.2 MB', time: '38 min ago', status: 'Completed', progress: 100, type: 'PDF' },
  { id: 'GP-4815', name: 'Wayfinding icons.svg', owner: 'Leah Thomas', initials: 'LT', color: 'teal', printer: 'Editorial · Canon PRO-4100', pages: 1, copies: 1, size: '820 KB', time: '52 min ago', status: 'Failed', progress: 0, type: 'SVG' },
];

const pages = [
  { label: 'Overview', icon: LayoutDashboard }, { label: 'Print jobs', icon: Printer, count: '8' },
  { label: 'Files', icon: FolderOpen }, { label: 'Activity', icon: Activity },
];
const printers = [
  { name: 'Epson SureColor P900', room: 'Design studio · Floor 2', state: 'Ready', tone: 'ready', queue: 2, color: '#7575e8' },
  { name: 'HP LaserJet M608', room: 'Production · Floor 1', state: 'Printing', tone: 'printing', queue: 4, color: '#4b8acb' },
  { name: 'Canon imagePROGRAF PRO-4100', room: 'Editorial · Floor 2', state: 'Ready', tone: 'ready', queue: 1, color: '#d28a54' },
];

function App() {
  const [jobs, setJobs] = useState(initialJobs);
  const [activePage, setActivePage] = useState('Overview');
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('All jobs');
  const [filterOpen, setFilterOpen] = useState(false);
  const [modal, setModal] = useState('');
  const [selectedJob, setSelectedJob] = useState(null);
  const [toast, setToast] = useState('');
  const [dragging, setDragging] = useState(false);
  const [page, setPage] = useState(1);
  const [apiUrl, setApiUrl] = useState(() => localStorage.getItem('ghostprint-api-url') || API_BASE);
  const [apiStatus, setApiStatus] = useState('idle');
  const [apiMessage, setApiMessage] = useState('Add the forwarded URL when your backend is running.');
  const [dark, setDark] = useState(false);
  const [notificationOpen, setNotificationOpen] = useState(false);
  const [notifications, setNotifications] = useState(3);
  const [uploading, setUploading] = useState([]);
  const fileInput = useRef(null);
  const notify = (message) => { setToast(message); window.clearTimeout(notify.timer); notify.timer = window.setTimeout(() => setToast(''), 3200); };

  const visibleJobs = useMemo(() => jobs.filter((job) => {
    const matchesSearch = `${job.name} ${job.owner} ${job.id} ${job.printer}`.toLowerCase().includes(search.toLowerCase());
    const matchesFilter = filter === 'All jobs' || job.status === filter;
    const matchesPage = activePage === 'Print jobs' ? true : activePage === 'Overview' ? true : activePage === 'Files' ? true : true;
    return matchesSearch && matchesFilter && matchesPage;
  }), [jobs, search, filter, activePage]);

  async function checkConnection(url = apiUrl) {
    const normalized = url.trim().replace(/\/$/, '');
    if (!normalized) { setApiStatus('missing'); setApiMessage('Paste the forwarded HTTPS URL from VS Code Port Forwarding.'); return; }
    try { new URL(normalized); } catch { setApiStatus('error'); setApiMessage('That URL does not look valid. Include https:// at the start.'); return; }
    setApiUrl(normalized); localStorage.setItem('ghostprint-api-url', normalized); setApiStatus('checking'); setApiMessage('Checking the backend…');
    try {
      const response = await fetch(`${normalized}/health`, { signal: AbortSignal.timeout(6500) });
      if (!response.ok) throw new Error(`Health check returned ${response.status}`);
      setApiStatus('connected'); setApiMessage('Backend is reachable through the forwarded port.'); notify('Backend connected');
    } catch {
      setApiStatus('error'); setApiMessage('Could not reach /health. Check the forwarded URL, port visibility, and backend CORS settings.');
    }
  }

  function queueFiles(files) {
    const accepted = Array.from(files || []).filter((file) => /\.(pdf|png|jpe?g|svg|ai|psd|tif?f|docx?)$/i.test(file.name));
    if (!accepted.length) { if (files?.length) notify('Choose a PDF, image, or design file to continue.'); return; }
    setUploading((existing) => [...existing, ...accepted.map((file) => ({ file, progress: 0, state: 'uploading' }))]);
    accepted.forEach((file) => {
      const ticker = window.setInterval(() => setUploading((items) => items.map((item) => {
        if (item.file !== file) return item;
        const next = Math.min(item.progress + 16 + Math.random() * 16, 100);
        return { ...item, progress: next, state: next >= 100 ? 'ready' : 'uploading' };
      })), 160);
      window.setTimeout(() => { window.clearInterval(ticker); setUploading((items) => items.map((item) => item.file === file ? { ...item, progress: 100, state: 'ready' } : item)); }, 900);
    });
    setModal('upload');
  }

  function createJob(fileItem) {
    const file = fileItem?.file;
    if (!file) return;
    const isImage = /\.(png|jpe?g|svg|tif?f)$/i.test(file.name);
    const ext = file.name.split('.').pop().toUpperCase();
    const newJob = { id: `GP-${4822 + jobs.length - initialJobs.length}`, name: file.name, owner: 'You', initials: 'YO', color: 'mint', printer: 'Studio · Epson P900', pages: 1, copies: 1, size: file.size > 1024 * 1024 ? `${(file.size / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(file.size / 1024))} KB`, time: 'Just now', status: 'Queued', progress: 0, type: isImage ? ext : ext };
    setJobs((current) => [newJob, ...current]); setUploading((items) => items.filter((item) => item.file !== file)); setActivePage('Print jobs'); setModal(''); notify('Added to the print queue');
  }

  function runAction(job, action) {
    if (action === 'Print again') setJobs((current) => [{ ...job, id: `GP-${4822 + current.length - initialJobs.length}`, status: 'Queued', progress: 0, time: 'Just now' }, ...current]);
    if (action === 'Cancel job') setJobs((current) => current.filter((item) => item.id !== job.id));
    setSelectedJob(null); notify(action === 'Cancel job' ? 'Print job cancelled' : 'Added to the print queue');
  }

  const pageTitle = activePage === 'Overview' ? 'Good morning, Priya' : activePage;
  const pageSubtitle = activePage === 'Overview' ? 'Here’s what’s happening in your print studio today.' : activePage === 'Print jobs' ? 'Manage your print queue and keep every job moving.' : activePage === 'Files' ? 'Your files, ready when you are.' : 'A running log of activity across your studio.';

  return <div className={`app ${dark ? 'dark' : ''}`}>
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><span /><span /><span /></div><span>ghostprint</span><span className="brand-beta">STUDIO</span></div>
      <div className="workspace-switch"><div className="workspace-avatar">N</div><div className="workspace-copy"><b>Northstar Studio</b><span>Workspace</span></div><ChevronDown size={15} /></div>
      <div className="nav-label">WORKSPACE</div>
      <nav>{pages.map(({ label, icon: Icon, count }) => <button key={label} className={`nav-item ${activePage === label ? 'active' : ''}`} onClick={() => setActivePage(label)}><Icon size={17} strokeWidth={1.8} /><span>{label}</span>{count && <span className="nav-count">{jobs.filter(j => j.status === 'Queued' || j.status === 'Printing').length}</span>}</button>)}</nav>
      <div className="sidebar-divider" />
      <div className="sidebar-section-title"><span>YOUR PRINTERS</span><button title="Add printer" onClick={() => { setActivePage('Settings'); setModal('printers'); }}><Plus size={15} /></button></div>
      <div className="printer-list">{printers.map((printer) => <button className="printer-row" key={printer.name} onClick={() => { setActivePage('Print jobs'); setFilter('All jobs'); }}><span className="printer-dot" style={{ '--dot': printer.color }}><Printer size={14} /></span><span className="printer-meta"><b>{printer.name.replace('Epson SureColor ', '').replace('HP LaserJet ', '').replace('Canon imagePROGRAF ', '')}</b><span>{printer.room}</span></span><span className={`printer-presence ${printer.tone}`} /></button>)}</div>
      <div className="sidebar-spacer" />
      <div className="sidebar-tip"><div className="tip-icon"><Sparkles size={15} /></div><b>Print, without the busywork.</b><p>Drop in a file and we’ll handle the rest.</p><button onClick={() => fileInput.current?.click()}>Upload a file <ArrowRight size={13} /></button><div className="tip-orb" /></div>
      <button className="profile"><div className="profile-avatar">PS</div><div className="profile-info"><b>Priya Sharma</b><span>Studio admin</span></div><MoreHorizontal size={17} /></button>
    </aside>

    <main className="main-area">
      <header className="topbar"><div className="breadcrumbs"><span>Northstar Studio</span><ChevronRight size={13} /><b>{activePage === 'Overview' ? 'Overview' : activePage}</b></div><div className="top-actions"><div className="search-wrap"><Search size={15} /><input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search anything..." /><kbd><Command size={10} /> K</kbd></div><button className="icon-button notification-button" onClick={() => { setNotificationOpen(!notificationOpen); setNotifications(0); }} title="Notifications"><Bell size={17} />{notifications > 0 && <i />}</button>{notificationOpen && <div className="notification-pop"><b>Notifications</b><button onClick={() => setNotificationOpen(false)}><X size={14} /></button><div className="notification-item"><CheckCircle2 size={15} /><span><b>Spring lookbook spreads</b> finished printing.<small>12 minutes ago</small></span></div><div className="notification-item warning"><AlertCircle size={15} /><span><b>Wayfinding icons</b> needs attention.<small>38 minutes ago</small></span></div></div>}<button className="top-avatar" title="Priya Sharma">PS</button></div></header>
      <div className="page-content">
        <section className="welcome-row"><div><div className="eyebrow"><span className="eyebrow-line" /> TUESDAY, NOVEMBER 21, 2026 <span className="weather-dot" /> ALL SYSTEMS GO</div><h1>{pageTitle}<span className="wave">✳</span></h1><p>{pageSubtitle}</p></div><div className="welcome-buttons"><button className="button button-quiet" onClick={() => { setActivePage('Print jobs'); setFilter('All jobs'); }}><Clock3 size={15} /> Job history</button><button className="button button-primary" onClick={() => fileInput.current?.click()}><Plus size={16} /> New print job</button></div></section>

        <section className="hero-card"><div className="hero-text"><div className="hero-kicker"><span className="pulse-dot" /> STUDIO STATUS <span className="hero-divider" /> LIVE</div><h2>Your studio is<br />in a good flow.</h2><p>Everything’s running smoothly. Keep the good work moving.</p><button className="hero-link" onClick={() => { setActivePage('Print jobs'); setFilter('All jobs'); }}>View print queue <ArrowRight size={14} /></button><div className="hero-foot"><span><span className="mini-dot green" />3 printers online</span><span><span className="mini-dot yellow" />1 job needs attention</span></div></div><div className="hero-art" aria-hidden="true"><div className="art-halo"/><div className="art-grid"/><div className="art-ring ring-one"/><div className="art-ring ring-two"/><div className="art-ring ring-three"/><div className="art-shadow"/><div className="paper paper-back"><i/><i/><i/><i/></div><div className="paper paper-mid"><i/><i/><i/><i/><i/></div><div className="paper paper-front"><span className="paper-tag">Nº 08</span><div className="paper-image"/><div className="paper-title">A study in<br/>beautiful things.</div><div className="paper-lines"><i/><i/><i/></div><div className="paper-seal">N<span>✳</span>S</div></div><div className="float-card print-float"><div className="float-icon"><Printer size={15}/></div><span><b>Now printing</b><small>Brand identity · Set 01</small></span><div className="float-progress"><i/></div></div><div className="float-card ready-float"><span className="ready-check"><Check size={13}/></span><span><b>Looks good.</b><small>Your next job is ready.</small></span></div><div className="sparkle spark-a">✳</div><div className="sparkle spark-b">✴</div></div><div className="hero-sticker">MADE<br/>TO MAKE<br/><span>✳</span></div></section>

        <section className="metrics-grid"><article className="metric-card"><div className="metric-top"><span>Jobs today</span><div className="metric-icon mint"><FileCheck2 size={17}/></div></div><div className="metric-main"><b>24</b><span className="metric-change positive"><ArrowUpRight size={13}/> 12%</span></div><div className="metric-note">vs. yesterday <span className="metric-bars"><i/><i/><i/><i/><i/><i/><i/><i/><i/></span></div></article><article className="metric-card"><div className="metric-top"><span>In the queue</span><div className="metric-icon lavender"><Clock3 size={17}/></div></div><div className="metric-main"><b>{jobs.filter((j) => j.status === 'Queued' || j.status === 'Printing').length.toString().padStart(2, '0')}</b><span className="metric-unit">jobs</span></div><div className="metric-note"><span className="status-live"><i/>2 printing right now</span></div></article><article className="metric-card"><div className="metric-top"><span>Paper used</span><div className="metric-icon peach"><FileText size={17}/></div></div><div className="metric-main"><b>1,284</b><span className="metric-unit">sheets</span></div><div className="metric-note">of 2,000 monthly <span className="usage-bar"><i/></span></div></article><article className="metric-card"><div className="metric-top"><span>Studio uptime</span><div className="metric-icon blue"><Zap size={17}/></div></div><div className="metric-main"><b>99.8</b><span className="metric-unit">%</span><span className="metric-change positive"><Check size={12}/> Great</span></div><div className="metric-note">Last 30 days</div></article></section>

        <section className="content-grid"><div className="jobs-panel panel"><div className="panel-header"><div><h3>{activePage === 'Files' ? 'Recent files' : activePage === 'Activity' ? 'Recent activity' : 'Recent print jobs'}</h3><p>A little progress, at a glance.</p></div><div className="panel-tools"><div className="filter-anchor"><button className={`filter-button ${filter !== 'All jobs' ? 'filter-active' : ''}`} onClick={() => setFilterOpen(!filterOpen)}><ListFilter size={14}/>{filter === 'All jobs' ? 'Filter' : filter}<ChevronDown size={13}/></button>{filterOpen && <div className="filter-menu">{['All jobs', 'Printing', 'Queued', 'Ready', 'Completed', 'Failed'].map((option) => <button key={option} onClick={() => { setFilter(option); setFilterOpen(false); }} className={filter === option ? 'selected' : ''}>{option}{filter === option && <Check size={13}/>}</button>)}</div>}</div><button className="button button-primary button-small" onClick={() => fileInput.current?.click()}><Plus size={14}/> New job</button></div></div>
          <div className="table-wrap"><table><thead><tr><th>FILE NAME</th><th>STATUS</th><th>PRINTER</th><th>OWNER</th><th>SUBMITTED</th><th></th></tr></thead><tbody>{visibleJobs.slice(0, 5).map((job) => <tr key={job.id} onClick={() => setSelectedJob(job)} className="job-row"><td><div className="file-cell"><div className={`file-icon ${job.type === 'AI' || job.type === 'SVG' ? 'file-image' : ''}`}>{job.type === 'AI' || job.type === 'SVG' ? <FileImage size={16}/> : <FileText size={16}/>}</div><div><b>{job.name}</b><span>{job.id} <i/> {job.pages} pages <i/> {job.size}</span></div></div></td><td><StatusBadge status={job.status} progress={job.progress}/></td><td><span className="printer-cell"><Printer size={13}/>{job.printer.split(' · ')[1]}</span></td><td><div className="owner-cell"><div className={`owner-avatar ${job.color}`}>{job.initials}</div><span>{job.owner}</span></div></td><td className="time-cell">{job.time}</td><td><button className="row-more" title="Job options" onClick={(e) => { e.stopPropagation(); setSelectedJob(job); }}><MoreHorizontal size={16}/></button></td></tr>)}</tbody></table>{visibleJobs.length === 0 && <div className="empty-state"><Search size={21}/><b>No jobs found</b><span>Try another search or filter.</span></div>}</div>
          <div className="panel-footer"><span>Showing <b>{Math.min(5, visibleJobs.length)}</b> of <b>{visibleJobs.length}</b> jobs</span><div className="pagination"><button disabled={page === 1} onClick={() => setPage(1)}><ChevronLeft size={14}/></button><button className="page-current">{page}</button><button onClick={() => setPage(page === 1 ? 2 : 1)}>{page === 1 ? '2' : '1'}</button><span>...</span><button onClick={() => setPage(4)}>4</button><button disabled={page === 4} onClick={() => setPage(Math.min(4, page + 1))}><ChevronRight size={14}/></button></div></div>
        </div>
        <aside className="right-column"><div className="printer-panel panel"><div className="side-panel-header"><div><h3>Studio printers</h3><p>3 devices · all connected</p></div><button className="icon-button small-icon" onClick={() => setModal('printers')} title="Printer settings"><Settings2 size={16}/></button></div><div className="printer-cards">{printers.map((printer, index) => <button className="device-card" key={printer.name} onClick={() => { setActivePage('Print jobs'); notify(`${printer.name} is ${printer.state.toLowerCase()}`); }}><div className="device-head"><div className="device-icon" style={{ '--device': printer.color }}><Printer size={16}/></div><span className={`device-status ${printer.tone}`}><i/>{printer.state}</span></div><b>{printer.name}</b><span className="device-room">{printer.room}</span><div className="device-bottom"><span><LayersIcon/> {printer.queue} jobs in queue</span><ArrowUpRight size={13}/></div>{index === 1 && <div className="device-progress"><i/></div>}</button>)}</div><button className="manage-link" onClick={() => setModal('printers')}>Manage printers <ArrowRight size={13}/></button></div>
          <div className="quick-panel panel"><div className="quick-heading"><div className="quick-spark"><Sparkles size={15}/></div><div><h3>Quick tip</h3><span>YOUR DAILY PRINT WISDOM</span></div><button onClick={() => notify('Tip saved for later')} title="Save tip"><ArrowUpRight size={15}/></button></div><p>Need a quick reprint? Open any completed job and hit <b>Print again</b> — your settings are already saved.</p><button className="tip-action" onClick={() => { const done = jobs.find(j => j.status === 'Completed'); if (done) { setSelectedJob(done); } else notify('No completed jobs yet.'); }}>Give it a try <ArrowRight size={13}/></button><div className="tip-decor">✳</div></div></aside></section>

        <footer className="footer"><span>© 2026 GhostPrint Studio <i/> Made with intention, for the people who make.</span><div><button onClick={() => setModal('help')}><CircleHelp size={13}/> Help center</button><button onClick={() => setModal('connection')}><span className={`connection-dot ${apiStatus === 'connected' ? 'connected' : apiStatus === 'error' ? 'error' : ''}`}/>{apiStatus === 'connected' ? 'Backend connected' : 'Connect backend'}</button><button onClick={() => setDark(!dark)}><span className="theme-icon">◐</span> {dark ? 'Light mode' : 'Appearance'}</button></div></footer>
      </div>
    </main>

    {modal === 'connection' && <Modal title="Connect your backend" eyebrow="SERVER CONNECTION" onClose={() => setModal('')}><div className="connection-intro"><div className={`connection-illustration ${apiStatus}`}><Wifi size={21}/></div><div><b>Run the server anywhere.</b><p>Paste its VS Code forwarded port URL and GhostPrint will connect from this browser.</p></div></div><label className="field-label" htmlFor="api-url">Forwarded backend URL</label><div className="url-input"><span>↗</span><input id="api-url" value={apiUrl} onChange={(e) => { setApiUrl(e.target.value); setApiStatus('idle'); }} placeholder="https://your-server-8000.app.github.dev" autoFocus/></div><div className="connection-hint"><ShieldCheck size={14}/><span>Use the HTTPS link shown under <b>Ports</b> in VS Code. The URL is saved in this browser.</span></div>{apiMessage && <div className={`connection-message ${apiStatus}`}><span>{apiStatus === 'connected' ? <CheckCircle2 size={15}/> : apiStatus === 'checking' ? <LoaderCircle size={15} className="spin"/> : apiStatus === 'error' || apiStatus === 'missing' ? <AlertCircle size={15}/> : <CircleHelp size={15}/>}</span>{apiMessage}</div>}<div className="modal-actions"><button className="button button-quiet" onClick={() => setModal('')}>Close</button><button className="button button-primary" onClick={() => checkConnection()} disabled={apiStatus === 'checking'}>{apiStatus === 'checking' ? <LoaderCircle size={15} className="spin"/> : <Wifi size={15}/>} Check connection</button></div></Modal>}

    {modal === 'upload' && <Modal title="Ready to print" eyebrow="NEW PRINT JOB" onClose={() => setModal('')}><div className="upload-list">{uploading.map((item) => <div className="upload-file" key={`${item.file.name}-${item.file.lastModified}`}><div className="file-icon"><FileText size={16}/></div><div className="upload-file-info"><b>{item.file.name}</b><span>{item.file.size > 1024 * 1024 ? `${(item.file.size / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(item.file.size / 1024))} KB`}</span><div className="upload-progress"><i style={{ width: `${item.progress}%` }}/></div></div>{item.state === 'ready' ? <CheckCircle2 className="upload-done" size={18}/> : <LoaderCircle className="spin upload-spin" size={17}/>}</div>)}</div><div className="setting-row"><div><b>Printer</b><span>Pick a destination printer</span></div><select defaultValue="Studio · Epson P900"><option>Studio · Epson P900</option><option>Production · HP M608</option><option>Editorial · Canon PRO-4100</option></select></div><div className="setting-row"><div><b>Copies</b><span>One-sided · color</span></div><div className="stepper"><button onClick={(e) => e.currentTarget.nextElementSibling.value = Math.max(1, Number(e.currentTarget.nextElementSibling.value) - 1)}><span>−</span></button><input defaultValue="1" min="1" max="99" type="number"/><button onClick={(e) => e.currentTarget.previousElementSibling.value = Math.min(99, Number(e.currentTarget.previousElementSibling.value) + 1)}><Plus size={13}/></button></div></div><div className="modal-actions"><button className="button button-quiet" onClick={() => setModal('')}>Keep editing</button><button className="button button-primary" disabled={uploading.length === 0 || uploading.some((item) => item.state !== 'ready')} onClick={() => createJob(uploading.find((item) => item.state === 'ready'))}><Printer size={15}/> Add to print queue</button></div></Modal>}

    {modal === 'printers' && <Modal title="Studio printers" eyebrow="DEVICES & CONNECTIONS" onClose={() => setModal('')}><p className="modal-desc">Your studio devices and their current status.</p><div className="modal-printers">{printers.map((printer) => <div className="modal-printer" key={printer.name}><div className="device-icon" style={{ '--device': printer.color }}><Printer size={16}/></div><div><b>{printer.name}</b><span>{printer.room}</span></div><span className={`device-status ${printer.tone}`}><i/>{printer.state}</span></div>)}</div><button className="button button-connect" onClick={() => { setModal('connection'); }}><Wifi size={15}/> Configure server connection</button></Modal>}

    {modal === 'help' && <Modal title="How can we help?" eyebrow="GHOSTPRINT SUPPORT" onClose={() => setModal('')}><p className="modal-desc">A few useful places to start.</p><button className="help-link" onClick={() => { setModal('connection'); }}><span><Wifi size={16}/></span><div><b>Connect your server</b><small>Set up the VS Code forwarded URL.</small></div><ArrowRight size={15}/></button><button className="help-link" onClick={() => { setModal(''); notify('Print setup guide opened'); }}><span><Printer size={16}/></span><div><b>Print setup guide</b><small>Paper, color, sizing and more.</small></div><ArrowRight size={15}/></button><button className="help-link" onClick={() => { setModal(''); notify('Support details copied'); }}><span><CircleHelp size={16}/></span><div><b>Contact studio support</b><small>We’re happy to help you out.</small></div><ArrowRight size={15}/></button></Modal>}

    {selectedJob && <Modal title="Job details" eyebrow={selectedJob.id} onClose={() => setSelectedJob(null)}><div className="job-detail-file"><div className="file-icon"><FileText size={18}/></div><div><b>{selectedJob.name}</b><span>{selectedJob.pages} pages · {selectedJob.size}</span></div></div><div className="detail-grid"><div><span>STATUS</span><StatusBadge status={selectedJob.status} progress={selectedJob.progress}/></div><div><span>PRINTER</span><b>{selectedJob.printer}</b></div><div><span>SUBMITTED BY</span><b>{selectedJob.owner}</b></div><div><span>SUBMITTED</span><b>{selectedJob.time}</b></div></div><div className="modal-actions"><button className="button button-quiet danger" onClick={() => runAction(selectedJob, 'Cancel job')}><Trash2 size={14}/> Cancel job</button><button className="button button-primary" onClick={() => runAction(selectedJob, 'Print again')}><RefreshCw size={14}/> Print again</button></div></Modal>}

    <input ref={fileInput} className="file-input" type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.svg,.ai,.psd,.tif,.tiff,.doc,.docx" onChange={(e) => { queueFiles(e.target.files); e.target.value = ''; }}/>
    {dragging && <div className="drop-overlay" onDragLeave={() => setDragging(false)} onDrop={(e) => { e.preventDefault(); setDragging(false); queueFiles(e.dataTransfer.files); }}><div><CloudUpload size={30}/><b>Drop your files to get started.</b><span>PDFs, images and design files welcome.</span></div></div>}
    {toast && <div className="toast"><CheckCircle2 size={16}/>{toast}<button onClick={() => setToast('')}><X size={14}/></button></div>}
    <div className="drag-listener" onDragEnter={(e) => { e.preventDefault(); setDragging(true); }} onDragOver={(e) => e.preventDefault()} />
  </div>;
}

function LayersIcon() { return <span className="layers-icon"><File size={11}/></span>; }
function StatusBadge({ status, progress }) {
  const classes = { Printing: 'status-printing', Queued: 'status-queued', Ready: 'status-ready', Completed: 'status-completed', Failed: 'status-failed' };
  return <span className={`status-badge ${classes[status] || ''}`}><i/>{status}{status === 'Printing' && <span className="status-progress">{progress}%</span>}</span>;
}
function Modal({ title, eyebrow, onClose, children }) {
  return <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}><div className="modal"><div className="modal-top"><div><div className="modal-eyebrow">{eyebrow}</div><h2>{title}</h2></div><button className="modal-close" onClick={onClose} aria-label="Close"><X size={18}/></button></div>{children}</div></div>;
}

function AppRoot() {
  React.useEffect(() => {
    const onKey = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); document.querySelector('.search-wrap input')?.focus(); }
      if (e.key === 'Escape') document.querySelector('.modal-close')?.click();
    };
    const onDrag = (e) => { if (e.type === 'dragover') e.preventDefault(); };
    window.addEventListener('keydown', onKey); window.addEventListener('dragover', onDrag);
    return () => { window.removeEventListener('keydown', onKey); window.removeEventListener('dragover', onDrag); };
  }, []);
  return <App/>;
}

createRoot(document.getElementById('root')).render(<AppRoot/>);
