from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from .environment_manager import EnvironmentStore

log = logging.getLogger("apolo.environment_worker")


class ProviderError(RuntimeError):
    pass


class LibvirtAgentProvider:
    """Authorized external QEMU/KVM host agent; Codespaces is intentionally not a VPS provider."""

    name = "libvirt-agent"

    def __init__(self, base_url: str, token: str, timeout: float = 30):
        if not base_url.startswith("https://") and os.getenv("APOLO_ALLOW_INSECURE_AGENT") != "true":
            raise ProviderError("The host-agent endpoint must use HTTPS.")
        if not token:
            raise ProviderError("APOLO_PROVISIONER_TOKEN is not configured.")
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            headers={"X-Apolo-Agent-Token": token},
            timeout=httpx.Timeout(timeout, connect=5),
        )

    def _request(self, method: str, path: str, payload: dict | None = None) -> dict:
        try:
            response = self.client.request(method, self.base_url + path, json=payload)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ProviderError("Host agent returned a non-object response.")
            return data
        except httpx.HTTPError as exc:
            raise ProviderError(f"Host agent request failed: {type(exc).__name__}") from exc

    def capacity(self) -> dict:
        data = self._request("GET", "/agent/v1/capacity")
        if data.get("authorized") is not True or data.get("state") != "ok":
            raise ProviderError("Host agent did not confirm authorization and healthy capacity.")
        return data

    def ensure_disk(self, job: dict) -> dict:
        if job.get("disk_uri"):
            return {"disk_uri": job["disk_uri"], "durable": True}
        return self._request("POST", "/agent/v1/disks/ensure", {
            "environment_id": job["id"], "vps_id": job["vps_id"],
            "size_gib": job["disk_gib"], "storage_class": "persistent",
        })

    def restore(self, job: dict, disk_uri: str) -> dict:
        return self._request("POST", "/agent/v1/environments/restore", {
            "environment_id": job["id"], "vps_id": job["vps_id"],
            "disk_uri": disk_uri, "vcpus": job["vcpus"],
            "memory_mib": job["memory_mib"], "disk_gib": job["disk_gib"],
        })

    def verify_runtime(self, runtime_id: str) -> dict:
        return self._request("GET", "/agent/v1/runtimes/" + runtime_id)


class EnvironmentWorker:
    def __init__(self, store: EnvironmentStore, providers: dict[str, Any]):
        self.store = store
        self.providers = providers

    def process_once(self) -> dict | None:
        job = self.store.claim_next()
        if job is None:
            return None
        try:
            provider = self.providers.get(job["provider"])
            if provider is None:
                raise ProviderError(f"Provider '{job['provider']}' is not enabled by server policy.")

            capacity = provider.capacity()
            if capacity.get("available_vcpus", 0) < job["vcpus"]:
                raise ProviderError("Insufficient authorized vCPU capacity.")
            if capacity.get("available_memory_mib", 0) < job["memory_mib"]:
                raise ProviderError("Insufficient authorized RAM capacity.")
            if capacity.get("available_disk_gib", 0) < job["disk_gib"]:
                raise ProviderError("Insufficient persistent storage capacity.")

            disk = provider.ensure_disk(job)
            disk_uri = disk.get("disk_uri")
            if disk.get("durable") is not True or not isinstance(disk_uri, str) or not disk_uri:
                raise ProviderError("Storage provider did not confirm a durable disk URI.")

            started = provider.restore(job, disk_uri)
            runtime_id = started.get("runtime_id")
            if started.get("accepted") is not True or not isinstance(runtime_id, str) or not runtime_id:
                raise ProviderError("Provider did not confirm runtime creation.")

            observed = provider.verify_runtime(runtime_id)
            if observed.get("state") != "running" or observed.get("disk_uri") != disk_uri:
                raise ProviderError("Runtime or attached persistent disk could not be independently verified.")

            result = self.store.transition(
                job["id"], "running", disk_uri=disk_uri, runtime_id=runtime_id,
                last_error=None,
            )
            return {"environment": result, "verified": True}
        except Exception as exc:
            log.warning("Environment job %s not started: %s", job["id"], exc)
            latest = self.store.get(job["id"]) or job
            retryable = isinstance(exc, ProviderError) and any(
                marker in str(exc).lower() for marker in
                ("insufficient", "unreachable", "timeout", "capacity")
            )
            self.store.transition(
                job["id"], "waiting_capacity" if retryable else "failed",
                disk_uri=latest.get("disk_uri"),
                last_error=str(exc)[:500],
            )
            return {"environment_id": job["id"], "verified": False, "error": str(exc)[:500]}


def build_worker() -> EnvironmentWorker:
    url = os.getenv("APOLO_PROVISIONER_URL", "").rstrip("/")
    token = os.getenv("APOLO_PROVISIONER_TOKEN", "")
    allow = {x.strip() for x in os.getenv("APOLO_ENABLED_PROVIDERS", "libvirt-agent").split(",") if x.strip()}
    providers: dict[str, Any] = {}
    if "libvirt-agent" in allow and url and token:
        providers["libvirt-agent"] = LibvirtAgentProvider(url, token)
    # Codespaces is short-lived development infrastructure, never a VPS runtime provider.
    return EnvironmentWorker(EnvironmentStore(), providers)


def run_worker(poll_seconds: float = 10) -> None:
    worker = build_worker()
    while True:
        try:
            result = worker.process_once()
            if result is None:
                time.sleep(poll_seconds)
        except Exception:
            log.exception("Environment worker iteration failed")
            time.sleep(poll_seconds)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    run_worker(float(os.getenv("APOLO_WORKER_POLL_SECONDS", "10")))
