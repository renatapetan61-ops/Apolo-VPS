from __future__ import annotations

import hmac
import os
from fastapi import FastAPI, Header, HTTPException
from .libvirt_provider import LibvirtProvider, ProviderUnavailable

app = FastAPI(title="APOLO VPS Host Agent", version="0.2.0")
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
