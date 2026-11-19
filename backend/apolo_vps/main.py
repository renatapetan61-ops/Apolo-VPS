from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .ipam import IPAMError, IPAllocator
from .store import InstanceStore

app = FastAPI(title="APOLO VPS API", version="0.3.0",
              description="Greek-gold cloud infrastructure control plane")
origins = [x.strip() for x in os.getenv("APOLO_CORS_ORIGINS", "http://localhost:5173").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False,
                   allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type", "Authorization"])

class CreateInstance(BaseModel):
    computer_name: str | None = Field(default=None, min_length=3, max_length=63)
    username: str = Field(min_length=3, max_length=32)
    os: str
    location: str = "auto"
    plan: str = "standard-2"
    memory_mib: int = Field(default=2048, ge=512, le=131072)
    vcpus: int = Field(default=2, ge=1, le=32)
    disk_gib: int = Field(default=25, ge=10, le=2048)

    @field_validator("computer_name")
    @classmethod
    def validate_hostname(cls, value):
        if value is None: return value
        import re
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Computer name must be a valid DNS hostname.")
        return value

    @field_validator("username")
    @classmethod
    def validate_username(cls, value):
        import re
        value = value.strip()
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{2,31}", value):
            raise ValueError("Username must contain 3–32 safe characters.")
        return value

def _agent_config():
    url = os.getenv("APOLO_PROVISIONER_URL", "").rstrip("/")
    token = os.getenv("APOLO_PROVISIONER_TOKEN", "")
    if not url or not token:
        raise HTTPException(503, "Configure a private HTTPS APOLO host-agent URL and token.")
    if not url.startswith("https://") and os.getenv("APOLO_ALLOW_INSECURE_AGENT") != "true":
        raise HTTPException(503, "Host-agent URL must use HTTPS.")
    return url, token

def _agent_request(method, path, body=None, timeout=12):
    url, token = _agent_config()
    try:
        response = httpx.request(method, f"{url}{path}",
            headers={"X-Apolo-Agent-Token": token}, json=body,
            timeout=httpx.Timeout(timeout, connect=3))
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        detail = "Host agent rejected the operation."
        try: detail = exc.response.json().get("detail", detail)
        except Exception: pass
        raise HTTPException(exc.response.status_code, detail) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Host agent is unreachable.") from exc

def _store():
    return InstanceStore()

def _ipam():
    return IPAllocator()

@app.get("/api/v1/health")
def health():
    configured = bool(os.getenv("APOLO_PROVISIONER_URL") and os.getenv("APOLO_PROVISIONER_TOKEN"))
    hypervisor = None
    ready = False
    if configured:
        try:
            result = _agent_request("GET", "/agent/v1/health", timeout=5)
            ready = result.get("state") == "ok"
            hypervisor = result.get("hypervisor")
        except HTTPException: pass
    return {"service":"apolo-vps-api","state":"ok","provider_configured":configured,
            "provider_ready":ready,"provisioning_mode":"remote-libvirt-agent" if ready else "not-ready",
            "hypervisor":hypervisor,"timestamp":datetime.now(timezone.utc).isoformat()}

@app.get("/api/v1/hypervisors")
def hypervisors():
    return {"hypervisors":[_agent_request("GET","/agent/v1/health").get("hypervisor",{})],
            "source":"live-agent"}

@app.get("/api/v1/images")
def images():
    return _agent_request("GET","/agent/v1/images")

@app.get("/api/v1/instances")
def instances():
    stored = _store().list()
    live = _agent_request("GET","/agent/v1/domains").get("domains",[])
    live_by_name = {x["name"]:x for x in live}
    result=[]
    for item in stored:
        item["libvirt_state"] = live_by_name.get(item["name"],{}).get("state")
        result.append(item)
    return {"instances":result,"source":"sqlite-plus-live-libvirt"}

@app.post("/api/v1/instances", status_code=status.HTTP_201_CREATED)
def create_instance(payload: CreateInstance):
    instance_id = "vm-" + uuid.uuid4().hex
    try:
        ipv4, ipv6 = _ipam().allocate(instance_id)
    except IPAMError as exc:
        raise HTTPException(503, str(exc)) from exc
    try:
        result = _agent_request("POST", "/agent/v1/provision", {
            "instance_id":instance_id, "computer_name":payload.computer_name,
            "username":payload.username, "image_id":payload.os, "ipv4":ipv4, "ipv6":ipv6,
            "memory_mib":payload.memory_mib, "vcpus":payload.vcpus, "disk_gib":payload.disk_gib,
        }, timeout=240)
        record={"id":instance_id,"name":result["computer_name"],"username":payload.username,
                "os":payload.os,"ipv4":ipv4,"ipv6":ipv6,"state":"running"}
        _store().save(record)
        return {"instance":record,"credentials":{"username":payload.username,"password":result["password"]},
                "message":"VM created and started by libvirt. Save the password now; it will not be shown again."}
    except Exception:
        try: _ipam().release(instance_id)
        except Exception: pass
        raise

@app.post("/api/v1/instances/{name}/{action}")
def instance_lifecycle(name: str, action: str):
    if action not in {"start","shutdown","reboot","destroy","delete"}:
        raise HTTPException(400,"Unsupported lifecycle action.")
    result = _agent_request("POST",f"/agent/v1/domains/{name}/{action}")
    if action == "delete":
        item = _store().get_by_name(name)
        if item:
            _store().delete(item["id"])
            try: _ipam().release(item["id"])
            except Exception: pass
    return result

@app.get("/")
def root():
    return {"name":"APOLO VPS","api":"/api/v1/health","docs":"/docs"}
