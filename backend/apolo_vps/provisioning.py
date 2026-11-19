from __future__ import annotations

import os
import re
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from .catalog import get_image
from .libvirt_provider import LibvirtProvider
from .security import generate_password, generated_hostname


class ProvisioningError(RuntimeError):
    pass


def _password_hash(password: str) -> str:
    result = subprocess.run(
        ["openssl", "passwd", "-6", "-stdin"],
        input=password, capture_output=True, text=True, check=True, timeout=15,
    )
    return result.stdout.strip()


def provision_linux(*, instance_id: str, computer_name: str | None, username: str,
                    image_id: str, ipv4: str, ipv6: str, memory_mib: int,
                    vcpus: int, disk_gib: int) -> dict:
    image = get_image(image_id)
    if not image or not image["enabled"]:
        raise ProvisioningError("The selected image is not installed and verified.")
    if image["family"] != "linux" or image["provisioner"] != "cloud-init":
        raise ProvisioningError("This guest image requires a different unattended provisioner.")
    name = computer_name or generated_hostname()
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", name):
        raise ProvisioningError("Invalid computer name.")
    bridge = os.getenv("APOLO_LIBVIRT_BRIDGE")
    if not bridge:
        raise ProvisioningError("APOLO_LIBVIRT_BRIDGE is not configured.")
    storage = Path(os.getenv("APOLO_VM_STORAGE", "/var/lib/libvirt/images/apolo-vps"))
    storage.mkdir(parents=True, exist_ok=True)
    disk_path = str(storage / f"{instance_id}.qcow2")
    seed_path = str(storage / f"{instance_id}-seed.iso")
    if Path(disk_path).exists() or Path(seed_path).exists():
        raise ProvisioningError("A VM with this internal ID already has storage files.")

    password = generate_password()
    password_hash = _password_hash(password)
    is_rocky = image_id == "rocky-9"
    guest_group = "wheel" if is_rocky else "sudo"
    packages = ["qemu-guest-agent", "firewalld"] if is_rocky else ["qemu-guest-agent", "ufw"]
    firewall_commands = (
        [["systemctl", "enable", "--now", "firewalld"],
         ["firewall-cmd", "--permanent", "--add-service=ssh"],
         ["firewall-cmd", "--reload"]]
        if is_rocky else
        [["ufw", "allow", "OpenSSH"], ["ufw", "--force", "enable"]]
    )
    user_data = {
        "hostname": name,
        "manage_etc_hosts": True,
        "users": [{
            "name": username,
            "groups": [guest_group],
            "shell": "/bin/bash",
            "sudo": ["ALL=(ALL) NOPASSWD:ALL"],
            "lock_passwd": False,
            "passwd": password_hash,
        }],
        "ssh_pwauth": True,
        "chpasswd": {"expire": True},
        "package_update": True,
        "packages": packages,
        "runcmd": [["systemctl", "enable", "--now", "qemu-guest-agent"], *firewall_commands],
    }
    network_config = {
        "version": 2,
        "ethernets": {
            "ens3": {
                "match": {"driver": "virtio_net"},
                "set-name": "ens3",
                "dhcp4": False,
                "dhcp6": False,
                "addresses": [f"{ipv4}/{os.getenv('APOLO_GUEST_IPV4_PREFIX', '32')}",
                              f"{ipv6}/{os.getenv('APOLO_GUEST_IPV6_PREFIX', '128')}"],
                "routes": [
                    {"to": "0.0.0.0/0", "via": os.getenv("APOLO_IPV4_GATEWAY"), "on-link": True},
                    {"to": "::/0", "via": os.getenv("APOLO_IPV6_GATEWAY"), "on-link": True},
                ],
                "nameservers": {"addresses": os.getenv("APOLO_DNS_SERVERS", "1.1.1.1,2606:4700:4700::1111").split(",")},
            }
        },
    }
    if not os.getenv("APOLO_IPV4_GATEWAY") or not os.getenv("APOLO_IPV6_GATEWAY"):
        raise ProvisioningError("Both public IPv4 and IPv6 gateways must be configured.")
    with tempfile.TemporaryDirectory(prefix="apolo-cloudinit-") as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "user-data").write_text("#cloud-config\n" + yaml.safe_dump(user_data, sort_keys=False), encoding="utf-8")
        (tmp_path / "meta-data").write_text(yaml.safe_dump({"instance-id": instance_id, "local-hostname": name}), encoding="utf-8")
        (tmp_path / "network-config").write_text(yaml.safe_dump(network_config, sort_keys=False), encoding="utf-8")
        cloud_localds = shutil.which("cloud-localds")
        if not cloud_localds:
            raise ProvisioningError("Install cloud-image-utils (cloud-localds) on the hypervisor.")
        subprocess.run([cloud_localds, "--network-config", str(tmp_path / "network-config"),
                        seed_path, str(tmp_path / "user-data"), str(tmp_path / "meta-data")],
                       check=True, capture_output=True, text=True, timeout=60)
    try:
        provider = LibvirtProvider()
        result = provider.define_domain(
            name=name, memory_mib=memory_mib, vcpus=vcpus,
            disk_path=disk_path, image_path=image["path"], bridge=bridge,
            cloud_init_iso=seed_path, disk_gib=disk_gib,
        )
        return {
            **result, "computer_name": name, "username": username,
            "password": password, "ipv4": ipv4, "ipv6": ipv6,
            "os": image_id, "location": os.getenv("APOLO_HYPERVISOR_LOCATION", "configured-hypervisor"),
            "disk_gib": disk_gib, "memory_mib": memory_mib, "vcpus": vcpus,
        }
    except Exception:
        for path in (disk_path, seed_path):
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        raise
