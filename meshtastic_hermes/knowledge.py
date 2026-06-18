"""Node-interaction knowledge base (SQLite).

Records *metadata* for every packet observed on the mesh — including encrypted
packets on private channels, which are NEVER decrypted. By tracking who
transmits, who they address, on which channel, with what signal quality and hop
count, the agent can infer the structure and activity of the mesh without ever
reading message contents it isn't entitled to.

This module is intentionally pure/standalone: it depends only on the stdlib and
takes plain dicts as input, so it can be unit-tested without a radio attached.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path
from typing import Any

# Sentinel for the broadcast address used by Meshtastic.
BROADCAST_ID = "^all"


def default_db_path() -> str:
    """Resolve the knowledge-base path, in priority order:

    1. ``MESHTASTIC_HERMES_DB`` — explicit override.
    2. ``STATE_DIRECTORY`` — set automatically by systemd for units declaring
       ``StateDirectory=`` (the common NixOS deployment). The service user's
       ``$HOME`` is frequently non-writable there (DynamicUser, ProtectHome,
       ``/var/empty``), whereas the state directory is guaranteed writable and
       persistent. systemd may pass a colon-separated list; use the first entry.
    3. ``~/.hermes/meshtastic_kb.sqlite`` — the interactive/desktop default.
    """
    env = os.environ.get("MESHTASTIC_HERMES_DB")
    if env:
        return env
    state_dir = os.environ.get("STATE_DIRECTORY")
    if state_dir:
        return str(Path(state_dir.split(":", 1)[0]) / "meshtastic_kb.sqlite")
    return str(Path.home() / ".hermes" / "meshtastic_kb.sqlite")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id     TEXT PRIMARY KEY,
    num         INTEGER,
    short_name  TEXT,
    long_name   TEXT,
    hw_model    TEXT,
    role        TEXT,
    first_seen  REAL,
    last_seen   REAL,
    last_snr    REAL,
    last_rssi   REAL,
    last_hops   INTEGER,
    lat         REAL,
    lon         REAL,
    battery     INTEGER,
    packets     INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS interactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ts            REAL,
    from_node     TEXT,
    to_node       TEXT,
    channel       INTEGER,
    portnum       TEXT,
    encrypted     INTEGER,
    hop_limit     INTEGER,
    rx_snr        REAL,
    rx_rssi       REAL,
    payload_size  INTEGER
);

CREATE INDEX IF NOT EXISTS idx_inter_from ON interactions(from_node);
CREATE INDEX IF NOT EXISTS idx_inter_to   ON interactions(to_node);
CREATE INDEX IF NOT EXISTS idx_inter_ts   ON interactions(ts);
"""


class NodeGraph:
    """Persistent store of mesh nodes and the interactions observed between them."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or default_db_path()
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False: meshtastic delivers packets on a background
        # thread while tool handlers query from the main thread. A lock guards
        # all access.
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def upsert_node(self, node_id: str, ts: float, **fields: Any) -> None:
        """Insert or update a node row, only overwriting columns that are provided."""
        if not node_id:
            return
        cols = {k: v for k, v in fields.items() if v is not None}
        with self._lock:
            cur = self._conn.execute("SELECT node_id FROM nodes WHERE node_id = ?", (node_id,))
            exists = cur.fetchone() is not None
            if not exists:
                self._conn.execute(
                    "INSERT INTO nodes (node_id, first_seen, last_seen) VALUES (?, ?, ?)",
                    (node_id, ts, ts),
                )
            assignments = ["last_seen = ?"]
            values: list[Any] = [ts]
            for col, val in cols.items():
                assignments.append(f"{col} = ?")
                values.append(val)
            values.append(node_id)
            self._conn.execute(
                f"UPDATE nodes SET {', '.join(assignments)} WHERE node_id = ?", values
            )
            self._conn.commit()

    def record_packet(self, meta: dict[str, Any]) -> None:
        """Record one observed packet's metadata and bump sender stats.

        `meta` keys (all optional except from_node/ts):
            ts, from_node, to_node, channel, portnum, encrypted (bool),
            hop_limit, rx_snr, rx_rssi, payload_size
        """
        ts = meta.get("ts", 0.0)
        from_node = meta.get("from_node") or ""
        to_node = meta.get("to_node") or BROADCAST_ID
        with self._lock:
            self._conn.execute(
                """INSERT INTO interactions
                   (ts, from_node, to_node, channel, portnum, encrypted,
                    hop_limit, rx_snr, rx_rssi, payload_size)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    ts,
                    from_node,
                    to_node,
                    meta.get("channel"),
                    meta.get("portnum"),
                    1 if meta.get("encrypted") else 0,
                    meta.get("hop_limit"),
                    meta.get("rx_snr"),
                    meta.get("rx_rssi"),
                    meta.get("payload_size"),
                ),
            )
            self._conn.commit()
        # Keep a lightweight rollup on the sender node (own lock acquisition).
        if from_node:
            self.upsert_node(
                from_node,
                ts,
                last_snr=meta.get("rx_snr"),
                last_rssi=meta.get("rx_rssi"),
                last_hops=meta.get("hop_limit"),
            )
            with self._lock:
                self._conn.execute(
                    "UPDATE nodes SET packets = packets + 1 WHERE node_id = ?", (from_node,)
                )
                self._conn.commit()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def nodes(self, limit: int = 100, sort: str = "last_seen") -> list[dict[str, Any]]:
        order = {
            "last_seen": "last_seen DESC",
            "first_seen": "first_seen ASC",
            "packets": "packets DESC",
            "name": "long_name ASC",
        }.get(sort, "last_seen DESC")
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM nodes ORDER BY {order} LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def interactions(
        self, node_id: str | None = None, since: float | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        clauses, params = [], []
        if node_id:
            clauses.append("(from_node = ? OR to_node = ?)")
            params += [node_id, node_id]
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM interactions {where} ORDER BY ts DESC LIMIT ?", params
            ).fetchall()
        return [dict(r) for r in rows]

    def neighbors(self, node_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Inferred direct contacts: counterpart nodes this node exchanged packets with."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT peer, COUNT(*) AS count, MAX(ts) AS last_ts FROM (
                    SELECT to_node   AS peer, ts FROM interactions WHERE from_node = ?
                    UNION ALL
                    SELECT from_node AS peer, ts FROM interactions WHERE to_node   = ?
                )
                WHERE peer != '' AND peer != ?
                GROUP BY peer ORDER BY count DESC LIMIT ?
                """,
                (node_id, node_id, node_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def top_talkers(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT from_node AS node_id, COUNT(*) AS count
                   FROM interactions WHERE from_node != ''
                   GROUP BY from_node ORDER BY count DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            node_count = self._conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            packet_count = self._conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
            encrypted = self._conn.execute(
                "SELECT COUNT(*) FROM interactions WHERE encrypted = 1"
            ).fetchone()[0]
            channels = self._conn.execute(
                "SELECT COUNT(DISTINCT channel) FROM interactions WHERE channel IS NOT NULL"
            ).fetchone()[0]
        return {
            "db_path": self.db_path,
            "nodes": node_count,
            "packets": packet_count,
            "encrypted_packets": encrypted,
            "decoded_packets": packet_count - encrypted,
            "channels_seen": channels,
            "top_talkers": self.top_talkers(5),
        }
