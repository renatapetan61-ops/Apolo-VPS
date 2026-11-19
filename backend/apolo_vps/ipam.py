from __future__ import annotations

import ipaddress
import os
import sqlite3
from pathlib import Path


class IPAMError(RuntimeError):
    pass


class IPAllocator:
    """SQLite-backed allocator for operator-configured, routable address pools.

    No pool is inferred. The operator must supply CIDRs, gateways and bridge
    configuration that their upstream provider has authorized.
    """

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.getenv("APOLO_STATE_DB", "apolo-vps-state.sqlite3")
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS allocations (
                instance_id TEXT PRIMARY KEY,
                ipv4 TEXT UNIQUE,
                ipv6 TEXT UNIQUE,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=15)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    @staticmethod
    def _pool(name: str, version: int):
        raw = os.getenv(name)
        if not raw:
            raise IPAMError(f"{name} is not configured; no public IP can be assigned.")
        try:
            network = ipaddress.ip_network(raw, strict=True)
        except ValueError as exc:
            raise IPAMError(f"{name} is not a valid network CIDR.") from exc
        if network.version != version or not network.is_global:
            raise IPAMError(f"{name} must be an operator-authorized global IPv{version} network.")
        return network

    def allocate(self, instance_id: str) -> tuple[str, str]:
        v4 = self._pool("APOLO_IPV4_CIDR", 4)
        v6 = self._pool("APOLO_IPV6_CIDR", 6)
        with self._connect() as db:
            if db.execute("SELECT 1 FROM allocations WHERE instance_id=?", (instance_id,)).fetchone():
                raise IPAMError("Instance already has an address allocation.")
            used4 = {r[0] for r in db.execute("SELECT ipv4 FROM allocations WHERE ipv4 IS NOT NULL")}
            used6 = {r[0] for r in db.execute("SELECT ipv6 FROM allocations WHERE ipv6 IS NOT NULL")}
            reserved4 = set() if v4.prefixlen >= 31 else {str(v4.network_address), str(v4.broadcast_address)}
            reserved6 = set() if v6.prefixlen == 128 else {str(v6.network_address)}
            candidates4 = [v4.network_address] if v4.prefixlen == 32 else v4.hosts()
            candidates6 = [v6.network_address] if v6.prefixlen == 128 else v6.hosts()
            ip4 = next((str(ip) for ip in candidates4 if str(ip) not in used4 and str(ip) not in reserved4), None)
            ip6 = next((str(ip) for ip in candidates6 if str(ip) not in used6 and str(ip) not in reserved6), None)
            if not ip4 or not ip6:
                raise IPAMError("The configured IPv4 or IPv6 pool is exhausted.")
            db.execute("INSERT INTO allocations(instance_id, ipv4, ipv6) VALUES (?, ?, ?)", (instance_id, ip4, ip6))
            return ip4, ip6

    def release(self, instance_id: str) -> None:
        with self._connect() as db:
            db.execute("DELETE FROM allocations WHERE instance_id=?", (instance_id,))
