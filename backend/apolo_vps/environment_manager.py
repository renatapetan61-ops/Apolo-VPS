from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone


class EnvironmentStore:
    """Durable metadata for runtime requests; VM disks must live in external storage."""

    STATES = {"waiting_capacity", "provisioning", "running", "stopped", "recovering", "failed"}

    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("APOLO_STATE_DB", "apolo-vps-state.sqlite3")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS environments (
                    id TEXT PRIMARY KEY,
                    vps_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    state TEXT NOT NULL,
                    vcpus INTEGER NOT NULL,
                    memory_mib INTEGER NOT NULL,
                    disk_gib INTEGER NOT NULL,
                    disk_uri TEXT,
                    runtime_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_error TEXT
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS idx_environments_vps ON environments(vps_id)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=20)

    def request(self, *, vps_id: str, provider: str, vcpus: int,
                memory_mib: int, disk_gib: int) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": "env-" + uuid.uuid4().hex,
            "vps_id": vps_id,
            "provider": provider,
            "state": "waiting_capacity",
            "vcpus": vcpus,
            "memory_mib": memory_mib,
            "disk_gib": disk_gib,
            "disk_uri": None,
            "runtime_id": None,
            "created_at": now,
            "updated_at": now,
            "last_error": None,
        }
        with self.connect() as db:
            db.execute("""
                INSERT INTO environments
                (id,vps_id,provider,state,vcpus,memory_mib,disk_gib,disk_uri,runtime_id,created_at,updated_at,last_error)
                VALUES (:id,:vps_id,:provider,:state,:vcpus,:memory_mib,:disk_gib,:disk_uri,:runtime_id,:created_at,:updated_at,:last_error)
            """, record)
        return record

    def list(self, vps_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            if vps_id:
                rows = db.execute("SELECT * FROM environments WHERE vps_id=? ORDER BY created_at DESC", (vps_id,))
            else:
                rows = db.execute("SELECT * FROM environments ORDER BY created_at DESC")
            return [dict(row) for row in rows]

    def transition(self, environment_id: str, state: str, *, disk_uri: str | None = None,
                   runtime_id: str | None = None, last_error: str | None = None) -> dict | None:
        if state not in self.STATES:
            raise ValueError("Unsupported environment state.")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            current = db.execute("SELECT * FROM environments WHERE id=?", (environment_id,)).fetchone()
            if current is None:
                return None
            # A runtime cannot be marked active without a durable disk reference.
            if state in {"running", "stopped", "recovering"} and not (disk_uri or current["disk_uri"]):
                raise ValueError("A durable external disk_uri is required before activating an environment.")
            db.execute("""
                UPDATE environments SET state=?, disk_uri=COALESCE(?,disk_uri),
                    runtime_id=COALESCE(?,runtime_id), updated_at=?, last_error=?
                WHERE id=?
            """, (state, disk_uri, runtime_id, now, last_error, environment_id))
            return dict(db.execute("SELECT * FROM environments WHERE id=?", (environment_id,)).fetchone())
