from __future__ import annotations
import base64, hashlib, hmac, json, os, secrets, smtplib, sqlite3, uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any
import httpx
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

router = APIRouter()
ROUNDS = 310_000

def now(): return datetime.now(timezone.utc)
def stamp(value=None): return (value or now()).astimezone(timezone.utc).isoformat()
def connect():
    db=sqlite3.connect(os.getenv("APOLO_STATE_DB","apolo-vps-state.sqlite3"),timeout=20)
    db.row_factory=sqlite3.Row
    db.execute("PRAGMA busy_timeout=20000")
    db.execute("PRAGMA foreign_keys=ON")
    return db
def b64(value): return base64.urlsafe_b64encode(value).rstrip(b"=").decode()
def unb64(value): return base64.urlsafe_b64decode(value+"="*(-len(value)%4))
def secret():
    value=os.getenv("APOLO_AUTH_SECRET","")
    if len(value)<32: raise HTTPException(503,"Configure APOLO_AUTH_SECRET com pelo menos 32 caracteres aleatórios.")
    return value.encode()
def password_hash(password):
    salt=secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac("sha256",password.encode(),salt,ROUNDS)
    return "pbkdf2_sha256"+"$"+str(ROUNDS)+"$"+b64(salt)+"$"+b64(digest)
def password_valid(password,encoded):
    try:
        algorithm,rounds,salt,expected=encoded.split("$",3)
        if algorithm!="pbkdf2_sha256": return False
        actual=hashlib.pbkdf2_hmac("sha256",password.encode(),unb64(salt),int(rounds))
        return hmac.compare_digest(actual,unb64(expected))
    except (ValueError,TypeError): return False
def issue_token(user):
    body=b64(json.dumps({"sub":user["id"],"iat":int(now().timestamp()),"exp":int((now()+timedelta(hours=12)).timestamp())},separators=(",",":")).encode())
    sig=b64(hmac.new(secret(),body.encode(),hashlib.sha256).digest())
    return body+"."+sig
def claims_for(token):
    try:
        body,sig=token.split(".",1)
        expected=b64(hmac.new(secret(),body.encode(),hashlib.sha256).digest())
        if not hmac.compare_digest(sig,expected): raise ValueError("signature")
        claims=json.loads(unb64(body))
        if int(claims["exp"])<=int(now().timestamp()): raise ValueError("expired")
        return claims
    except Exception as exc: raise HTTPException(401,"Sessão inválida ou expirada.") from exc

def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE NOT NULL,display_name TEXT NOT NULL,password_hash TEXT NOT NULL,role TEXT NOT NULL DEFAULT 'user',state TEXT NOT NULL DEFAULT 'pending_verification',verify_hash TEXT,verify_expires TEXT,created_at TEXT NOT NULL,verified_at TEXT);
        CREATE TABLE IF NOT EXISTS free_plans(id TEXT PRIMARY KEY,name TEXT NOT NULL,description TEXT NOT NULL,vcpus INTEGER NOT NULL,memory_mib INTEGER NOT NULL,disk_gib INTEGER NOT NULL,terms_json TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS capacity_nodes(id TEXT PRIMARY KEY,name TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'pending_verification',verified INTEGER NOT NULL DEFAULT 0,free_vcpus INTEGER NOT NULL DEFAULT 0,free_memory_mib INTEGER NOT NULL DEFAULT 0,free_disk_gib INTEGER NOT NULL DEFAULT 0,reserved_vcpus INTEGER NOT NULL DEFAULT 0,reserved_memory_mib INTEGER NOT NULL DEFAULT 0,reserved_disk_gib INTEGER NOT NULL DEFAULT 0,last_probe TEXT,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS subscriptions(id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),plan_id TEXT NOT NULL REFERENCES free_plans(id),term_years INTEGER NOT NULL,state TEXT NOT NULL,auto_renew INTEGER NOT NULL DEFAULT 1,starts_at TEXT,renews_at TEXT,node_id TEXT REFERENCES capacity_nodes(id),instance_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS provisioning_queue(id TEXT PRIMARY KEY,subscription_id TEXT NOT NULL UNIQUE REFERENCES subscriptions(id),user_id TEXT NOT NULL REFERENCES users(id),vcpus INTEGER NOT NULL,memory_mib INTEGER NOT NULL,disk_gib INTEGER NOT NULL,state TEXT NOT NULL DEFAULT 'waiting_capacity',node_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,last_error TEXT);
        CREATE TABLE IF NOT EXISTS renewal_events(id TEXT PRIMARY KEY,subscription_id TEXT NOT NULL REFERENCES subscriptions(id),scheduled_for TEXT NOT NULL,outcome TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(subscription_id,scheduled_for));
        CREATE TABLE IF NOT EXISTS audit_events(id TEXT PRIMARY KEY,actor_id TEXT,action TEXT NOT NULL,target_id TEXT,details_json TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_queue_state ON provisioning_queue(state,created_at);
        CREATE INDEX IF NOT EXISTS idx_renewals_due ON subscriptions(state,auto_renew,renews_at);
        """)
        db.execute("""INSERT OR IGNORE INTO free_plans(id,name,description,vcpus,memory_mib,disk_gib,terms_json,enabled)
          VALUES('free-linux','APOLO Free Linux','Plano gratuito sujeito à capacidade real disponível e às regras de uso.',1,1024,20,'[1,2,5,10]',1)""")
def audit(db,actor,action,target,details=None):
    db.execute("INSERT INTO audit_events VALUES(?,?,?,?,?,?)",("evt-"+uuid.uuid4().hex,actor,action,target,json.dumps(details or {},separators=(",",":")),stamp()))
def current_user(authorization: str|None=Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Autenticação Bearer obrigatória.")
    claims=claims_for(authorization[7:].strip()); init_db()
    with connect() as db: row=db.execute("SELECT id,email,display_name,role,state,created_at FROM users WHERE id=?",(claims["sub"],)).fetchone()
    if not row or row["state"]!="active": raise HTTPException(401,"Conta não verificada, suspensa ou inexistente.")
    return dict(row)
def admin_user(user=Depends(current_user)):
    if user["role"]!="admin": raise HTTPException(403,"Acesso restrito à administração.")
    return user

class Register(BaseModel):
    email:str=Field(min_length=5,max_length=254)
    display_name:str=Field(min_length=2,max_length=80)
    password:str=Field(min_length=12,max_length=128)
    @field_validator("email")
    @classmethod
    def valid_email(cls,v):
        v=v.strip().lower()
        if v.count("@")!=1 or "." not in v.rsplit("@",1)[-1] or any(c.isspace() for c in v): raise ValueError("Informe um e-mail válido.")
        return v
    @field_validator("password")
    @classmethod
    def strong_password(cls,v):
        if not(any(c.islower() for c in v) and any(c.isupper() for c in v) and any(c.isdigit() for c in v)): raise ValueError("Use letras maiúsculas, minúsculas e números.")
        return v
class Login(BaseModel):
    email:str
    password:str=Field(min_length=1,max_length=128)
class ResendVerification(BaseModel):
    email: str = Field(min_length=5, max_length=254)
class Verify(BaseModel): token:str=Field(min_length=32,max_length=512)
class Subscribe(BaseModel):
    plan_id:str="free-linux"
    term_years:int=Field(ge=1,le=10)
    auto_renew:bool=True
class NodeCreate(BaseModel): name:str=Field(min_length=3,max_length=80)
class AutoRenew(BaseModel): enabled:bool

def send_verification(email,display_name,token):
    host=os.getenv("APOLO_EMAIL_SMTP_HOST",""); username=os.getenv("APOLO_EMAIL_SMTP_USER","")
    password=os.getenv("APOLO_EMAIL_SMTP_PASSWORD",""); sender=os.getenv("APOLO_EMAIL_FROM","")
    if not all((host,username,password,sender)): raise HTTPException(503,"SMTP não configurado. Cadastro pendente; configure o e-mail para verificar a conta.")
    msg=EmailMessage(); msg["Subject"]="Confirme seu APOLO Free Cloud"; msg["From"]=sender; msg["To"]=email
    msg.set_content("Olá, {}.\\n\\nToken de verificação (válido por 30 minutos):\\n{}\\n".format(display_name,token))
    port=int(os.getenv("APOLO_EMAIL_SMTP_PORT","587"))
    try:
        if port==465:
            with smtplib.SMTP_SSL(host,port,timeout=15) as smtp: smtp.login(username,password); smtp.send_message(msg)
        else:
            with smtplib.SMTP(host,port,timeout=15) as smtp: smtp.starttls(); smtp.login(username,password); smtp.send_message(msg)
    except (OSError,smtplib.SMTPException,ValueError) as exc: raise HTTPException(503,"Falha no envio do e-mail de verificação.") from exc

def allocate_waiting(db):
    count=0
    for q in db.execute("SELECT * FROM provisioning_queue WHERE state='waiting_capacity' ORDER BY created_at").fetchall():
        node=db.execute("""SELECT * FROM capacity_nodes WHERE state='healthy' AND verified=1
          AND free_vcpus-reserved_vcpus>=? AND free_memory_mib-reserved_memory_mib>=?
          AND free_disk_gib-reserved_disk_gib>=? ORDER BY created_at LIMIT 1""",(q["vcpus"],q["memory_mib"],q["disk_gib"])).fetchone()
        if not node: continue
        db.execute("UPDATE capacity_nodes SET reserved_vcpus=reserved_vcpus+?,reserved_memory_mib=reserved_memory_mib+?,reserved_disk_gib=reserved_disk_gib+? WHERE id=?",(q["vcpus"],q["memory_mib"],q["disk_gib"],node["id"]))
        db.execute("UPDATE provisioning_queue SET state='capacity_reserved',node_id=?,updated_at=? WHERE id=?",(node["id"],stamp(),q["id"]))
        db.execute("UPDATE subscriptions SET state='capacity_reserved',node_id=?,updated_at=? WHERE id=?",(node["id"],stamp(),q["subscription_id"]))
        count+=1
    return count

@router.post("/auth/register",status_code=202)
def register(payload:Register):
    init_db(); token=secrets.token_urlsafe(36); uid="usr-"+uuid.uuid4().hex
    with connect() as db:
        if db.execute("SELECT 1 FROM users WHERE email=?",(payload.email,)).fetchone(): raise HTTPException(409,"Já existe uma conta com este e-mail.")
        db.execute("INSERT INTO users(id,email,display_name,password_hash,role,state,verify_hash,verify_expires,created_at) VALUES(?,?,?,?,?,'pending_verification',?,?,?)",
          (uid,payload.email,payload.display_name.strip(),password_hash(payload.password),"user",hashlib.sha256(token.encode()).hexdigest(),stamp(now()+timedelta(minutes=30)),stamp()))
        audit(db,uid,"account.registered",uid)
    send_verification(payload.email,payload.display_name.strip(),token)
    return {"accepted":True,"state":"pending_verification","message":"Verifique seu e-mail para ativar a conta."}

@router.post("/auth/resend-verification",status_code=202)
def resend_verification(payload:ResendVerification):
    init_db()
    email=payload.email.strip().lower()
    with connect() as db:
        row=db.execute("SELECT * FROM users WHERE email=? AND state='pending_verification'",(email,)).fetchone()
        if not row: return {"accepted":True,"message":"Se a conta estiver pendente, enviaremos um novo token."}
        issued=datetime.fromisoformat(row["verify_expires"])-timedelta(minutes=30) if row["verify_expires"] else now()-timedelta(minutes=1)
        if (now()-issued).total_seconds()<60:
            raise HTTPException(429,"Aguarde um minuto antes de solicitar outro token.")
        token=secrets.token_urlsafe(36)
        db.execute("UPDATE users SET verify_hash=?,verify_expires=? WHERE id=?",
                   (hashlib.sha256(token.encode()).hexdigest(),stamp(now()+timedelta(minutes=30)),row["id"]))
    send_verification(email,row["display_name"],token)
    return {"accepted":True,"message":"Se a conta estiver pendente, enviaremos um novo token."}


@router.post("/auth/verify-email")
def verify_email(payload:Verify):
    init_db(); digest=hashlib.sha256(payload.token.encode()).hexdigest()
    with connect() as db:
        row=db.execute("SELECT * FROM users WHERE verify_hash=?",(digest,)).fetchone()
        if not row or row["state"]!="pending_verification": raise HTTPException(400,"Token inválido ou já utilizado.")
        if not row["verify_expires"] or row["verify_expires"]<stamp(): raise HTTPException(400,"Token expirado.")
        db.execute("UPDATE users SET state='active',verify_hash=NULL,verify_expires=NULL,verified_at=? WHERE id=?",(stamp(),row["id"]))
        audit(db,row["id"],"account.email_verified",row["id"])
    return {"verified":True}

@router.post("/auth/login")
def login(payload:Login):
    init_db()
    with connect() as db: row=db.execute("SELECT * FROM users WHERE email=?",(payload.email.strip().lower(),)).fetchone()
    if not row or not password_valid(payload.password,row["password_hash"]): raise HTTPException(401,"E-mail ou senha inválidos.")
    if row["state"]!="active": raise HTTPException(403,"Confirme seu e-mail antes de entrar.")
    user={"id":row["id"],"email":row["email"],"display_name":row["display_name"],"role":row["role"]}
    return {"access_token":issue_token(user),"token_type":"bearer","expires_in":43200,"user":user}
@router.get("/auth/me")
def me(user=Depends(current_user)): return {"user":user}

@router.get("/plans")
def plans():
    init_db()
    with connect() as db: rows=db.execute("SELECT * FROM free_plans WHERE enabled=1").fetchall()
    return {"plans":[{"id":r["id"],"name":r["name"],"description":r["description"],"vcpus":r["vcpus"],"memory_mib":r["memory_mib"],"disk_gib":r["disk_gib"],"terms_years":json.loads(r["terms_json"])} for r in rows]}

@router.post("/subscriptions",status_code=202)
def subscribe(payload:Subscribe,user=Depends(current_user)):
    init_db()
    with connect() as db:
        plan=db.execute("SELECT * FROM free_plans WHERE id=? AND enabled=1",(payload.plan_id,)).fetchone()
        if not plan: raise HTTPException(404,"Plano indisponível.")
        if payload.term_years not in json.loads(plan["terms_json"]): raise HTTPException(422,"Prazo não permitido.")
        exists=db.execute("SELECT id FROM subscriptions WHERE user_id=? AND state IN ('waiting_capacity','capacity_reserved','active','grace')",(user["id"],)).fetchone()
        if exists: raise HTTPException(409,"Você já tem uma assinatura ativa ou na fila.")
        sid,qid,created="sub-"+uuid.uuid4().hex,"q-"+uuid.uuid4().hex,stamp()
        db.execute("INSERT INTO subscriptions(id,user_id,plan_id,term_years,state,auto_renew,created_at,updated_at) VALUES(?,?,?,?,'waiting_capacity',?,?,?)",(sid,user["id"],plan["id"],payload.term_years,int(payload.auto_renew),created,created))
        db.execute("INSERT INTO provisioning_queue(id,subscription_id,user_id,vcpus,memory_mib,disk_gib,state,created_at,updated_at) VALUES(?,?,?,?,?,?,'waiting_capacity',?,?)",(qid,sid,user["id"],plan["vcpus"],plan["memory_mib"],plan["disk_gib"],created,created))
        allocate_waiting(db); result=dict(db.execute("SELECT * FROM subscriptions WHERE id=?",(sid,)).fetchone())
        audit(db,user["id"],"subscription.created",sid,{"term_years":payload.term_years,"state":result["state"]})
    return {"subscription":result,"provisioned":False,"message":"Assinatura gratuita registrada. Reserva de capacidade não equivale a VPS provisionada."}

@router.get("/subscriptions")
def my_subscriptions(user=Depends(current_user)):
    init_db()
    with connect() as db: rows=db.execute("""SELECT s.*,p.name plan_name,q.state queue_state,q.last_error FROM subscriptions s JOIN free_plans p ON p.id=s.plan_id LEFT JOIN provisioning_queue q ON q.subscription_id=s.id WHERE s.user_id=? ORDER BY s.created_at DESC""",(user["id"],)).fetchall()
    return {"subscriptions":[dict(r) for r in rows]}
@router.patch("/subscriptions/{sid}/auto-renew")
def set_auto_renew(sid:str,payload:AutoRenew,user=Depends(current_user)):
    init_db()
    with connect() as db:
        changed=db.execute("UPDATE subscriptions SET auto_renew=?,updated_at=? WHERE id=? AND user_id=? AND state IN ('capacity_reserved','active','grace')",(int(payload.enabled),stamp(),sid,user["id"])).rowcount
        if not changed: raise HTTPException(404,"Assinatura não encontrada ou não alterável.")
        audit(db,user["id"],"subscription.auto_renew_changed",sid,{"enabled":payload.enabled})
    return {"subscription_id":sid,"auto_renew":payload.enabled}

@router.post("/subscriptions/{sid}/cancel")
def cancel_subscription(sid: str, user=Depends(current_user)):
    init_db()
    with connect() as db:
        sub=db.execute("SELECT * FROM subscriptions WHERE id=? AND user_id=?",(sid,user["id"])).fetchone()
        if not sub: raise HTTPException(404,"Assinatura não encontrada.")
        if sub["state"]=="active": raise HTTPException(409,"Uma VPS ativa precisa ser desligada e removida pelo fluxo de encerramento antes de cancelar a assinatura.")
        if sub["state"]=="canceled": return {"subscription_id":sid,"state":"canceled"}
        if sub["node_id"]:
            q=db.execute("SELECT * FROM provisioning_queue WHERE subscription_id=?",(sid,)).fetchone()
            if q:
                db.execute("UPDATE capacity_nodes SET reserved_vcpus=MAX(0,reserved_vcpus-?),reserved_memory_mib=MAX(0,reserved_memory_mib-?),reserved_disk_gib=MAX(0,reserved_disk_gib-?) WHERE id=?",
                           (q["vcpus"],q["memory_mib"],q["disk_gib"],sub["node_id"]))
        db.execute("UPDATE provisioning_queue SET state='canceled',updated_at=? WHERE subscription_id=?",(stamp(),sid))
        db.execute("UPDATE subscriptions SET state='canceled',auto_renew=0,updated_at=? WHERE id=?",(stamp(),sid))
        audit(db,user["id"],"subscription.canceled",sid)
        allocate_waiting(db)
    return {"subscription_id":sid,"state":"canceled"}

@router.post("/admin/bootstrap")
def bootstrap(authorization:str|None=Header(default=None),x_apolo_bootstrap_token:str|None=Header(default=None)):
    init_db(); expected=os.getenv("APOLO_BOOTSTRAP_ADMIN_TOKEN","")
    if len(expected)<32 or not x_apolo_bootstrap_token or not hmac.compare_digest(expected,x_apolo_bootstrap_token): raise HTTPException(403,"Token bootstrap inválido.")
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Entre com conta verificada.")
    claims=claims_for(authorization[7:].strip())
    with connect() as db:
        if db.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]: raise HTTPException(409,"Bootstrap já utilizado.")
        if not db.execute("UPDATE users SET role='admin' WHERE id=? AND state='active'",(claims["sub"],)).rowcount: raise HTTPException(403,"Conta não verificada.")
        audit(db,claims["sub"],"admin.bootstrap",claims["sub"])
    return {"promoted":True,"message":"Admin inicial criado. Remova APOLO_BOOTSTRAP_ADMIN_TOKEN agora."}

@router.get("/admin/overview")
def admin_overview(admin=Depends(admin_user)):
    init_db()
    with connect() as db:
        counts={t:db.execute("SELECT COUNT(*) FROM "+t).fetchone()[0] for t in ("users","subscriptions","capacity_nodes","provisioning_queue")}
        states={r["state"]:r["n"] for r in db.execute("SELECT state,COUNT(*) n FROM provisioning_queue GROUP BY state")}
        nodes=[dict(r) for r in db.execute("SELECT * FROM capacity_nodes ORDER BY created_at DESC")]
        waiting=[dict(r) for r in db.execute("""SELECT q.*,u.email,s.term_years FROM provisioning_queue q JOIN users u ON u.id=q.user_id JOIN subscriptions s ON s.id=q.subscription_id WHERE q.state='waiting_capacity' ORDER BY q.created_at LIMIT 100""")]
    return {"counts":counts,"queue_states":states,"nodes":nodes,"waiting_queue":waiting}
@router.get("/admin/users")
def admin_users(admin=Depends(admin_user)):
    init_db()
    with connect() as db: rows=db.execute("SELECT id,email,display_name,role,state,created_at,verified_at FROM users ORDER BY created_at DESC LIMIT 500").fetchall()
    return {"users":[dict(r) for r in rows]}
@router.post("/admin/nodes",status_code=201)
def register_node(payload:NodeCreate,admin=Depends(admin_user)):
    init_db(); nid="node-"+uuid.uuid4().hex
    with connect() as db:
        db.execute("INSERT INTO capacity_nodes(id,name,state,verified,created_at) VALUES(?,?,'pending_verification',0,?)",(nid,payload.name,stamp()))
        audit(db,admin["id"],"node.registered",nid,{"name":payload.name})
    return {"node_id":nid,"state":"pending_verification","capacity_eligible":False}
@router.post("/admin/nodes/{nid}/probe")
def probe_node(nid:str,admin=Depends(admin_user)):
    init_db()
    with connect() as db:
        other=db.execute("SELECT id FROM capacity_nodes WHERE state='healthy' AND verified=1 AND id<>? LIMIT 1",(nid,)).fetchone()
    if other: raise HTTPException(409,"O adaptador atual representa um único host agent; não duplique sua capacidade.")
    url=os.getenv("APOLO_PROVISIONER_URL","").rstrip("/"); token=os.getenv("APOLO_PROVISIONER_TOKEN","")
    if not url.startswith("https://") or not token: raise HTTPException(503,"Configure host agent por HTTPS privado.")
    try:
        response=httpx.get(url+"/agent/v1/capacity",headers={"X-Apolo-Agent-Token":token},timeout=httpx.Timeout(10,connect=3)); response.raise_for_status(); data=response.json()
    except (httpx.HTTPError,ValueError) as exc:
        with connect() as db:
            pending=db.execute("SELECT COALESCE(SUM(vcpus),0) v,COALESCE(SUM(memory_mib),0) m,COALESCE(SUM(disk_gib),0) d FROM provisioning_queue WHERE node_id=? AND state='capacity_reserved'",(nid,)).fetchone()
            db.execute("UPDATE capacity_nodes SET state='offline',verified=0,reserved_vcpus=MAX(0,reserved_vcpus-?),reserved_memory_mib=MAX(0,reserved_memory_mib-?),reserved_disk_gib=MAX(0,reserved_disk_gib-?) WHERE id=?",
                       (pending["v"],pending["m"],pending["d"],nid))
            db.execute("UPDATE provisioning_queue SET state='waiting_capacity',node_id=NULL,updated_at=?,last_error='Host agent indisponível; reserva liberada.' WHERE node_id=? AND state='capacity_reserved'",(stamp(),nid))
            db.execute("UPDATE subscriptions SET state='waiting_capacity',node_id=NULL,updated_at=? WHERE node_id=? AND state='capacity_reserved'",(stamp(),nid))
            allocate_waiting(db)
        raise HTTPException(503,"Não foi possível medir a capacidade real.") from exc
    keys=("available_vcpus","available_memory_mib","available_disk_gib")
    if data.get("state")!="ok" or data.get("authorized") is not True or data.get("storage",{}).get("durable") is not True or data.get("storage",{}).get("type") not in {"nfs","nfs4"} or any(type(data.get(k)) is not int or data[k]<0 for k in keys): raise HTTPException(502,"Agente não confirmou capacidade e armazenamento NFS durável.")
    with connect() as db:
        if not db.execute("SELECT 1 FROM capacity_nodes WHERE id=?",(nid,)).fetchone(): raise HTTPException(404,"Nó não encontrado.")
        db.execute("UPDATE capacity_nodes SET state='healthy',verified=1,free_vcpus=?,free_memory_mib=?,free_disk_gib=?,last_probe=? WHERE id=?",(*(data[k] for k in keys),stamp(),nid))
        reserved=allocate_waiting(db); audit(db,admin["id"],"node.probed",nid,{"newly_reserved":reserved})
    return {"node_id":nid,"state":"healthy","measured_capacity":{k:data[k] for k in keys},"newly_reserved":reserved,"provisioned":False}
@router.post("/admin/queue/reconcile")
def reconcile(admin=Depends(admin_user)):
    init_db()
    with connect() as db:
        allocated=allocate_waiting(db); waiting=db.execute("SELECT COUNT(*) FROM provisioning_queue WHERE state='waiting_capacity'").fetchone()[0]; reserved=db.execute("SELECT COUNT(*) FROM provisioning_queue WHERE state='capacity_reserved'").fetchone()[0]
        audit(db,admin["id"],"queue.reconciled",None,{"allocated":allocated})
    return {"newly_reserved":allocated,"waiting_capacity":waiting,"capacity_reserved":reserved,"provisioned":False}
@router.get("/admin/subscriptions")
def admin_subscriptions(admin=Depends(admin_user)):
    init_db()
    with connect() as db: rows=db.execute("SELECT s.*,u.email,p.name plan_name FROM subscriptions s JOIN users u ON u.id=s.user_id JOIN free_plans p ON p.id=s.plan_id ORDER BY s.created_at DESC LIMIT 500").fetchall()
    return {"subscriptions":[dict(r) for r in rows]}
@router.get("/admin/audit")
def admin_audit(admin=Depends(admin_user)):
    init_db()
    with connect() as db: rows=db.execute("SELECT * FROM audit_events ORDER BY created_at DESC LIMIT 500").fetchall()
    return {"events":[dict(r)|{"details":json.loads(r["details_json"])} for r in rows]}

def process_due_renewals(at=None):
    init_db(); at=at or now(); renewed=deferred=disabled=0
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        due=db.execute("SELECT * FROM subscriptions WHERE state='active' AND auto_renew=1 AND renews_at IS NOT NULL AND renews_at<=?",(stamp(at),)).fetchall()
        for sub in due:
            scheduled=sub["renews_at"]; node=db.execute("SELECT * FROM capacity_nodes WHERE id=?",(sub["node_id"],)).fetchone() if sub["node_id"] else None
            if node and node["state"]=="healthy" and node["verified"]:
                next_date=datetime.fromisoformat(scheduled)+timedelta(days=365*int(sub["term_years"]))
                db.execute("UPDATE subscriptions SET renews_at=?,updated_at=? WHERE id=?",(stamp(next_date),stamp(at),sub["id"]))
                db.execute("INSERT OR IGNORE INTO renewal_events VALUES(?,?,?,'renewed',?)",("ren-"+uuid.uuid4().hex,sub["id"],scheduled,stamp(at))); renewed+=1
            else:
                db.execute("UPDATE subscriptions SET state='grace',updated_at=? WHERE id=?",(stamp(at),sub["id"]))
                db.execute("INSERT OR IGNORE INTO renewal_events VALUES(?,?,?,'capacity_unavailable',?)",("ren-"+uuid.uuid4().hex,sub["id"],scheduled,stamp(at))); deferred+=1
        disabled=db.execute("SELECT COUNT(*) FROM subscriptions WHERE state='active' AND auto_renew=0 AND renews_at IS NOT NULL AND renews_at<=?",(stamp(at),)).fetchone()[0]
    return {"renewed":renewed,"deferred_for_capacity":deferred,"auto_renew_disabled":disabled}
