from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Image:
    id: str
    name: str
    family: str
    version: str
    architecture: str
    path: str | None
    provisioner: str
    enabled: bool
    note: str


# An image is enabled only when the current host agent can provision it safely.
# Windows and ARM64 remain visible as planned catalog entries, but fail closed
# until their architecture-specific firmware, devices and unattended installer
# have been implemented and validated on a real hypervisor.
_IMAGE_DEFS = (
    ("ubuntu-24.04", "Ubuntu 24.04 LTS", "linux", "24.04", "x86_64", "cloud-init", "APOLO_IMAGE_UBUNTU_2404"),
    ("debian-12", "Debian 12", "linux", "12", "x86_64", "cloud-init", "APOLO_IMAGE_DEBIAN_12"),
    ("rocky-9", "Rocky Linux 9", "linux", "9", "x86_64", "cloud-init", "APOLO_IMAGE_ROCKY_9"),
    ("ubuntu-24.04-arm64", "Ubuntu 24.04 LTS ARM64", "linux", "24.04", "aarch64", "cloud-init-arm64", "APOLO_IMAGE_UBUNTU_2404_ARM64"),
    ("debian-12-arm64", "Debian 12 ARM64", "linux", "12", "aarch64", "cloud-init-arm64", "APOLO_IMAGE_DEBIAN_12_ARM64"),
    ("rocky-9-arm64", "Rocky Linux 9 ARM64", "linux", "9", "aarch64", "cloud-init-arm64", "APOLO_IMAGE_ROCKY_9_ARM64"),
    ("windows-11-x64", "Windows 11 x64", "windows", "11", "x86_64", "windows-unattend-x64", "APOLO_IMAGE_WINDOWS_11_X64"),
    ("windows-10-x64", "Windows 10 x64", "windows", "10", "x86_64", "windows-unattend-x64", "APOLO_IMAGE_WINDOWS_10_X64"),
    ("windows-11-arm64", "Windows 11 ARM64", "windows", "11", "aarch64", "windows-unattend-arm64", "APOLO_IMAGE_WINDOWS_11_ARM64"),
    ("windows-10-arm64", "Windows 10 ARM64", "windows", "10", "aarch64", "windows-unattend-arm64", "APOLO_IMAGE_WINDOWS_10_ARM64"),
    ("windows-8-x64", "Windows 8 x64", "windows", "8", "x86_64", "windows-unattend-legacy", "APOLO_IMAGE_WINDOWS_8_X64"),
    ("windows-7-x64", "Windows 7 x64", "windows", "7", "x86_64", "windows-unattend-legacy", "APOLO_IMAGE_WINDOWS_7_X64"),
    # Retain the previous server image ID for API compatibility, but keep it
    # disabled until a real Windows unattended provisioner exists.
    ("windows-server-2022", "Windows Server 2022", "windows", "2022", "x86_64", "windows-unattend-x64", "APOLO_IMAGE_WINDOWS_2022"),
)


def list_images() -> list[dict]:
    result = []
    for image_id, name, family, version, architecture, provisioner, env_name in _IMAGE_DEFS:
        raw_path = os.getenv(env_name)
        path = str(Path(raw_path).expanduser().resolve()) if raw_path else None
        valid = bool(path and Path(path).is_file())

        if provisioner == "cloud-init":
            enabled = valid
            note = "Verified local image file; supported by the current x86_64 cloud-init provisioner." if enabled else f"Set {env_name} to an existing verified cloud image."
        elif provisioner == "cloud-init-arm64":
            enabled = False
            note = "ARM64 catalog entry only; requires an ARM64-aware libvirt domain, UEFI firmware and validated guest networking."
        elif family == "windows":
            enabled = False
            note = "Planned catalog entry; unavailable until its licensed image, architecture-specific drivers, unattended setup, activation and remote-console path are validated."
        else:
            enabled = False
            note = "No validated provisioner is available for this image."

        result.append(asdict(Image(
            id=image_id, name=name, family=family, version=version,
            architecture=architecture, path=path, provisioner=provisioner,
            enabled=enabled, note=note,
        )))
    return result


def get_image(image_id: str) -> dict | None:
    return next((item for item in list_images() if item["id"] == image_id), None)
