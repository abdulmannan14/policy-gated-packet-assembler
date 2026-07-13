"""Command-line entry point.

Orchestrates the pipeline: ingest -> assemble -> policy gate -> sign/output.

Exit codes:
    0  packet accepted and emitted (with packet_hash)
    1  packet rejected by the policy gate
    2  usage / ingestion error (bad path, invalid YAML, ...)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .packet import assemble_packet, hash_packet
from .parsing import IngestionError, load_component
from .policy import evaluate_all, failures

DEFAULT_DB_PATH = Path("packet_counter.db")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="packet-assembler",
        description="Assemble a policy-gated, hashed micro-packet from a YAML "
        "component definition.",
    )
    parser.add_argument("input", type=Path, help="Path to the component YAML file.")
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to the SQLite counter database "
        f"(default: {DEFAULT_DB_PATH}).",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ---- Ingest ---------------------------------------------------------- #
    try:
        component = load_component(args.input)
    except IngestionError as exc:
        json.dump({"status": "error", "error": str(exc)}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 2

    # ---- Assemble -------------------------------------------------------- #
    packet = assemble_packet(component, args.db)

    # ---- Policy gate ----------------------------------------------------- #
    results = evaluate_all(packet)
    failed = failures(results)

    if failed:
        error_output = {
            "status": "rejected",
            "packet_id": packet["packet_id"],
            "failures": [{"rule": r.rule, "reason": r.reason} for r in failed],
        }
        json.dump(error_output, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 1

    # ---- Sign & output --------------------------------------------------- #
    packet_hash = hash_packet(packet)
    signed = dict(packet)
    signed["packet_hash"] = packet_hash

    # Emit deterministically (sorted keys) so output is stable and diff-able.
    # Note the hash is computed over the packet *without* packet_hash, so
    # a consumer recomputes it by dropping packet_hash and re-hashing.
    json.dump(signed, sys.stdout, sort_keys=True, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
