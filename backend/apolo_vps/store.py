from __future__ import annotations

import os
import sqlite3
from pathlib import Path


class InstanceStore:
    def __init__(self, path: str | None = None):
        self.path = path or os.getenv("APOLO_STATE_DB", "apolo-vps-state.sqlite3")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS instances (
                id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, username TEXT NOT NULL,
                os TEXT NOT NULL, ipv4 TEXT NOT NULL, ipv6 TEXT NOT NULL,
                location TEXT NOT NULL DEFAULT 'unassigned',
                state TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
            columns = {row[1] for row in db.execute("PRAGMA table_info(instances)")}
            if "location" not in columns:
                db.execute("ALTER TABLE instances ADD COLUMN location TEXT NOT NULL DEFAULT 'unassigned'")

    def connect(self):
        return sqlite3.connect(self.path, timeout=20)

    def save(self, record: dict) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO instances(id,name,username,os,ipv4,ipv6,location,state)
                VALUES(?,?,?,?,?,?,?,?)""",
                (record["id"], record["name"], record["username"], record["os"],
                 record["ipv4"], record["ipv6"], record.get("location", "unassigned"),
                 record.get("state", "running")))

    def list(self) -> list[dict]:
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(
                "SELECT id,name,username,os,ipv4,ipv6,location,state,created_at FROM instances ORDER BY created_at DESC"
            )]

    def delete(self, instance_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM instances WHERE id=?", (instance_id,))

    def get_by_name(self, name: str) -> dict | None:
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            row = db.execute("SELECT * FROM instances WHERE name=?", (name,)).fetchone()
            return dict(row) if row else None
