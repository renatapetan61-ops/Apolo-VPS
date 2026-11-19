from apolo_vps.environment_manager import EnvironmentStore


def test_environment_request_is_durable_and_waits_for_capacity(tmp_path):
    path = str(tmp_path / "state.sqlite3")
    store = EnvironmentStore(path)
    created = store.request(vps_id="vm-123", provider="github-codespaces",
                            vcpus=2, memory_mib=2048, disk_gib=30)
    assert created["state"] == "waiting_capacity"
    assert created["disk_uri"] is None

    reopened = EnvironmentStore(path)
    assert reopened.list("vm-123")[0]["id"] == created["id"]


def test_environment_cannot_be_marked_running_without_external_disk(tmp_path):
    store = EnvironmentStore(str(tmp_path / "state.sqlite3"))
    created = store.request(vps_id="vm-123", provider="external-host",
                            vcpus=2, memory_mib=2048, disk_gib=30)
    try:
        store.transition(created["id"], "running", runtime_id="runtime-1")
    except ValueError as exc:
        assert "durable external disk_uri" in str(exc)
    else:
        raise AssertionError("An environment without durable storage must not become running.")


def test_environment_transition_requires_durable_disk_and_persists_it(tmp_path):
    store = EnvironmentStore(str(tmp_path / "state.sqlite3"))
    created = store.request(vps_id="vm-123", provider="external-host",
                            vcpus=2, memory_mib=2048, disk_gib=30)
    updated = store.transition(created["id"], "running",
                               disk_uri="s3://apolo-vps/vm-123/root.qcow2",
                               runtime_id="runtime-1")
    assert updated["state"] == "running"
    assert updated["disk_uri"] == "s3://apolo-vps/vm-123/root.qcow2"
