# Minimal Policy-Gated Packet Assembler

A small Python CLI that ingests a YAML component definition, assembles a
"micro-packet", runs it through an explicit policy gate, and either emits a
signed (SHA-256 hashed) packet or a structured JSON rejection.

It is a simplified stand-in for a Build Machine step: read a spec artefact,
enforce policy, and produce an integrity-hashed record.

---

## Requirements

- Python **3.10+** (developed and tested on 3.12)
- **PyYAML** (only third-party dependency)
- `sqlite3` — bundled with the Python standard library, nothing to install

## Setup

```bash
# from the project root
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt      # just PyYAML
```

(or simply `pip install pyyaml`).

## Usage

The tool is a runnable module:

```bash
python -m packet_assembler <path-to-component.yaml> [--db packet_counter.db]
```

- Accepted packet → packet JSON (with `packet_hash`) on stdout, **exit 0**
- Rejected packet → structured JSON listing every failing rule, **exit 1**
- Bad input (missing file / invalid YAML) → JSON error, **exit 2**

The `--db` flag chooses where the atomic counter lives (default
`packet_counter.db` in the working directory).

### Run all five specification tests

```bash
./run_tests.sh
```

This resets the counter DB, runs Tests 1–4 against the shared counter, and runs
Test 5 against a dedicated fresh DB so the sequence starts cleanly at `-001`.

---

## Pipeline

```
YAML file
   │  parsing.py      → load + structural validation (has a `component` mapping)
   ▼
component dict
   │  packet.py       → assemble packet; packet_id from atomic SQLite counter
   ▼
packet dict
   │  policy.py       → 7 named rule functions, each returns pass/fail + reason
   ▼
pass? ──no──► structured JSON rejection, exit 1
   │yes
   ▼
packet.py           → SHA-256 over canonical (sorted-key) JSON = packet_hash
   ▼
signed packet JSON, exit 0
```

Module responsibilities are intentionally separated:

| Module        | Responsibility                                             |
|---------------|------------------------------------------------------------|
| `parsing.py`  | Read YAML, confirm structural shape only                   |
| `counter.py`  | Atomic, concurrency-safe per-day sequence number in SQLite |
| `packet.py`   | Assemble packet, canonical JSON, SHA-256 hashing           |
| `policy.py`   | Seven individually-named policy rule functions             |
| `cli.py`      | Orchestrate the pipeline and own exit codes                |

---

## The policy rules

Each is a named function in `policy.py` returning a `RuleResult(rule, passed,
reason)`. All rules run every time (no short-circuit) so a single run reports
**all** violations at once.

| Rule      | Checks                                                                        |
|-----------|-------------------------------------------------------------------------------|
| RULE-001  | `component_id` present and matches `C-NNN` (3-digit)                           |
| RULE-002  | `release` is exactly `Release1-MVP`                                            |
| RULE-003  | `owns` non-empty and free of `TBD` / `TODO`                                    |
| RULE-004  | `does_not_own` non-empty and not the literal `None`                            |
| RULE-005  | `fail_closed_behaviour` non-empty and contains rejected/blocked/denied/refused |
| RULE-006  | `acceptance_tests` is a non-empty list                                        |
| RULE-007  | `assembled_at` is a valid ISO 8601 UTC timestamp ending in `Z`                |

---

## Test outputs

Produced by `./run_tests.sh`. Hashes and timestamps below are from a sample run
and will differ on yours (the hash is deterministic *for a given packet*, but
`assembled_at` changes each run, which changes the hash — see Design decisions).

### Test 1 — valid C-007 → all rules pass, exit 0

```json
{
  "acceptance_tests": [
    "AT-REQ-001",
    "AT-REQ-002",
    "AT-REQ-004"
  ],
  "assembled_at": "2026-07-13T04:14:27Z",
  "assembler_version": "test-assembler-v0.1",
  "component_id": "C-007",
  "component_name": "Sentinel Request Gateway",
  "cr_authority": "BFS-SPEC-003 Section 4.2",
  "does_not_own": "Downstream service routing, payload transformation, response caching",
  "fail_closed_behaviour": "If the gateway is unavailable, all inbound requests are rejected with HTTP 503. No requests are passed downstream without gateway validation.",
  "owns": "Inbound request authentication, rate limiting, structured request logging",
  "packet_hash": "8a014c296b4ad794ae9e09f1cfea5185b2ad1053b367de1ff8652a4cfadf54a1",
  "packet_id": "BAP-20260713-001",
  "release": "Release1-MVP",
  "zones": [
    "Zone-External"
  ]
}
```
exit code: **0**

### Test 2 — `does_not_own: "None"` → RULE-004 fails, exit 1

```json
{
  "status": "rejected",
  "packet_id": "BAP-20260713-002",
  "failures": [
    {
      "rule": "RULE-004",
      "reason": "does_not_own is 'None'; every component must state explicit non-responsibilities."
    }
  ]
}
```
exit code: **1**

### Test 3 — `acceptance_tests: []` → RULE-006 fails, exit 1

```json
{
  "status": "rejected",
  "packet_id": "BAP-20260713-003",
  "failures": [
    {
      "rule": "RULE-006",
      "reason": "acceptance_tests must be a non-empty list; a component with no acceptance tests cannot be assembled."
    }
  ]
}
```
exit code: **1**

### Test 4 — `release: "Release2"` → RULE-002 fails, exit 1

```json
{
  "status": "rejected",
  "packet_id": "BAP-20260713-004",
  "failures": [
    {
      "rule": "RULE-002",
      "reason": "release must be exactly 'Release1-MVP', got 'Release2'."
    }
  ]
}
```
exit code: **1**

### Test 5 — run Test 1 twice concurrently → consecutive IDs

Both runs are launched at the same time against one fresh counter DB:

```
run A packet_id:   "packet_id": "BAP-20260713-001",
run B packet_id:   "packet_id": "BAP-20260713-002",
```

The two IDs are distinct and consecutive. As a stronger check, launching **50**
concurrent processes against one DB yields **50 unique packet IDs** (sequence
1–50, no duplicates and no gaps) — evidence the counter is genuinely atomic
under contention.

---

## Design decisions

- **Atomic counter via `BEGIN IMMEDIATE`.** `counter.py` opens SQLite in
  autocommit mode and wraps the read-modify-write in an `IMMEDIATE`
  transaction, which takes a RESERVED lock up front. Only one writer can be in
  the critical section at a time; competitors block (up to a 30s busy timeout)
  and retry rather than reading a stale value. This is why two overlapping runs
  can never mint the same `NNN`. WAL mode is enabled for better concurrent
  behaviour. I deliberately avoided `RETURNING` so the code runs on older
  bundled SQLite builds too.

- **Per-day sequence.** `NNN` is keyed by the `YYYYMMDD` in the packet id, so it
  resets each day — matching the fact that the date is part of the id. (A global
  counter would also satisfy the tests; per-day felt more faithful to the id
  format. See Assumptions.)

- **Assemble-then-gate ordering, as specified.** The spec assigns `packet_id`
  during assembly (Step 2), *before* the policy gate (Step 3). I followed that
  literally, so a rejected packet still consumes a sequence number and the
  rejection output includes its `packet_id` for traceability. The trade-off is
  gaps in the accepted-packet sequence. See "Deliberately simplified".

- **All rules always run.** Rules never short-circuit, so one invocation
  surfaces every violation — more useful than fixing them one at a time.

- **Rules are policy functions, not a schema.** Each rule is an independently
  named, testable function returning a structured reason, per the spec's
  emphasis on explicit named checks over a schema validator.

- **Deterministic hashing.** `packet_hash` is SHA-256 over the canonical JSON
  (`sort_keys=True`, tight separators) of the packet **excluding** `packet_hash`
  itself. A consumer verifies integrity by dropping `packet_hash` and
  re-hashing. Sorting keys makes the bytes — and therefore the hash —
  independent of field insertion order. This is the "why" of integrity hashing:
  it lets any downstream step detect tampering without trusting the transport.

- **Missing YAML fields become `None`, not exceptions.** Assembly is tolerant so
  that the policy gate can report a precise, structured reason for a missing
  field rather than the tool crashing.

- **Exit codes.** `0` accepted, `1` policy rejection, `2` usage/ingestion error
  — so the tool composes cleanly in a build pipeline.

## Assumptions

- **Counter scope is per-day.** If a global monotonic counter is preferred,
  it's a one-line change in `counter.py` (key on a constant instead of the day).
- **`assembled_at` at second precision** is sufficient for an ISO-8601-UTC-`Z`
  timestamp; sub-second precision wasn't required by RULE-007.
- **`component.id` may be unquoted in YAML** (`C-007` parses as a string) —
  handled without special casing.
- The counter DB path is a runtime concern, so it's a CLI flag rather than
  hard-coded, and it lives outside version control (`.gitignore`).

## Deliberately simplified

- **Rejected packets still consume a sequence number.** Following the spec's
  assemble→gate ordering, the `packet_id` is minted before the gate runs. In a
  real system I'd likely *reserve* the id only after the gate passes (or record
  rejections separately) to avoid gaps in the accepted sequence. I kept the
  spec's ordering and documented the trade-off rather than silently deviating.
- **Signing is a hash, not a real signature.** Per the spec, this simulates
  Sigstore with a SHA-256 integrity hash rather than a cryptographic signature
  over a key. The hashing is implemented correctly and deterministically; only
  the key/attestation infrastructure is out of scope.
- **No automated unit-test suite.** `run_tests.sh` exercises the five specified
  cases end-to-end (including real concurrency). Given the 2–4h envelope I
  prioritised a clean, well-separated implementation and the specified tests
  over a parallel pytest suite; the rule functions are pure and trivially
  unit-testable if desired.

---

## Time

- **Started:** 2026-07-13, 09:05 (PKT, UTC+05:00)
- **Submitted:** 2026-07-13, 12:20 (PKT, UTC+05:00)
- **Total time:** ~3 hours 15 minutes
- **Straightforward:** module separation, the policy rules, deterministic
  hashing, and the CLI wiring.
- **Harder than expected:** getting the atomic counter genuinely correct under
  concurrent processes (not just threads) — reasoning about SQLite lock modes
  and confirming with a 50-process stress test rather than assuming it worked.
