from __future__ import annotations

import os
import re
import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


class ProviderUnavailable(RuntimeError):
    pass


class LibvirtProvider:
    """Local KVM/libvirt adapter. Run this service only on a secured hypervisor."""

    def __init__(self, uri: str | None = None):
        self.uri = uri or os.getenv("APOLO_LIBVIRT_URI", "qemu:///system")

    def _connection(self):
        try:
            import libvirt  # type: ignore
        except ImportError as exc:
            raise ProviderUnavailable("Install the OS package for python3-libvirt on the hypervisor.") from exc
        conn = libvirt.open(self.uri)
        if conn is None:
            raise ProviderUnavailable(f"Could not connect to libvirt URI {self.uri}.")
        return conn

    def hypervisor_info(self) -> dict[str, Any]:
        conn = self._connection()
        try:
            info = conn.getInfo()
            return {
                "uri": self.uri,
                "hostname": conn.getHostname(),
                "model": info[0],
                "memory_kib": info[1],
                "cpus": info[2],
                "mhz": info[3],
                "nodes": info[4],
                "sockets": info[5],
                "cores": info[6],
                "threads": info[7],
                "libvirt_version": conn.getLibVersion(),
                "qemu_version": conn.getVersion(),
            }
        finally:
            conn.close()

    def list_domains(self) -> list[dict]:
        conn = self._connection()
        try:
            records = []
            for domain in conn.listAllDomains(0):
                records.append({
                    "id": str(domain.UUIDString()),
                    "name": domain.name(),
                    "state": int(domain.state()[0]),
                    "memory_kib": int(domain.info()[1]),
                    "vcpus": int(domain.info()[3]),
                })
            return records
        finally:
            conn.close()

    def lifecycle(self, name: str, action: str) -> dict:
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,62}", name):
            raise ValueError("Invalid domain name.")
        conn = self._connection()
        try:
            domain = conn.lookupByName(name)
            if action == "start":
                domain.create()
            elif action == "shutdown":
                domain.shutdown()
            elif action == "reboot":
                domain.reboot(0)
            elif action == "destroy":
                domain.destroy()
            elif action == "delete":
                domain_xml = ET.fromstring(domain.XMLDesc(0))
                if domain.isActive():
                    domain.destroy()
                domain.undefineFlags(0)
                storage_root = Path(os.getenv("APOLO_VM_STORAGE", "/var/lib/libvirt/images/apolo-vps")).resolve()
                for source in domain_xml.findall(".//devices/disk/source"):
                    disk_file = source.get("file")
                    if not disk_file:
                        continue
                    candidate = Path(disk_file).resolve()
                    if candidate.parent == storage_root and candidate.name.startswith("vm-"):
                        candidate.unlink(missing_ok=True)
            else:
                raise ValueError("Unsupported lifecycle action.")
            return {"name": name, "action": action, "state": int(domain.state()[0]) if action != "delete" else "undefined"}
        finally:
            conn.close()

    def define_domain(self, *, name: str, memory_mib: int, vcpus: int, disk_path: str,
                      image_path: str, bridge: str, cloud_init_iso: str, disk_gib: int = 20) -> dict:
        """Create a domain from prevalidated local paths and an operator bridge."""
        for value in (name, bridge):
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{1,62}", value):
                raise ValueError("Invalid domain or bridge identifier.")
        for candidate in (disk_path, image_path, cloud_init_iso):
            if not Path(candidate).is_file():
                raise ProviderUnavailable(f"Required image/disk file does not exist: {candidate}")
        qemu_img = os.getenv("APOLO_QEMU_IMG", "qemu-img")
        image_info = subprocess.run([qemu_img, "info", "--output=json", image_path],
                                   check=True, capture_output=True, text=True, timeout=30)
        image_format = json.loads(image_info.stdout).get("format")
        if image_format not in {"qcow2", "raw"}:
            raise ProviderUnavailable("Guest base image must be QCOW2 or raw.")
        subprocess.run([qemu_img, "create", "-f", "qcow2", "-F", image_format, "-b", image_path, disk_path, f"{disk_gib}G"],
                       check=True, capture_output=True, text=True, timeout=120)
        root = ET.Element("domain", type="kvm")
        ET.SubElement(root, "name").text = name
        ET.SubElement(root, "memory", unit="MiB").text = str(memory_mib)
        ET.SubElement(root, "vcpu").text = str(vcpus)
        os_node = ET.SubElement(root, "os")
        ET.SubElement(os_node, "type", arch="x86_64", machine="q35").text = "hvm"
        ET.SubElement(root, "features")
        devices = ET.SubElement(root, "devices")
        ET.SubElement(devices, "emulator").text = os.getenv("APOLO_QEMU_EMULATOR", "/usr/bin/qemu-system-x86_64")
        disk = ET.SubElement(devices, "disk", type="file", device="disk")
        ET.SubElement(disk, "driver", name="qemu", type="qcow2")
        ET.SubElement(disk, "source", file=disk_path)
        ET.SubElement(disk, "target", dev="vda", bus="virtio")
        nic = ET.SubElement(devices, "interface", type="bridge")
        ET.SubElement(nic, "source", bridge=bridge)
        ET.SubElement(nic, "model", type="virtio")
        cdrom = ET.SubElement(devices, "disk", type="file", device="cdrom")
        ET.SubElement(cdrom, "driver", name="qemu", type="raw")
        ET.SubElement(cdrom, "source", file=cloud_init_iso)
        ET.SubElement(cdrom, "target", dev="sda", bus="sata")
        ET.SubElement(cdrom, "readonly")
        ET.SubElement(devices, "console", type="pty")
        xml = ET.tostring(root, encoding="unicode")
        conn = self._connection()
        try:
            domain = conn.defineXML(xml)
            if domain is None:
                raise ProviderUnavailable("libvirt rejected the domain definition.")
            domain.create()
            return {"id": domain.UUIDString(), "name": domain.name(), "state": int(domain.state()[0])}
        finally:
            conn.close()
