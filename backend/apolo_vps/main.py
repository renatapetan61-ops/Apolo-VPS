from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

app = FastAPI(title="APOLO VPS API", version="0.1.0", description="Greek-gold cloud infrastructure control plane")

origins = [item.strip() for item in os.getenv("APOLO_CORS_ORIGINS", "http://localhost:5173").split(",") if item.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=False, allow_methods=["GET", "POST"], allow_headers=["Content-Type", "Authorization"])

class CreateInstance(BaseModel):
    computer_name: str = Field(min_length=3, max_length=63)
    username: str = Field(min_length=3, max_length=32)
    os: Literal["ubuntu-24.04", "debian-12", "rocky-9", "windows-server-2022"]
    location: Literal["auto", "sa-east", "us-east", "eu-west"] = "auto"
    plan: Literal["standard-2"] = "standard-2"

    @field_validator("computer_name")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        value = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", value):
            raise ValueError("Computer name must be a valid DNS hostname.")
        return value

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not re.fullmatch(r"[a-z_][a-z0-9_-]{2,31}", value):
            raise ValueError("Username must contain 3–32 safe characters.")
        return value

@app.get("/api/v1/health")
def health():
    provider = os.getenv("APOLO_PROVISIONER_URL")
    token = os.getenv("APOLO_PROVISIONER_TOKEN")
    configured = bool(provider and token)
    return {
        "service": "apolo-vps-api",
        "state": "ok",
        "provider_ready": configured,
        "provisioning_mode": "remote-agent" if configured else "not-configured",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

@app.get("/api/v1/instances")
def list_instances():
    # Inventory is intentionally empty until a real provider-backed inventory is connected.
    # Never manufacture VM records, addresses, or credentials.
    return {"instances": [], "source": "provider-not-connected"}

@app.post("/api/v1/instances", status_code=status.HTTP_202_ACCEPTED)
def create_instance(payload: CreateInstance):
    provider = os.getenv("APOLO_PROVISIONER_URL")
    token = os.getenv("APOLO_PROVISIONER_TOKEN")
    if not provider or not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Real VPS provisioning is not enabled. Connect and configure a secured KVM/libvirt host agent first.",
        )
    # Deliberately fail closed until the authenticated host-agent protocol and
    # network/image inventory have been configured and verified.
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Provider endpoint is configured, but provisioning adapter is not yet enabled. No VM was created.",
    )

@app.get("/")
def root():
    return {"name": "APOLO VPS", "api": "/api/v1/health", "docs": "/docs"}
