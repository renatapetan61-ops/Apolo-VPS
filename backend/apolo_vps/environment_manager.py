from __future__ import annotations

import os
import sqlite3
import uuid
from pathlib import Path
from datetime import datetime, timezone


class EnvironmentStore:
    """Durable runtime metadata. VM disk bytes must be stored by an external storage provider."""

    STATES = {"waiting_capacity", "provisioning", "running", "stopped", "recovering", "failed"}

    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("APOLO_STATE_DB", "apolo-vps-state.sqlite3")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS environments (
                    id TEXT PRIMARY KEY, vps_id TEXT NOT NULL, provider TEXT NOT NULL,
                    state TEXT NOT NULL, vcpus INTEGER NOT NULL, memory_mib INTEGER NOT NULL,
                    disk_gib INTEGER NOT NULL, disk_uri TEXT, runtime_id TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0, lease_until TEXT
                )
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(environments)")}
            if "attempts" not in columns:
                db.execute("ALTER TABLE environments ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0")
            if "lease_until" not in columns:
                db.execute("ALTER TABLE environments ADD COLUMN lease_until TEXT")
            db.execute("CREATE INDEX IF NOT EXISTS idx_environments_vps ON environments(vps_id)")
            db.execute("CREATE INDEX IF NOT EXISTS idx_environments_state ON environments(state,created_at)")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=20000")
        return db

    def request(self, *, vps_id: str, provider: str, vcpus: int,
                memory_mib: int, disk_gib: int) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        record = {
            "id": "env-" + uuid.uuid4().hex, "vps_id": vps_id, "provider": provider,
            "state": "waiting_capacity", "vcpus": vcpus, "memory_mib": memory_mib,
            "disk_gib": disk_gib, "disk_uri": None, "runtime_id": None,
            "created_at": now, "updated_at": now, "last_error": None,
            "attempts": 0, "lease_until": None,
        }
        with self.connect() as db:
            db.execute("""
                INSERT INTO environments
                (id,vps_id,provider,state,vcpus,memory_mib,disk_gib,disk_uri,runtime_id,
                 created_at,updated_at,last_error,attempts,lease_until)
                VALUES (:id,:vps_id,:provider,:state,:vcpus,:memory_mib,:disk_gib,:disk_uri,:runtime_id,
                        :created_at,:updated_at,:last_error,:attempts,:lease_until)
            """, record)
        return record

    def list(self, vps_id: str | None = None) -> list[dict]:
        with self.connect() as db:
            if vps_id:
                rows = db.execute("SELECT * FROM environments WHERE vps_id=? ORDER BY created_at DESC", (vps_id,))
            else:
                rows = db.execute("SELECT * FROM environments ORDER BY created_at DESC")
            return [dict(row) for row in rows]

    def get(self, environment_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM environments WHERE id=?", (environment_id,)).fetchone()
            return dict(row) if row else None

    def claim_next(self, lease_seconds: int = 180) -> dict | None:
        """Atomically claim one queued/recovering job; expired worker leases are reclaimable."""
        now = datetime.now(timezone.utc)
        now_s = now.isoformat()
        lease_s = datetime.fromtimestamp(now.timestamp() + lease_seconds, timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("""
                SELECT * FROM environments
                WHERE state IN ('waiting_capacity','recovering')
                  AND (lease_until IS NULL OR lease_until < ?)
                ORDER BY created_at LIMIT 1
            """, (now_s,)).fetchone()
            if row is None:
                return None
            changed = db.execute("""
                UPDATE environments SET state='provisioning', lease_until=?, updated_at=?,
                    attempts=attempts+1, last_error=NULL
                WHERE id=? AND state IN ('waiting_capacity','recovering')
                  AND (lease_until IS NULL OR lease_until < ?)
            """, (lease_s, now_s, row["id"], now_s)).rowcount
            if changed != 1:
                return None
            claimed = db.execute("SELECT * FROM environments WHERE id=?", (row["id"],)).fetchone()
            return dict(claimed)

    def transition(self, environment_id: str, state: str, *, disk_uri: str | None = None,
                   runtime_id: str | None = None, last_error: str | None = None) -> dict | None:
        if state not in self.STATES:
            raise ValueError("Unsupported environment state.")
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            current = db.execute("SELECT * FROM environments WHERE id=?", (environment_id,)).fetchone()
            if current is None:
                return None
            if state in {"running", "stopped", "recovering"} and not (disk_uri or current["disk_uri"]):
                raise ValueError("A durable external disk_uri is required before activating an environment.")
            db.execute("""
                UPDATE environments SET state=?, disk_uri=COALESCE(?,disk_uri),
                    runtime_id=COALESCE(?,runtime_id), updated_at=?, last_error=?, lease_until=NULL
                WHERE id=?
            """, (state, disk_uri, runtime_id, now, last_error, environment_id))
            row = db.execute("SELECT * FROM environments WHERE id=?", (environment_id,)).fetchone()
            return dict(row)
