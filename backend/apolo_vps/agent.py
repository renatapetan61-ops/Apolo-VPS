from __future__ import annotations

import hmac
import os
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from .libvirt_provider import LibvirtProvider, ProviderUnavailable

app = FastAPI(title="APOLO VPS Host Agent", version="0.4.0")
provider = LibvirtProvider()


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


class DiskRequest(BaseModel):
    environment_id: str = Field(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9-]+$")
    vps_id: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9-]+$")
    size_gib: int = Field(ge=10, le=2048)
    storage_class: str = Field(default="persistent")


class RestoreRequest(BaseModel):
    environment_id: str = Field(min_length=8, max_length=64, pattern=r"^[a-zA-Z0-9-]+$")
    vps_id: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9-]+$")
    disk_uri: str
    vcpus: int = Field(ge=1, le=32)
    memory_mib: int = Field(ge=512, le=131072)
    disk_gib: int = Field(ge=10, le=2048)


def _authorize(token: str | None) -> None:
    expected = os.getenv("APOLO_AGENT_TOKEN")
    if not expected:
        raise HTTPException(503, "Host agent is not configured.")
    if not token or not hmac.compare_digest(token, expected):
        raise HTTPException(401, "Invalid agent credential.")


def _persistent_root() -> Path:
    raw = os.getenv("APOLO_PERSISTENT_STORAGE_MOUNT", "")
    if not raw:
        raise HTTPException(503, "APOLO_PERSISTENT_STORAGE_MOUNT is not configured.")
    root = Path(raw).resolve()
    if not root.is_dir() or not os.path.ismount(root):
        raise HTTPException(503, "Persistent storage path is not a mounted filesystem.")
    try:
        result = subprocess.run(
            ["findmnt", "-n", "-o", "FSTYPE", "--target", str(root)],
            check=True, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(503, "Unable to verify persistent storage mount.") from exc
    if result.stdout.strip().lower() not in {"nfs", "nfs4"}:
        raise HTTPException(503, "The configured persistent volume must be NFS/NFS4 shared storage.")
    return root


def _disk_path(disk_uri: str) -> Path:
    parsed = urlparse(disk_uri)
    if parsed.scheme != "file" or parsed.netloc not in {"", "localhost"}:
        raise HTTPException(400, "Unsupported disk URI; expected a local file URI on the shared NFS mount.")
    root = _persistent_root()
    path = Path(unquote(parsed.path)).resolve()
    if root not in path.parents or path.suffix != ".qcow2":
        raise HTTPException(400, "Disk URI is outside the authorized persistent storage root.")
    return path


@app.get("/agent/v1/health")
def health(x_apolo_agent_token: str | None = Header(default=None)):
    _authorize(x_apolo_agent_token)
    try:
        info = provider.hypervisor_info()
        return {"state": "ok", "provider": "libvirt", "location": os.getenv("APOLO_HYPERVISOR_LOCATION", "unassigned"), "hypervisor": info}
    except ProviderUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/agent/v1/capacity")
def capacity(x_apolo_agent_token: str | None = Header(default=None)):
    _authorize(x_apolo_agent_token)
    try:
        root = _persistent_root()
        conn = provider._connection()
        try:
            info = conn.getInfo()
            active = [d for d in conn.listAllDomains(1) if d.isActive()]
            used_vcpus = sum(int(d.info()[3]) for d in active)
            free_memory_mib = int(conn.getFreeMemory() or 0) // 1024
            free_disk_gib = shutil.disk_usage(root).free // (1024 ** 3)
            return {
                "state": "ok", "authorized": True,
                "available_vcpus": max(0, int(info[2]) - used_vcpus),
                "available_memory_mib": free_memory_mib,
                "available_disk_gib": int(free_disk_gib),
                "storage": {"type": "nfs", "mount": str(root), "durable": True},
                "hypervisor": {"hostname": conn.getHostname(), "uri": provider.uri},
            }
        finally:
            conn.close()
    except (ProviderUnavailable, OSError) as exc:
        raise HTTPException(503, str(exc)) from exc


@app.post("/agent/v1/disks/ensure")
def ensure_disk(payload: DiskRequest, x_apolo_agent_token: str | None = Header(default=None)):
    _authorize(x_apolo_agent_token)
    if payload.storage_class != "persistent":
        raise HTTPException(400, "Only persistent storage class is supported.")
    root = _persistent_root()
    base_raw = os.getenv("APOLO_ENVIRONMENT_BASE_IMAGE", "")
    if not base_raw:
        raise HTTPException(503, "APOLO_ENVIRONMENT_BASE_IMAGE is not configured.")
    base_image = Path(base_raw).resolve()
    # QCOW2 overlays retain a reference to their backing image. Requiring the
    # base image on the same shared NFS export prevents a recovered VM on a
    # replacement host from depending on a file that existed only on the old host.
    if root not in base_image.parents or not base_image.is_file():
        raise HTTPException(503, "The verified base image must be a file inside the shared NFS mount.")
    disk = (root / f"{payload.environment_id}.qcow2").resolve()
    if disk.parent != root:
        raise HTTPException(400, "Invalid disk path.")
    qemu_img = os.getenv("APOLO_QEMU_IMG", "qemu-img")
    import json
    try:
        base_info = subprocess.run(
            [qemu_img, "info", "--output=json", str(base_image)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        base_format = json.loads(base_info.stdout).get("format")
        if base_format not in {"qcow2", "raw"}:
            raise HTTPException(503, "Base image format must be qcow2 or raw.")
        if not disk.exists():
            subprocess.run(
                [qemu_img, "create", "-f", "qcow2", "-F", base_format, "-b", str(base_image), str(disk), f"{payload.size_gib}G"],
                check=True, capture_output=True, text=True, timeout=180,
            )
        info = subprocess.run(
            [qemu_img, "info", "--output=json", str(disk)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        details = json.loads(info.stdout)
        backing = details.get("backing-filename")
        backing_path = Path(backing).resolve() if backing else None
        if (details.get("format") != "qcow2"
                or int(details.get("virtual-size", 0)) < payload.size_gib * (1024 ** 3)
                or backing_path != base_image):
            raise HTTPException(409, "Persistent disk format, size or shared backing image does not match the request.")
    except HTTPException:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as exc:
        disk.unlink(missing_ok=True)
        raise HTTPException(503, "Unable to create or verify the persistent QCOW2 disk and its shared backing image.") from exc
    return {"durable": True, "disk_uri": disk.as_uri(), "storage_class": "persistent", "storage_type": "nfs"}


@app.post("/agent/v1/environments/restore")
def restore(payload: RestoreRequest, x_apolo_agent_token: str | None = Header(default=None)):
    _authorize(x_apolo_agent_token)
    disk = _disk_path(payload.disk_uri)
    if not disk.is_file():
        raise HTTPException(404, "Persistent disk does not exist.")
    bridge = os.getenv("APOLO_LIBVIRT_BRIDGE", "")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,62}", bridge):
        raise HTTPException(503, "A valid APOLO_LIBVIRT_BRIDGE is required.")
    name = "apolo-" + payload.environment_id.replace("-", "")[:48]
    conn = provider._connection()
    try:
        try:
            domain = conn.lookupByName(name)
            if not domain.isActive():
                domain.create()
        except Exception:
            root = ET.Element("domain", type="kvm")
            ET.SubElement(root, "name").text = name
            ET.SubElement(root, "memory", unit="MiB").text = str(payload.memory_mib)
            ET.SubElement(root, "vcpu").text = str(payload.vcpus)
            os_node = ET.SubElement(root, "os")
            ET.SubElement(os_node, "type", arch="x86_64", machine="q35").text = "hvm"
            ET.SubElement(root, "features")
            devices = ET.SubElement(root, "devices")
            ET.SubElement(devices, "emulator").text = os.getenv("APOLO_QEMU_EMULATOR", "/usr/bin/qemu-system-x86_64")
            disk_node = ET.SubElement(devices, "disk", type="file", device="disk")
            ET.SubElement(disk_node, "driver", name="qemu", type="qcow2")
            ET.SubElement(disk_node, "source", file=str(disk))
            ET.SubElement(disk_node, "target", dev="vda", bus="virtio")
            nic = ET.SubElement(devices, "interface", type="bridge")
            ET.SubElement(nic, "source", bridge=bridge)
            ET.SubElement(nic, "model", type="virtio")
            ET.SubElement(devices, "console", type="pty")
            domain = conn.defineXML(ET.tostring(root, encoding="unicode"))
            if domain is None:
                raise HTTPException(503, "libvirt rejected the runtime definition.")
            domain.create()
        return {"accepted": True, "runtime_id": name, "disk_uri": disk.as_uri()}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "libvirt could not restore the environment.") from exc
    finally:
        conn.close()


@app.get("/agent/v1/runtimes/{runtime_id}")
def verify_runtime(runtime_id: str, x_apolo_agent_token: str | None = Header(default=None)):
    _authorize(x_apolo_agent_token)
    if not re.fullmatch(r"apolo-[a-f0-9]{8,48}", runtime_id):
        raise HTTPException(400, "Invalid runtime identifier.")
    conn = provider._connection()
    try:
        try:
            domain = conn.lookupByName(runtime_id)
        except Exception as exc:
            raise HTTPException(404, "Runtime not found.") from exc
        state = int(domain.state()[0])
        xml = ET.fromstring(domain.XMLDesc(0))
        disk_source = xml.find("./devices/disk/source")
        disk_uri = Path(disk_source.get("file", "")).resolve().as_uri() if disk_source is not None and disk_source.get("file") else None
        return {"runtime_id": runtime_id, "state": "running" if state == 1 else "stopped", "disk_uri": disk_uri}
    finally:
        conn.close()


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
