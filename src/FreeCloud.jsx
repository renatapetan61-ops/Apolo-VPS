import React, { useEffect, useState } from 'react';
import { Activity, CheckCircle2, Clock3, Cloud, Database, KeyRound, RefreshCw, Server, ShieldCheck, Users } from 'lucide-react';
import './free-cloud.css';

const API = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000';
const endpoint = '/api/v1';

export default function FreeCloud({ adminOnly = false }) {
  const [token, setToken] = useState('');
  const [user, setUser] = useState(null);
  const [authMode, setAuthMode] = useState('login');
  const [form, setForm] = useState({ email:'', display_name:'', password:'' });
  const [verifyToken, setVerifyToken] = useState('');
  const [bootstrapToken, setBootstrapToken] = useState('');
  const [plan, setPlan] = useState(null);
  const [term, setTerm] = useState(1);
  const [subscriptions, setSubscriptions] = useState([]);
  const [overview, setOverview] = useState(null);
  const [nodeName, setNodeName] = useState('APOLO host');
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  async function request(path, options = {}) {
    const headers = { 'Content-Type':'application/json', ...(options.headers || {}) };
    if (token) headers.Authorization = 'Bearer ' + token;
    const response = await fetch(API + endpoint + path, { ...options, headers });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'A solicitação não foi concluída.');
    return data;
  }

  async function loadAccount(currentToken = token) {
    if (!currentToken) return;
    const headers = { Authorization:'Bearer ' + currentToken };
    const [me, subs] = await Promise.all([
      fetch(API + endpoint + '/auth/me', { headers }),
      fetch(API + endpoint + '/subscriptions', { headers })
    ]);
    if (!me.ok) throw new Error('Sessão expirada. Entre novamente.');
    const meData = await me.json();
    const subData = subs.ok ? await subs.json() : { subscriptions:[] };
    setUser(meData.user);
    setSubscriptions(subData.subscriptions || []);
    if (meData.user.role === 'admin') await loadAdmin(currentToken);
  }

  async function loadAdmin(currentToken = token) {
    const response = await fetch(API + endpoint + '/admin/overview', {
      headers:{ Authorization:'Bearer ' + currentToken }
    });
    if (response.ok) setOverview(await response.json());
  }

  useEffect(() => {
    fetch(API + endpoint + '/plans').then(r => r.json()).then(data => setPlan(data.plans?.[0] || null)).catch(() => {});
  }, []);

  async function submitAuth(event) {
    event.preventDefault(); setLoading(true); setError(''); setMessage('');
    try {
      if (authMode === 'register') {
        const data = await request('/auth/register', { method:'POST', body:JSON.stringify(form) });
        setMessage(data.message || 'Cadastro enviado. Verifique seu e-mail.');
        setAuthMode('verify');
      } else if (authMode === 'verify') {
        const data = await request('/auth/verify-email', { method:'POST', body:JSON.stringify({ token:verifyToken }) });
        setMessage(data.verified ? 'E-mail confirmado. Agora entre na sua conta.' : 'Não foi possível verificar.');
        setAuthMode('login');
      } else {
        const data = await request('/auth/login', { method:'POST', body:JSON.stringify({ email:form.email, password:form.password }) });
        setToken(data.access_token);
        await loadAccount(data.access_token);
        setMessage('Sessão iniciada com sucesso.');
      }
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function subscribe() {
    setLoading(true); setError(''); setMessage('');
    try {
      const data = await request('/subscriptions', { method:'POST', body:JSON.stringify({ plan_id:plan.id, term_years:Number(term), auto_renew:true }) });
      setMessage(data.message);
      await loadAccount();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function bootstrap() {
    setLoading(true); setError(''); setMessage('');
    try {
      await request('/admin/bootstrap', { method:'POST', headers:{ 'X-Apolo-Bootstrap-Token':bootstrapToken } });
      await loadAccount();
      setMessage('Primeiro administrador configurado. Remova o token de bootstrap do servidor.');
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function createNode() {
    setLoading(true); setError(''); setMessage('');
    try {
      const data = await request('/admin/nodes', { method:'POST', body:JSON.stringify({ name:nodeName }) });
      setMessage('Nó registrado em estado pendente: ' + data.node_id);
      await loadAdmin();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function probeNode(id) {
    setLoading(true); setError(''); setMessage('');
    try {
      const data = await request('/admin/nodes/' + id + '/probe', { method:'POST' });
      setMessage('Capacidade real medida. Reservas novas: ' + data.newly_reserved + '. VPS provisionada: não.');
      await loadAdmin();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  async function reconcile() {
    setLoading(true); setError(''); setMessage('');
    try {
      const data = await request('/admin/queue/reconcile', { method:'POST' });
      setMessage('Fila processada. Novas reservas: ' + data.newly_reserved + '.');
      await loadAdmin();
    } catch (e) { setError(e.message); }
    finally { setLoading(false); }
  }

  function logout() { setToken(''); setUser(null); setOverview(null); setSubscriptions([]); setMessage('Sessão encerrada.'); }

  if (!user) return <section className="fc-wrap">
    <div className="fc-heading"><div><span className="fc-eyebrow"><Cloud size={14}/> APOLO FREE CLOUD</span><h2>{adminOnly ? 'Administração protegida' : 'Sua conta APOLO'}</h2><p>Cadastro, planos gratuitos e solicitações de VPS com capacidade verificada.</p></div></div>
    <div className="fc-auth-card">
      <div className="fc-auth-tabs">
        <button className={authMode==='login'?'selected':''} onClick={()=>setAuthMode('login')}>Entrar</button>
        <button className={authMode==='register'?'selected':''} onClick={()=>setAuthMode('register')}>Criar conta</button>
        <button className={authMode==='verify'?'selected':''} onClick={()=>setAuthMode('verify')}>Verificar e-mail</button>
      </div>
      <form onSubmit={submitAuth} className="fc-form">
        {authMode !== 'verify' && <label>E-mail<input type="email" required value={form.email} onChange={e=>setForm({...form,email:e.target.value})} autoComplete="email"/></label>}
        {authMode === 'register' && <label>Nome de exibição<input required minLength="2" maxLength="80" value={form.display_name} onChange={e=>setForm({...form,display_name:e.target.value})}/></label>}
        {authMode === 'verify' ? <label>Token recebido por e-mail<input required value={verifyToken} onChange={e=>setVerifyToken(e.target.value)} autoComplete="one-time-code"/></label> :
          <label>Senha<input type="password" required minLength={authMode==='register'?12:1} value={form.password} onChange={e=>setForm({...form,password:e.target.value})} autoComplete={authMode==='register'?'new-password':'current-password'}/></label>}
        {authMode==='register' && <p className="fc-hint">Use pelo menos 12 caracteres, com letras maiúsculas, minúsculas e números. A conta exige confirmação de e-mail.</p>}
        <button className="fc-primary" disabled={loading}>{loading?'Aguarde…':authMode==='register'?'Criar conta gratuita':authMode==='verify'?'Confirmar e-mail':'Entrar'}</button>
      </form>
    </div>
    {message && <p className="fc-message">{message}</p>}{error && <p className="fc-error">{error}</p>}
  </section>;

  return <section className="fc-wrap">
    <div className="fc-heading"><div><span className="fc-eyebrow"><Cloud size={14}/> APOLO FREE CLOUD</span><h2>{adminOnly?'Painel administrativo':'Planos e assinaturas'}</h2><p>Olá, {user.display_name}. Conta {user.role==='admin'?'administradora':'pessoal'}.</p></div><button className="fc-secondary" onClick={logout}>Sair</button></div>
    {message && <p className="fc-message">{message}</p>}{error && <p className="fc-error">{error}</p>}
    {user.role!=='admin' && <div className="fc-admin-bootstrap"><b>Primeiro acesso administrativo?</b><p>Se esta é a primeira conta verificada, informe o token de bootstrap configurado no servidor. Esta ação só funciona uma vez.</p><input type="password" placeholder="Token de bootstrap" value={bootstrapToken} onChange={e=>setBootstrapToken(e.target.value)}/><button onClick={bootstrap} disabled={loading || !bootstrapToken}>Promover minha conta a administrador</button></div>}
    {!adminOnly && <div className="fc-grid">
      <article className="fc-card fc-plan-card"><div className="fc-card-title"><Database size={18}/><span>PLANO GRATUITO</span></div><h3>{plan?.name || 'APOLO Free Linux'}</h3><p>{plan?.description}</p><div className="fc-specs"><span>1 vCPU</span><span>1 GiB RAM</span><span>20 GiB disco</span></div><label>Prazo inicial<select value={term} onChange={e=>setTerm(Number(e.target.value))}>{(plan?.terms_years||[1,2,5,10]).map(y=><option key={y} value={y}>{y} {y===1?'ano':'anos'}</option>)}</select></label><button className="fc-primary" disabled={loading || !plan} onClick={subscribe}>Solicitar plano gratuito</button><small>Renovação gratuita automática ativada por padrão. Sem cobrança.</small></article>
      <article className="fc-card"><div className="fc-card-title"><Activity size={18}/><span>MINHAS ASSINATURAS</span></div>{subscriptions.length===0?<p className="fc-muted">Você ainda não possui uma assinatura.</p>:subscriptions.map(s=><div className="fc-sub-row" key={s.id}><b>{s.plan_name}</b><span className="fc-state">{s.state}</span><small>{s.term_years} anos · renovação {s.auto_renew?'ativada':'desativada'}</small><small>{s.state==='waiting_capacity'?'Na fila aguardando capacidade real.':s.state==='capacity_reserved'?'Capacidade reservada; VPS ainda não confirmada.':s.state==='active'?'Serviço ativo.':'Verifique o estado no painel.'}</small>{['capacity_reserved','active','grace'].includes(s.state)&&<button className="fc-link" onClick={async()=>{try{await request('/subscriptions/'+s.id+'/auto-renew',{method:'PATCH',body:JSON.stringify({enabled:!s.auto_renew})});await loadAccount();}catch(e){setError(e.message);}}}>{s.auto_renew?'Desativar renovação':'Ativar renovação gratuita'}</button>}{['waiting_capacity','capacity_reserved'].includes(s.state)&&<button className="fc-link" onClick={async()=>{if(!window.confirm('Cancelar esta solicitação e liberar a reserva de capacidade?'))return;try{await request('/subscriptions/'+s.id+'/cancel',{method:'POST'});await loadAccount();setMessage('Solicitação cancelada.');}catch(e){setError(e.message);}}}>Cancelar solicitação</button>}</div>)}</article>
    </div>}
    {adminOnly && user.role!=='admin' && <div className="fc-card"><ShieldCheck/><h3>Acesso administrativo necessário</h3><p>Sua conta não tem permissão de administrador.</p></div>}
    {user.role==='admin' && <div className="fc-admin">
      <div className="fc-metrics">{Object.entries(overview?.counts||{}).map(([key,value])=><div className="fc-metric" key={key}><small>{key.replaceAll('_',' ')}</small><strong>{value}</strong></div>)}</div>
      <div className="fc-card"><div className="fc-card-title"><Server size={18}/><span>CAPACIDADE E HOSTS</span></div><div className="fc-node-create"><input value={nodeName} onChange={e=>setNodeName(e.target.value)} placeholder="Nome do host"/><button className="fc-primary" onClick={createNode} disabled={loading}>Registrar nó</button><button className="fc-secondary" onClick={reconcile} disabled={loading}><RefreshCw size={14}/> Reconciliar fila</button></div>
        {(overview?.nodes||[]).map(n=><div className="fc-node" key={n.id}><div><b>{n.name}</b><small>{n.id} · {n.state} · verificado: {n.verified?'sim':'não'}</small><small>Disponível: {n.free_vcpus-n.reserved_vcpus} vCPU · {n.free_memory_mib-n.reserved_memory_mib} MiB · {n.free_disk_gib-n.reserved_disk_gib} GiB</small></div><button className="fc-secondary" onClick={()=>probeNode(n.id)} disabled={loading}>Medir capacidade</button></div>)}
      </div>
      <div className="fc-card"><div className="fc-card-title"><Clock3 size={18}/><span>FILA DE CAPACIDADE</span></div>{(overview?.waiting_queue||[]).length===0?<p className="fc-muted">Nenhuma solicitação aguardando capacidade.</p>:(overview.waiting_queue||[]).map(q=><div className="fc-node" key={q.id}><div><b>{q.email}</b><small>{q.term_years} anos · {q.vcpus} vCPU · {q.memory_mib} MiB · {q.disk_gib} GiB</small><small>{q.id}</small></div><span className="fc-state">{q.state}</span></div>)}</div>
      <button className="fc-secondary" onClick={()=>loadAdmin()} disabled={loading}>Atualizar painel</button>
    </div>}
  </section>;
}
