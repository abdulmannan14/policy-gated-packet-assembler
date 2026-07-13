"""Policy gate.

Each rule is an individual named function that inspects the assembled packet
and returns a :class:`RuleResult`. This is deliberately *not* a schema
validator: the rules encode business policy, must be individually auditable,
and each carries a human-readable reason on failure.

``evaluate_all`` runs every rule (it does not short-circuit) so that a single
run reports *all* violations at once.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

# Substrings that mark an "unfinished" ownership statement (RULE-003).
_PLACEHOLDER_TOKENS = ("TBD", "TODO")

# Words that indicate a fail-closed behaviour actually describes rejection of
# requests (RULE-005). Matched case-insensitively on word boundaries.
_FAIL_CLOSED_KEYWORDS = ("rejected", "blocked", "denied", "refused")

_COMPONENT_ID_RE = re.compile(r"^C-\d{3}$")


@dataclass(frozen=True)
class RuleResult:
    rule: str
    passed: bool
    reason: str


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


# --------------------------------------------------------------------------- #
# Individual policy rules                                                      #
# --------------------------------------------------------------------------- #

def rule_001_component_id_format(packet: dict[str, Any]) -> RuleResult:
    """component_id must be present and match C-NNN (3-digit number)."""
    value = packet.get("component_id")
    if not _is_nonempty_str(value):
        return RuleResult("RULE-001", False, "component_id is missing or empty.")
    if not _COMPONENT_ID_RE.match(value):
        return RuleResult(
            "RULE-001",
            False,
            f"component_id '{value}' does not match required format C-NNN "
            "(e.g. C-007).",
        )
    return RuleResult("RULE-001", True, "component_id present and well-formed.")


def rule_002_release_exact(packet: dict[str, Any]) -> RuleResult:
    """release must be exactly 'Release1-MVP'."""
    value = packet.get("release")
    if value != "Release1-MVP":
        return RuleResult(
            "RULE-002",
            False,
            f"release must be exactly 'Release1-MVP', got {value!r}.",
        )
    return RuleResult("RULE-002", True, "release is 'Release1-MVP'.")


def rule_003_owns_present(packet: dict[str, Any]) -> RuleResult:
    """owns must be non-empty and must not contain 'TBD' or 'TODO'."""
    value = packet.get("owns")
    if not _is_nonempty_str(value):
        return RuleResult("RULE-003", False, "owns is missing or empty.")
    upper = value.upper()
    for token in _PLACEHOLDER_TOKENS:
        if token in upper:
            return RuleResult(
                "RULE-003",
                False,
                f"owns contains placeholder text '{token}'.",
            )
    return RuleResult("RULE-003", True, "owns is present and contains no placeholders.")


def rule_004_does_not_own_present(packet: dict[str, Any]) -> RuleResult:
    """does_not_own must be non-empty; the literal 'None' is not acceptable."""
    value = packet.get("does_not_own")
    if not _is_nonempty_str(value):
        return RuleResult("RULE-004", False, "does_not_own is missing or empty.")
    if value.strip().lower() == "none":
        return RuleResult(
            "RULE-004",
            False,
            "does_not_own is 'None'; every component must state explicit "
            "non-responsibilities.",
        )
    return RuleResult("RULE-004", True, "does_not_own states explicit non-responsibilities.")


def rule_005_fail_closed_describes_rejection(packet: dict[str, Any]) -> RuleResult:
    """fail_closed_behaviour must be non-empty and describe request rejection."""
    value = packet.get("fail_closed_behaviour")
    if not _is_nonempty_str(value):
        return RuleResult(
            "RULE-005", False, "fail_closed_behaviour is missing or empty."
        )
    lower = value.lower()
    if not any(
        re.search(rf"\b{keyword}\b", lower) for keyword in _FAIL_CLOSED_KEYWORDS
    ):
        return RuleResult(
            "RULE-005",
            False,
            "fail_closed_behaviour must describe what happens to requests on "
            "failure (one of: rejected, blocked, denied, refused).",
        )
    return RuleResult(
        "RULE-005", True, "fail_closed_behaviour describes request rejection."
    )


def rule_006_acceptance_tests_present(packet: dict[str, Any]) -> RuleResult:
    """acceptance_tests must be a non-empty list."""
    value = packet.get("acceptance_tests")
    if not isinstance(value, list) or len(value) == 0:
        return RuleResult(
            "RULE-006",
            False,
            "acceptance_tests must be a non-empty list; a component with no "
            "acceptance tests cannot be assembled.",
        )
    return RuleResult("RULE-006", True, "acceptance_tests is a non-empty list.")


def rule_007_assembled_at_iso_utc(packet: dict[str, Any]) -> RuleResult:
    """assembled_at must be a valid ISO 8601 UTC timestamp ending in 'Z'."""
    value = packet.get("assembled_at")
    if not _is_nonempty_str(value):
        return RuleResult("RULE-007", False, "assembled_at is missing or empty.")
    if not value.endswith("Z"):
        return RuleResult(
            "RULE-007", False, "assembled_at must be UTC and end in 'Z'."
        )
    try:
        # datetime.fromisoformat handles the trailing 'Z' from Python 3.11+.
        # We normalise 'Z' -> '+00:00' for broad compatibility, then confirm UTC.
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return RuleResult(
            "RULE-007", False, f"assembled_at '{value}' is not a valid ISO 8601 timestamp."
        )
    if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
        return RuleResult("RULE-007", False, "assembled_at is not in UTC.")
    return RuleResult("RULE-007", True, "assembled_at is a valid ISO 8601 UTC timestamp.")


# Ordered registry of all policy rules.
ALL_RULES: tuple[Callable[[dict[str, Any]], RuleResult], ...] = (
    rule_001_component_id_format,
    rule_002_release_exact,
    rule_003_owns_present,
    rule_004_does_not_own_present,
    rule_005_fail_closed_describes_rejection,
    rule_006_acceptance_tests_present,
    rule_007_assembled_at_iso_utc,
)


def evaluate_all(packet: dict[str, Any]) -> list[RuleResult]:
    """Run every rule (no short-circuit) and return all results in order."""
    return [rule(packet) for rule in ALL_RULES]


def failures(results: list[RuleResult]) -> list[RuleResult]:
    return [r for r in results if not r.passed]
