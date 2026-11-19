from apolo_vps.environment_manager import EnvironmentStore
from apolo_vps.environment_worker import EnvironmentWorker


class FakeProvider:
    def __init__(self, capacity=None, disk=None, started=None, observed=None):
        self.capacity_data = capacity or {
            "state": "ok", "authorized": True, "available_vcpus": 8,
            "available_memory_mib": 8192, "available_disk_gib": 500,
        }
        self.disk = disk or {"durable": True, "disk_uri": "s3://apolo/vm/root.qcow2"}
        self.started = started or {"accepted": True, "runtime_id": "runtime-42"}
        self.observed = observed or {"state": "running", "disk_uri": "s3://apolo/vm/root.qcow2"}

    def capacity(self): return self.capacity_data
    def ensure_disk(self, job): return self.disk
    def restore(self, job, disk_uri): return self.started
    def verify_runtime(self, runtime_id): return self.observed


def create_job(store, provider="libvirt-agent"):
    return store.request(vps_id="vm-1234", provider=provider, vcpus=2,
                         memory_mib=2048, disk_gib=30)


def test_worker_only_marks_running_after_runtime_and_disk_are_verified(tmp_path):
    store = EnvironmentStore(str(tmp_path / "state.sqlite3"))
    job = create_job(store)
    result = EnvironmentWorker(store, {"libvirt-agent": FakeProvider()}).process_once()
    assert result["verified"] is True
    saved = store.get(job["id"])
    assert saved["state"] == "running"
    assert saved["runtime_id"] == "runtime-42"
    assert saved["disk_uri"] == "s3://apolo/vm/root.qcow2"


def test_worker_fails_closed_when_provider_not_allowlisted(tmp_path):
    store = EnvironmentStore(str(tmp_path / "state.sqlite3"))
    job = create_job(store, "github-codespaces")
    result = EnvironmentWorker(store, {}).process_once()
    assert result["verified"] is False
    assert store.get(job["id"])["state"] == "failed"


def test_worker_requeues_when_capacity_is_insufficient(tmp_path):
    store = EnvironmentStore(str(tmp_path / "state.sqlite3"))
    job = create_job(store)
    provider = FakeProvider(capacity={
        "state": "ok", "authorized": True, "available_vcpus": 1,
        "available_memory_mib": 8192, "available_disk_gib": 500,
    })
    result = EnvironmentWorker(store, {"libvirt-agent": provider}).process_once()
    assert result["verified"] is False
    assert store.get(job["id"])["state"] == "waiting_capacity"


def test_worker_does_not_mark_running_when_runtime_verification_fails(tmp_path):
    store = EnvironmentStore(str(tmp_path / "state.sqlite3"))
    job = create_job(store)
    provider = FakeProvider(observed={"state": "stopped", "disk_uri": "s3://apolo/vm/root.qcow2"})
    result = EnvironmentWorker(store, {"libvirt-agent": provider}).process_once()
    assert result["verified"] is False
    assert store.get(job["id"])["state"] == "failed"


def test_store_claims_job_only_once(tmp_path):
    store = EnvironmentStore(str(tmp_path / "state.sqlite3"))
    create_job(store)
    first = store.claim_next()
    second = store.claim_next()
    assert first is not None
    assert second is None


def test_worker_reclaims_expired_provisioning_lease(tmp_path):
    store = EnvironmentStore(str(tmp_path / "state.sqlite3"))
    job = create_job(store)
    first = store.claim_next(lease_seconds=1)
    assert first is not None
    with store.connect() as db:
        db.execute("UPDATE environments SET lease_until='2000-01-01T00:00:00+00:00' WHERE id=?", (job["id"],))
    reclaimed = store.claim_next()
    assert reclaimed is not None
    assert reclaimed["id"] == job["id"]
    assert reclaimed["attempts"] == 2
