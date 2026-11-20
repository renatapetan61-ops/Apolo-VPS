import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from apolo_vps import agent


def test_environment_disk_uses_shared_backing_image_and_verifies_chain(tmp_path, monkeypatch):
    root = tmp_path / "nfs"
    root.mkdir()
    base = root / "ubuntu-cloud.img"
    base.write_bytes(b"base")
    monkeypatch.setattr(agent, "_authorize", lambda token: None)
    monkeypatch.setattr(agent, "_persistent_root", lambda: root)
    monkeypatch.setenv("APOLO_ENVIRONMENT_BASE_IMAGE", str(base))
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[1:3] == ["info", "--output=json"] and args[-1] == str(base):
            return type("Result", (), {"stdout": json.dumps({"format": "raw"})})()
        if args[1] == "create":
            Path(args[-2]).touch()
            return type("Result", (), {"stdout": ""})()
        if args[1:3] == ["info", "--output=json"]:
            return type("Result", (), {"stdout": json.dumps({
                "format": "qcow2",
                "virtual-size": 20 * 1024 ** 3,
                "backing-filename": str(base),
            })})()
        raise AssertionError(args)

    monkeypatch.setattr(agent.subprocess, "run", fake_run)
    payload = agent.DiskRequest(environment_id="environment-123", vps_id="vm-123", size_gib=20)
    result = agent.ensure_disk(payload, x_apolo_agent_token="test")

    assert result["durable"] is True
    assert result["storage_type"] == "nfs"
    assert Path(result["disk_uri"].removeprefix("file://")).is_file()
    create = next(args for args in calls if args[1] == "create")
    assert create[create.index("-F") + 1] == "raw"
    assert create[create.index("-b") + 1] == str(base)


def test_environment_disk_rejects_base_image_outside_shared_mount(tmp_path, monkeypatch):
    root = tmp_path / "nfs"
    root.mkdir()
    outside = tmp_path / "local-base.qcow2"
    outside.write_bytes(b"not shared")
    monkeypatch.setattr(agent, "_authorize", lambda token: None)
    monkeypatch.setattr(agent, "_persistent_root", lambda: root)
    monkeypatch.setenv("APOLO_ENVIRONMENT_BASE_IMAGE", str(outside))

    payload = agent.DiskRequest(environment_id="environment-456", vps_id="vm-456", size_gib=20)
    with pytest.raises(HTTPException) as exc:
        agent.ensure_disk(payload, x_apolo_agent_token="test")
    assert exc.value.status_code == 503
