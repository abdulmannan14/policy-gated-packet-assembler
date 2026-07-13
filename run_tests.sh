#!/usr/bin/env bash
# Runs all five specification test cases and prints their output + exit code.
# Usage: ./run_tests.sh
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

DB="packet_counter.db"
PY="${PYTHON:-python3}"

# Start from a clean counter so packet_id sequences are reproducible.
rm -f "$DB" "$DB"-wal "$DB"-shm

run() {
    local title="$1"; shift
    echo "=================================================================="
    echo "$title"
    echo "------------------------------------------------------------------"
    "$PY" -m packet_assembler "$@" --db "$DB"
    echo "exit code: $?"
    echo
}

run "TEST 1 - valid C-007 (expect: all rules pass, packet + hash, exit 0)" \
    examples/c007.yaml

run "TEST 2 - does_not_own = 'None' (expect: RULE-004 fails, exit 1)" \
    examples/c007_none.yaml

run "TEST 3 - acceptance_tests = [] (expect: RULE-006 fails, exit 1)" \
    examples/c007_empty_tests.yaml

run "TEST 4 - release = 'Release2' (expect: RULE-002 fails, exit 1)" \
    examples/c007_release2.yaml

echo "=================================================================="
echo "TEST 5 - concurrency: run Test 1 twice at once (expect: -001 then -002)"
echo "------------------------------------------------------------------"
# Use a dedicated, fresh counter DB so the demonstration starts at 001 (tests
# 1-4 above already advanced the shared counter). Launch both runs
# concurrently to genuinely exercise the atomic counter under contention.
DB5="packet_counter_test5.db"
rm -f "$DB5" "$DB5"-wal "$DB5"-shm
"$PY" -m packet_assembler examples/c007.yaml --db "$DB5" > /tmp/pa_run_a.json 2>&1 &
PID_A=$!
"$PY" -m packet_assembler examples/c007.yaml --db "$DB5" > /tmp/pa_run_b.json 2>&1 &
PID_B=$!
wait "$PID_A"; wait "$PID_B"
echo "run A packet_id: $(grep packet_id /tmp/pa_run_a.json | head -1)"
echo "run B packet_id: $(grep packet_id /tmp/pa_run_b.json | head -1)"
echo "(the two ids must differ and be consecutive: -001 and -002)"
rm -f "$DB5" "$DB5"-wal "$DB5"-shm
echo
