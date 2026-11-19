import React, { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, ArrowDownToLine, ChevronDown, CircleHelp, Cloud, Cpu, Database, Globe2, HardDrive, KeyRound, Layers3, LifeBuoy, Menu, Network, Plus, Power, RefreshCw, Search, Server, Settings2, ShieldCheck, Sparkles, TerminalSquare, X } from 'lucide-react';
import './styles.css';

const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const nav = [{ label: 'Overview', icon: Layers3 }, { label: 'Virtual machines', icon: Server }, { label: 'Images', icon: HardDrive }, { label: 'Networks', icon: Network }];
function App() {
  const [section, setSection] = useState('Overview');
  const [instances, setInstances] = useState([]);
  const [health, setHealth] = useState({ state: 'checking', provider_ready: false });
  const [showCreate, setShowCreate] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState('');
  const [credentials, setCredentials] = useState(null);
  const [controlToken, setControlToken] = useState('');
  const [form, setForm] = useState({ computer_name: '', username: '', os: 'ubuntu-24.04', location: 'auto', plan: 'standard-2' });

  async function refresh() {
    try {
      const [h, v] = await Promise.all([fetch(API + '/api/v1/health'), fetch(API + '/api/v1/instances')]);
      if (h.ok) setHealth(await h.json());
      if (v.ok) setInstances((await v.json()).instances || []);
      else setInstances([]);
    } catch { setHealth({ state: 'offline', provider_ready: false }); }
  }
  useEffect(() => { refresh(); }, []);
  async function createInstance(e) {
    e.preventDefault(); setLoading(true); setNotice('');
    try {
      const res = await fetch(API + '/api/v1/instances', { method: 'POST', headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + controlToken }, body: JSON.stringify(form) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Provisioning is not available.');
      setCredentials(data.credentials || null);
      setNotice(data.message || 'VPS created successfully.');
      setShowCreate(false); refresh();
    } catch (err) { setNotice(err.message); }
    finally { setLoading(false); }
  }
  const count = instances.length;
  return <div className="shell">
    <aside className={mobileNav ? 'sidebar open' : 'sidebar'}>
      <div className="brand"><div className="brand-mark">Α</div><div><b>APOLO<span> VPS</span></b><small>GREEK CLOUD SYSTEMS</small></div><button className="icon-btn close-nav" onClick={() => setMobileNav(false)}><X size={18}/></button></div>
      <div className="workspace"><div className="workspace-icon"><Cloud size={17}/></div><div><b>Personal workspace</b><small>Infrastructure</small></div><ChevronDown size={15}/></div>
      <div className="nav-label">WORKSPACE</div>
      {nav.map(n => <button key={n.label} className={'nav-item ' + (section === n.label ? 'active' : '')} onClick={() => { setSection(n.label); setMobileNav(false); }}><n.icon size={18}/>{n.label}{n.label === 'Virtual machines' && <span className="nav-count">{count}</span>}</button>)}
      <div className="nav-label second">MANAGEMENT</div>
      <button className="nav-item" onClick={() => setNotice('Network management will be enabled after a network provider is configured.')}><Globe2 size={18}/> IP addresses</button>
      <button className="nav-item" onClick={() => setNotice('Security settings are being prepared.')}><ShieldCheck size={18}/> Security</button>
      <button className="nav-item" onClick={() => setNotice('Settings are being prepared.')}><Settings2 size={18}/> Settings</button>
      <div className="sidebar-bottom"><div className="help-card"><div className="help-icon"><LifeBuoy size={17}/></div><b>Need a hand?</b><p>Explore the infrastructure guide and setup requirements.</p><a href="https://github.com/renatapetan61-ops/Apolo-VPS" target="_blank" rel="noreferrer">Read documentation ↗</a></div><div className="profile"><div className="avatar">A</div><div><b>APOLO Admin</b><small>Owner workspace</small></div><ChevronDown size={15}/></div></div>
    </aside>
    {mobileNav && <div className="scrim" onClick={() => setMobileNav(false)}/>}
    <main className="main">
      <header className="topbar"><button className="icon-btn menu-btn" onClick={() => setMobileNav(true)}><Menu/></button><div className="crumb">Workspace <span>/</span> <b>{section}</b></div><div className="top-actions"><div className={'connection ' + (health.state === 'ok' ? 'connected' : '')}><i/>{health.state === 'ok' ? 'API connected' : health.state === 'offline' ? 'API offline' : 'Checking API'}</div><button className="icon-btn" title="Help"><CircleHelp size={18}/></button><div className="avatar small-avatar">A</div></div></header>
      <div className="content">
        <div className="welcome-row"><div><div className="eyebrow"><Sparkles size={13}/> THE CLOUD, REFINED</div><h1>{section === 'Overview' ? 'Your infrastructure,' : section}<em> elevated.</em></h1><p className="subtitle">A clear view of your compute, network and virtual machines.</p></div><button className="gold-button" onClick={() => setShowCreate(true)}><Plus size={17}/> Create VPS</button></div>
        {notice && <div className="notice"><span>{notice}</span><button onClick={() => setNotice('')}><X size={16}/></button></div>}
        <section className="hero"><div className="hero-pattern">Ω</div><div className="hero-copy"><div className="hero-kicker"><span/> APOLO CLOUD CONTROL PLANE</div><h2>Built on precision.<br/><i>Designed for possibility.</i></h2><p>Manage your virtual infrastructure with clarity, control and confidence.</p><button className="hero-link" onClick={() => setNotice('Connect a KVM/libvirt host and configure storage and public networking to enable real VPS provisioning.')}>Explore infrastructure requirements <span>↗</span></button></div><div className="hero-seal"><div className="seal-ring"><span>Α</span><small>APOLO<br/>VPS</small></div></div></section>
        <div className="section-heading"><div><h3>Infrastructure overview</h3><p>Your resources at a glance</p></div><button className="subtle-button" onClick={refresh}><RefreshCw size={14}/> Refresh</button></div>
        <div className="stats-grid"><Stat icon={Server} label="Virtual machines" value={String(count).padStart(2,'0')} detail="Confirmed instances" /><Stat icon={Cpu} label="vCPU allocated" value="—" detail="Awaiting hypervisor" /><Stat icon={Database} label="Memory allocated" value="—" detail="Awaiting hypervisor" /><Stat icon={Activity} label="Provider status" value={health.provider_ready ? 'Ready' : 'Setup'} detail={health.provider_ready ? 'Provisioner available' : 'Hypervisor not connected'} status={!health.provider_ready}/></div>
        <section className="instances-panel"><div className="panel-head"><div><h3>Virtual machines</h3><p>Manage and monitor your compute instances</p></div><button className="outline-button" onClick={() => setShowCreate(true)}><Plus size={15}/> New instance</button></div>
          {instances.length === 0 ? <div className="empty-state"><div className="empty-illustration"><Server size={27}/><span>+</span></div><h4>Your cloud starts here</h4><p>No virtual machines have been provisioned yet. Connect a hypervisor to create your first real VPS.</p><button className="gold-button" onClick={() => setShowCreate(true)}><Plus size={16}/> Create your first VPS</button></div> : <div className="table-wrap"><table><thead><tr><th>INSTANCE</th><th>LOCATION</th><th>OPERATING SYSTEM</th><th>STATUS</th></tr></thead><tbody>{instances.map(vm => <tr key={vm.id}><td><b>{vm.name || vm.computer_name}</b><small>{vm.id}</small></td><td>{vm.location || '—'}</td><td>{vm.os || '—'}</td><td><span className="status-pill">{vm.libvirt_state === 1 ? 'Running' : vm.state || 'Unknown'}</span></td></tr>)}</tbody></table></div>}
        </section>
        <div className="bottom-grid"><div className="info-card"><div className="info-icon"><TerminalSquare/></div><div><b>Built for real infrastructure</b><p>APOLO VPS only reports resources confirmed by its connected hypervisor. No simulated IP addresses or virtual machines.</p><a href="https://github.com/renatapetan61-ops/Apolo-VPS" target="_blank" rel="noreferrer">View project on GitHub ↗</a></div></div><div className="provider-card"><div className="provider-top"><span>PROVISIONING PROVIDER</span><span className="provider-dot"/></div><h4>{health.provider_ready ? 'Provider ready' : 'Awaiting host connection'}</h4><p>{health.provider_ready ? 'The control plane can communicate with its configured provider.' : 'KVM / QEMU · libvirt · cloud-init'}</p><button onClick={() => setNotice('Host-agent integration is the next implementation milestone.')}>Provider setup <span>→</span></button></div></div>
        <footer>© 2026 APOLO VPS <span>GREEK GOLD INFRASTRUCTURE</span><span>CONTROL WITH PURPOSE.</span></footer>
      </div>
    </main>
    {credentials && <div className="modal-backdrop"><div className="modal"><div className="modal-head"><div><div className="eyebrow">VPS CREATED</div><h2>Save your credentials</h2><p>This password is displayed only once.</p></div><button className="icon-btn" onClick={() => setCredentials(null)}><X/></button></div><label>Username<input readOnly value={credentials.username}/></label><label>Password<input readOnly value={credentials.password}/></label><button className="gold-button submit-button" onClick={() => { navigator.clipboard?.writeText('Username: ' + credentials.username + '\nPassword: ' + credentials.password); setCredentials(null); }}>Copy credentials and close</button><small className="form-foot">Store this password in a secure password manager.</small></div></div>}
    {showCreate && <div className="modal-backdrop" onMouseDown={e => e.target === e.currentTarget && setShowCreate(false)}><form className="modal" onSubmit={createInstance}><div className="modal-head"><div><div className="eyebrow">NEW COMPUTE INSTANCE</div><h2>Create a VPS</h2><p>Configure the identity and operating system for your server.</p></div><button type="button" className="icon-btn" onClick={() => setShowCreate(false)}><X/></button></div><label>APOLO control token<input required type="password" autoComplete="off" placeholder="Admin token from API configuration" value={controlToken} onChange={e => setControlToken(e.target.value)}/></label><label>Computer name<input required minLength="3" maxLength="63" placeholder="e.g. APOLO-WEB-01" value={form.computer_name} onChange={e => setForm({...form, computer_name:e.target.value})}/></label><label>Username<input required minLength="3" maxLength="32" placeholder="e.g. apolo-admin" value={form.username} onChange={e => setForm({...form, username:e.target.value})}/></label><label>Operating system<select value={form.os} onChange={e => setForm({...form,os:e.target.value})}><option value="ubuntu-24.04">Ubuntu Server 24.04 LTS</option><option value="debian-12">Debian 12</option><option value="rocky-9">Rocky Linux 9</option><option value="windows-server-2022" disabled>Windows Server 2022 (preparation pending)</option></select></label><label>Location<select value={form.location} onChange={e => setForm({...form,location:e.target.value})}><option value="auto">Automatic (provider decides)</option><option value="sa-east">South America</option><option value="us-east">United States — East</option><option value="eu-west">Europe — West</option></select></label><div className="secure-note"><KeyRound size={16}/><span>A real Linux VM is created on the connected KVM host. Its password is generated once and shown only after successful creation.</span></div><button className="gold-button submit-button" disabled={loading}>{loading ? 'Submitting…' : 'Request VPS provisioning'} <Plus size={16}/></button><small className="form-foot">Only a VM confirmed by libvirt is registered in this panel.</small></form></div>}
  </div>;
}
function Stat({icon:Icon,label,value,detail,status}) { return <div className="stat-card"><div className="stat-top"><span>{label}</span><Icon size={17}/></div><strong className={status?'muted-value':''}>{value}</strong><small>{detail}</small></div> }
createRoot(document.getElementById('root')).render(<App/>);