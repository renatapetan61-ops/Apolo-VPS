from __future__ import annotations

import os
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .catalog import list_images
from .ipam import IPAMError, IPAllocator
from .security import generate_password, generated_hostname

app = FastAPI(
    title="APOLO VPS API",
    version="0.2.0",
    description="Greek-gold cloud infrastructure control plane",
)

origins = [item.strip() for item in os.getenv("APOLO_CORS_ORIGINS", "http://localhost:5173").split(",") if item.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)


class CreateInstance(BaseModel):
    computer_name: str | None = Field(default=None, min_length=3, max_length=63)
    username: str = Field(min_length=3, max_length=32)
    os: str
    location: str = "auto"
    plan: str = "standard-2"

    @field_validator("computer_name")
    @classmethod
    def validate_hostname(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().lower()
        import re
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Computer name must be a valid DNS hostname.")
        return value

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        import re
        value = value.strip()
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{2,31}", value):
            raise ValueError("Username must contain 3–32 safe characters.")
        return value


def _agent_config() -> tuple[str, str]:
    url = os.getenv("APOLO_PROVISIONER_URL", "").rstrip("/")
    token = os.getenv("APOLO_PROVISIONER_TOKEN", "")
    if not url or not token:
        raise HTTPException(503, "Configure the private APOLO host-agent URL and token first.")
    if not url.startswith("https://") and os.getenv("APOLO_ALLOW_INSECURE_AGENT") != "true":
        raise HTTPException(503, "Host-agent URL must use HTTPS. Insecure transport is disabled.")
    return url, token


def _agent_get(path: str):
    url, token = _agent_config()
    try:
        response = httpx.get(
            f"{url}{path}",
            headers={"X-Apolo-Agent-Token": token},
            timeout=httpx.Timeout(4.0, connect=2.0),
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Host agent is unreachable or rejected the request.") from exc


@app.get("/api/v1/health")
def health():
    configured = bool(os.getenv("APOLO_PROVISIONER_URL") and os.getenv("APOLO_PROVISIONER_TOKEN"))
    agent_reachable = False
    hypervisor = None
    if configured:
        try:
            payload = _agent_get("/agent/v1/health")
            agent_reachable = payload.get("state") == "ok"
            hypervisor = payload.get("hypervisor")
        except HTTPException:
            pass
    return {
        "service": "apolo-vps-api",
        "state": "ok",
        "provider_configured": configured,
        "provider_ready": agent_reachable,
        "provisioning_mode": "remote-libvirt-agent" if agent_reachable else "not-ready",
        "hypervisor": hypervisor,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/hypervisors")
def list_hypervisors():
    configured = bool(os.getenv("APOLO_PROVISIONER_URL") and os.getenv("APOLO_PROVISIONER_TOKEN"))
    if not configured:
        return {"hypervisors": [], "source": "not-configured"}
    try:
        health_payload = _agent_get("/agent/v1/health")
        return {"hypervisors": [health_payload.get("hypervisor", {})], "source": "live-agent"}
    except HTTPException:
        return {"hypervisors": [], "source": "agent-unreachable"}


@app.get("/api/v1/images")
def images():
    payload = _agent_get("/agent/v1/images")
    return {"images": payload.get("images", []), "source": "live-hypervisor-catalog"}


@app.get("/api/v1/instances")
def list_instances():
    payload = _agent_get("/agent/v1/domains")
    return {"instances": payload.get("domains", []), "source": "live-libvirt"}


@app.post("/api/v1/instances", status_code=status.HTTP_501_NOT_IMPLEMENTED)
def create_instance(payload: CreateInstance):
    # Provisioning is deliberately blocked until the complete guest bootstrap
    # pipeline (cloud-init/Windows unattend), IPAM bridge wiring, persistence,
    # quotas and rollback are configured. Never return pretend credentials.
    image = next((item for item in list_images() if item["id"] == payload.os), None)
    if not image or not image["enabled"]:
        raise HTTPException(409, "Selected OS image is not installed and verified on this host.")
    raise HTTPException(
        status.HTTP_501_NOT_IMPLEMENTED,
        "The libvirt inventory and lifecycle adapter are available, but guest creation is gated until cloud-init/Windows bootstrap and network bridge integration are completed. No VM was created.",
    )


@app.post("/api/v1/instances/{name}/{action}")
def instance_lifecycle(name: str, action: str):
    if action not in {"start", "shutdown", "reboot", "destroy", "delete"}:
        raise HTTPException(400, "Unsupported lifecycle action.")
    url, token = _agent_config()
    try:
        response = httpx.post(
            f"{url}/agent/v1/domains/{name}/{action}",
            headers={"X-Apolo-Agent-Token": token},
            timeout=httpx.Timeout(8.0, connect=2.0),
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(exc.response.status_code, "Host agent rejected the lifecycle operation.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Host agent is unreachable.") from exc


@app.get("/")
def root():
    return {"name": "APOLO VPS", "api": "/api/v1/health", "docs": "/docs"}
