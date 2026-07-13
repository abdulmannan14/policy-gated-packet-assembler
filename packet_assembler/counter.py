"""Atomic, concurrency-safe sequence counter backed by SQLite.

The packet_id format is BAP-YYYYMMDD-NNN. NNN is an atomic per-day sequence
number. It is stored in SQLite (not derived from time or randomness) so that
two overlapping executions can never mint the same NNN.

Concurrency model
-----------------
We use SQLite in autocommit mode (``isolation_level=None``) and open an
explicit ``BEGIN IMMEDIATE`` transaction around the read-modify-write. An
IMMEDIATE transaction acquires a RESERVED lock up-front, so only one writer
can be inside the critical section at a time; any competing process blocks
(honouring the connection ``timeout``) and retries rather than reading a stale
value. This makes "SELECT current, then write current+1" safe across processes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# How long a competing writer will wait for the RESERVED lock before raising
# "database is locked", in seconds.
_LOCK_TIMEOUT_SECONDS = 30.0


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        db_path,
        timeout=_LOCK_TIMEOUT_SECONDS,
        isolation_level=None,  # autocommit; we manage transactions explicitly
    )
    # WAL lets readers proceed while a writer holds the lock and generally
    # improves concurrent behaviour. It is a persistent property of the DB file.
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS packet_counter (
            day INTEGER PRIMARY KEY,   -- YYYYMMDD
            seq INTEGER NOT NULL       -- last-issued sequence for that day
        )
        """
    )
    return conn


def next_sequence(db_path: Path, day: str) -> int:
    """Atomically return the next sequence number for ``day`` (an 8-char
    YYYYMMDD string). The first call for a given day returns 1.

    The read-modify-write runs inside an IMMEDIATE transaction, so concurrent
    callers are serialised and can never receive the same value.
    """
    day_key = int(day)
    conn = _connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT seq FROM packet_counter WHERE day = ?", (day_key,)
        ).fetchone()
        if row is None:
            seq = 1
            conn.execute(
                "INSERT INTO packet_counter (day, seq) VALUES (?, ?)",
                (day_key, seq),
            )
        else:
            seq = row[0] + 1
            conn.execute(
                "UPDATE packet_counter SET seq = ? WHERE day = ?", (seq, day_key)
            )
        conn.execute("COMMIT")
        return seq
    except Exception:
        conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
