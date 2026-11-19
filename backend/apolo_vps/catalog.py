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


_IMAGE_DEFS = (
    ("ubuntu-24.04", "Ubuntu 24.04 LTS", "linux", "24.04", "cloud-init", "APOLO_IMAGE_UBUNTU_2404"),
    ("debian-12", "Debian 12", "linux", "12", "cloud-init", "APOLO_IMAGE_DEBIAN_12"),
    ("rocky-9", "Rocky Linux 9", "linux", "9", "cloud-init", "APOLO_IMAGE_ROCKY_9"),
    ("windows-server-2022", "Windows Server 2022", "windows", "2022", "windows-unattend", "APOLO_IMAGE_WINDOWS_2022"),
)


def list_images() -> list[dict]:
    result = []
    for image_id, name, family, version, provisioner, env_name in _IMAGE_DEFS:
        raw_path = os.getenv(env_name)
        path = str(Path(raw_path).expanduser().resolve()) if raw_path else None
        valid = bool(path and Path(path).is_file())
        windows_ready = family != "windows" or bool(os.getenv("APOLO_WINDOWS_TEMPLATE"))
        enabled = valid and windows_ready
        note = "Verified local image file." if enabled else (
            "Windows requires a prepared unattended/RDP template." if family == "windows" and valid
            else f"Set {env_name} to an existing, licensed image file."
        )
        result.append(asdict(Image(
            id=image_id, name=name, family=family, version=version,
            architecture="x86_64", path=path, provisioner=provisioner,
            enabled=enabled, note=note,
        )))
    return result


def get_image(image_id: str) -> dict | None:
    return next((item for item in list_images() if item["id"] == image_id), None)
