"""
Adversarial Mutation Operators for AST Property Fuzzing.

Implements boundary-value and domain perturbations within the structural
equivalence class E_phi(x) defined by the payload's AST fingerprint:
- Temporal domains (epoch sec vs ms, ISO8601 variations, leap dates, overflows)
- Numeric limits (IEEE 754 precision, signed 64-bit bounds, float/int shifts, zeros)
- Unicode & character torture (null bytes, emojis, RTL scripts, whitespace, escaping)
- Nullability and schema pollution (null substitution, extra metadata keys)
"""

from __future__ import annotations
import copy
import random
from typing import Any, Callable, Dict, List, Tuple


def mutate_temporal(val: Any) -> List[Any]:
    """Generates temporal boundary variations from an input scalar."""
    mutations: List[Any] = []
    if isinstance(val, (int, float)):
        epoch = float(val)
        mutations.append(0)  # Unix epoch base 1970-01-01
        mutations.append(int(epoch * 1000))  # Convert sec to ms (the classic drift failure)
        mutations.append(int(epoch / 1000) if epoch > 1000 else 0)  # ms to sec
        mutations.append(2147483647)  # Y2038 32-bit signed overflow
        mutations.append(32503680000)  # Year 3000
    elif isinstance(val, str):
        # String date mutations
        mutations.append("1970-01-01T00:00:00Z")
        mutations.append("2038-01-19T03:14:07Z")
        mutations.append("2026-10-06T12:00:00.123456Z")  # Microsecond ISO
        mutations.append("2026-10-06T12:00:00+05:30")  # Offset ISO
        mutations.append("2026-10-06 12:00:00")  # Space separator
        mutations.append("2026-10-06")  # Date only
    return mutations


def mutate_numeric(val: Any) -> List[Any]:
    """Generates numerical boundary values."""
    mutations: List[Any] = []
    if isinstance(val, (int, float)):
        mutations.append(0)
        mutations.append(0.0)
        mutations.append(-abs(val))  # Negative value
        mutations.append(9007199254740991)  # Number.MAX_SAFE_INTEGER
        mutations.append(1e-5)  # Precision limits
    return mutations


def mutate_strings(val: Any) -> List[Any]:
    """Generates string torture tests (Unicode, null-bytes, empty values)."""
    mutations: List[Any] = []
    if isinstance(val, str):
        mutations.append("")  # Empty
        mutations.append("   ")  # Whitespace only
        mutations.append(f"{val}\x00poison")  # Null-byte injection
        mutations.append(f"{val} 🎉 🚀")  # Multi-byte UTF-8 Emojis
        mutations.append(f"مرحبا_{val}")  # Arabic RTL
        mutations.append(f"'{val}'; DROP TABLE logs; --")  # Injection characters
    return mutations


def collect_payload_paths(obj: Any, prefix: Tuple[Any, ...] = ()) -> List[Tuple[Tuple[Any, ...], Any]]:
    """Recursively walks an object and collects all leaf paths and values."""
    results: List[Tuple[Tuple[Any, ...], Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            results.extend(collect_payload_paths(v, prefix + (k,)))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            results.extend(collect_payload_paths(item, prefix + (idx,)))
    else:
        results.append((prefix, obj))
    return results


def set_at_path(obj: Any, path: Tuple[Any, ...], new_val: Any) -> Any:
    """Sets a value at the given nested tuple path in a copied structure."""
    if not path:
        return new_val
    obj = copy.deepcopy(obj)
    curr = obj
    for step in path[:-1]:
        curr = curr[step]
    curr[path[-1]] = new_val
    return obj


def generate_adversarial_mutations(base_payload: Dict[str, Any], count: int = 40) -> List[Dict[str, Any]]:
    """
    Generates a suite of adversarially mutated payloads derived from base_payload,
    exploring the boundary space of the structural equivalence class E_phi(base).
    """
    mutated_suite: List[Dict[str, Any]] = []
    leaves = collect_payload_paths(base_payload)
    if not leaves:
        return [base_payload]

    # 1. Single-leaf boundary value perturbations
    for path, val in leaves:
        candidates = []
        candidates.extend(mutate_temporal(val))
        candidates.extend(mutate_numeric(val))
        candidates.extend(mutate_strings(val))
        # Nullability test
        candidates.append(None)

        for candidate_val in candidates:
            try:
                mutated = set_at_path(base_payload, path, candidate_val)
                mutated_suite.append(mutated)
            except Exception:
                continue

    # 2. Schema pollution test (unexpected extra metadata key)
    polluted = copy.deepcopy(base_payload)
    polluted["__upstream_canary_field__"] = "unexpected_metadata_drift"
    mutated_suite.append(polluted)

    # Dedup and shuffle
    random.seed(42)
    random.shuffle(mutated_suite)
    return mutated_suite[:count]
