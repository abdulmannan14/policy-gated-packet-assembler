"""Packet assembly and integrity hashing.

Assembly is kept separate from policy evaluation: this module only *builds* the
packet from parsed component data. Whether that packet is acceptable is decided
later by the policy gate.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .counter import next_sequence

ASSEMBLER_VERSION = "test-assembler-v0.1"


def _utc_now_iso_z() -> str:
    """Current UTC time as an ISO 8601 string ending in 'Z' (second precision)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_packet_id(db_path: Path, now: datetime | None = None) -> str:
    """Build a packet id of the form BAP-YYYYMMDD-NNN.

    NNN is an atomic per-day sequence pulled from SQLite (see counter.py). It is
    zero-padded to at least three digits and never reused within a day.
    """
    now = now or datetime.now(timezone.utc)
    day = now.strftime("%Y%m%d")
    seq = next_sequence(db_path, day)
    return f"BAP-{day}-{seq:03d}"


def assemble_packet(component: dict[str, Any], db_path: Path) -> dict[str, Any]:
    """Assemble a packet dict from a parsed component mapping.

    Missing YAML keys are surfaced as ``None`` rather than raising, so that the
    policy gate can report a precise, structured reason for each missing field.
    """
    now = datetime.now(timezone.utc)
    return {
        "packet_id": make_packet_id(db_path, now),
        "component_id": component.get("id"),
        "component_name": component.get("name"),
        "release": component.get("release"),
        "owns": component.get("owns"),
        "does_not_own": component.get("does_not_own"),
        "fail_closed_behaviour": component.get("fail_closed_behaviour"),
        "cr_authority": component.get("cr_authority"),
        "zones": component.get("zones"),
        "acceptance_tests": component.get("acceptance_tests"),
        "assembled_at": _utc_now_iso_z(),
        "assembler_version": ASSEMBLER_VERSION,
    }


def canonical_json(packet: dict[str, Any]) -> str:
    """Deterministic JSON encoding used both for hashing and for output.

    Keys are sorted so the same packet always produces the same bytes (and thus
    the same hash) regardless of insertion order.
    """
    return json.dumps(packet, sort_keys=True, separators=(",", ":"))


def hash_packet(packet: dict[str, Any]) -> str:
    """SHA-256 hex digest of the canonical packet JSON.

    This simulates the signing/integrity step: any downstream consumer can
    recompute this hash over the packet body and detect tampering. The hash is
    computed over the packet *without* the packet_hash field, so it stays a
    pure function of the packet content.
    """
    return hashlib.sha256(canonical_json(packet).encode("utf-8")).hexdigest()
