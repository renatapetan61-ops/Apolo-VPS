from __future__ import annotations

import hmac
import os
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from .libvirt_provider import LibvirtProvider, ProviderUnavailable

app = FastAPI(title="APOLO VPS Host Agent", version="0.3.0")

class ProvisionRequest(BaseModel):
    instance_id: str = Field(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9-]+$")
    computer_name: str | None = Field(default=None, min_length=3, max_length=63)
    username: str = Field(min_length=3, max_length=32)
    image_id: str
    ipv4: str
    ipv6: str
    memory_mib: int = Field(ge=512, le=131072)
    vcpus: int = Field(ge=1, le=32)
    disk_gib: int = Field(ge=10, le=2048)

provider = LibvirtProvider()


def _authorize(token: str | None) -> None:
    expected = os.getenv("APOLO_AGENT_TOKEN")
    if not expected:
        raise HTTPException(503, "Host agent is not configured.")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(401, "Invalid agent credential.")


@app.get("/agent/v1/health")
def health(x_apolo_agent_token: str | None = Header(default=None)):
    _authorize(x_apolo_agent_token)
    try:
        info = provider.hypervisor_info()
        return {"state": "ok", "provider": "libvirt", "hypervisor": info}
    except ProviderUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/agent/v1/images")
def images(x_apolo_agent_token: str | None = Header(default=None)):
    _authorize(x_apolo_agent_token)
    from .catalog import list_images
    return {"images": list_images()}


@app.get("/agent/v1/domains")
def domains(x_apolo_agent_token: str | None = Header(default=None)):
    _authorize(x_apolo_agent_token)
    try:
        return {"domains": provider.list_domains()}
    except ProviderUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/agent/v1/domains/{name}/{action}")
def lifecycle(name: str, action: str, x_apolo_agent_token: str | None = Header(default=None)):
    _authorize(x_apolo_agent_token)
    try:
        return provider.lifecycle(name, action)
    except (ProviderUnavailable, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@app.post("/agent/v1/provision")
def provision(payload: ProvisionRequest, x_apolo_agent_token: str | None = Header(default=None)):
    _authorize(x_apolo_agent_token)
    from .provisioning import provision_linux, ProvisioningError
    try:
        return provision_linux(
            instance_id=payload.instance_id, computer_name=payload.computer_name,
            username=payload.username, image_id=payload.image_id,
            ipv4=payload.ipv4, ipv6=payload.ipv6, memory_mib=payload.memory_mib,
            vcpus=payload.vcpus, disk_gib=payload.disk_gib,
        )
    except (ProvisioningError, ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, "Provisioning failed; inspect secured host-agent logs.") from exc
