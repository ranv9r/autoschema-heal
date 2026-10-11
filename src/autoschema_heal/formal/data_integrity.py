"""
Data Retention Checker (I_integrity).

Checks that synthesized JQ filters map output field values back to real
source data, rather than filling them with hardcoded dummy defaults or
dropping non-null fields entirely.
"""

from __future__ import annotations
import math
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple


DEFAULT_FALLBACK_VALUES: Set[Any] = {
    None,
    "",
    0,
    0.0,
    False,
    "unknown",
    "unknown@example.com",
    "1970-01-01T00:00:00Z",
    "N/A",
    "default",
    "SF_000",
    "evt_000",
}


def extract_leaves(obj: Any, prefix: Tuple[str, ...] = ()) -> List[Tuple[Tuple[str, ...], Any]]:
    """
    Extracts all scalar leaf nodes from a nested JSON structure.
    Returns list of (path_tuple, scalar_value).
    """
    leaves: List[Tuple[Tuple[str, ...], Any]] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            leaves.extend(extract_leaves(v, prefix + (str(k),)))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            leaves.extend(extract_leaves(item, prefix + (str(idx),)))
    else:
        if obj is not None and obj != "":
            leaves.append((prefix, obj))
    return leaves


def are_scalars_semantically_linked(src_val: Any, tgt_val: Any) -> bool:
    """
    Determines if a target scalar value legitimately originates from a source scalar value
    under standard data transformations (identity, stringification,
    numeric scaling like cents->dollars, or temporal conversions).
    """
    if src_val == tgt_val:
        return True

    s_str = str(src_val).strip().lower()
    t_str = str(tgt_val).strip().lower()

    if s_str == t_str:
        return True
    if len(s_str) > 3 and s_str in t_str:
        return True
    if len(t_str) > 3 and t_str in s_str:
        return True

    # Numeric equivalence or scaling (e.g., cents to dollars: 4999 -> 49.99)
    if isinstance(src_val, (int, float)) and isinstance(tgt_val, (int, float)):
        try:
            if math.isclose(float(src_val), float(tgt_val), rel_tol=1e-5):
                return True
            if math.isclose(float(src_val) / 100.0, float(tgt_val), rel_tol=1e-5):
                return True
            if math.isclose(float(src_val) * 100.0, float(tgt_val), rel_tol=1e-5):
                return True
        except (OverflowError, ValueError):
            pass

    # Temporal equivalence: Unix Epoch (sec or ms) -> ISO-8601 string
    if isinstance(src_val, (int, float)) and isinstance(tgt_val, str):
        try:
            epoch = float(src_val)
            if epoch > 1e11:  # ms
                epoch /= 1000.0
            dt = datetime.utcfromtimestamp(epoch)
            if dt.strftime("%Y-%m-%d") in tgt_val:
                return True
        except Exception:
            pass

    # Reverse temporal: ISO-8601 string -> Unix Epoch
    if isinstance(src_val, str) and isinstance(tgt_val, (int, float)):
        try:
            for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(src_val.split(".")[0].replace("Z", ""), fmt)
                    if math.isclose(dt.timestamp(), float(tgt_val), abs_tol=86400):
                        return True
                except ValueError:
                    continue
        except Exception:
            pass

    return False


class DataIntegrityVerifier:
    """
    Computes and checks the data retention ratio for a candidate JQ transformation.
    Rejects programs that fill output fields with hardcoded dummy constants
    (e.g., "unknown", 0.0) while the source payload contains real data.
    """

    def __init__(self, default_threshold: float = 0.70) -> None:
        self.default_threshold = default_threshold

    def calculate_data_retention(
        self,
        source_payload: Any,
        target_payload: Any,
        known_defaults: Optional[Set[Any]] = None,
    ) -> Tuple[float, List[Tuple[str, Any]], List[Tuple[str, Any]]]:
        """
        Computes Data Retention Ratio:
        Retention = |Matched Targets| / min(|Source Meaningful Leaves|, |Target Meaningful Leaves|)
        """
        defaults = known_defaults or DEFAULT_FALLBACK_VALUES

        src_leaves = [
            (path, val) for path, val in extract_leaves(source_payload) if val not in defaults
        ]
        tgt_leaves = [
            (path, val) for path, val in extract_leaves(target_payload) if val not in defaults
        ]

        # If source has no non-default leaves, retention is trivially satisfied
        if not src_leaves:
            return 1.0, [], []

        # If target has no non-default leaves while source had data, complete data loss!
        if not tgt_leaves:
            return 0.0, [], []

        matched_targets: List[Tuple[str, Any]] = []
        unmatched_targets: List[Tuple[str, Any]] = []
        used_src_indices: Set[int] = set()

        for tgt_path, tgt_val in tgt_leaves:
            found = False
            for src_idx, (src_path, src_val) in enumerate(src_leaves):
                if src_idx in used_src_indices:
                    continue
                if are_scalars_semantically_linked(src_val, tgt_val):
                    matched_targets.append((".".join(tgt_path), tgt_val))
                    used_src_indices.add(src_idx)
                    found = True
                    break
            if not found:
                unmatched_targets.append((".".join(tgt_path), tgt_val))

        capacity = min(len(src_leaves), len(tgt_leaves))
        retention = len(matched_targets) / capacity if capacity > 0 else 1.0
        return retention, matched_targets, unmatched_targets

    # SDE method alias
    calculate_leaf_recall = calculate_data_retention

    def verify(
        self,
        source_payload: Any,
        target_payload: Any,
        threshold: Optional[float] = None,
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Verifies invariant I_integrity (zero data loss).
        Returns (is_satisfied, retention_ratio, violation_explanation).
        """
        thresh = threshold if threshold is not None else self.default_threshold
        retention, matched, unmatched = self.calculate_data_retention(source_payload, target_payload)

        if retention >= thresh:
            return True, retention, None

        missing_fields_str = ", ".join(f"'{p}'={v}" for p, v in unmatched[:3])
        reason = (
            f"I_integrity violation: Data retention ratio {retention:.2f} < threshold {thresh:.2f}. "
            f"Target output dropped source fields or emitted ungrounded dummy values: [{missing_fields_str}]."
        )
        return False, retention, reason


# Aliases for backwards compatibility
DataIntegrityOracle = DataIntegrityVerifier
EntropyPreservationOracle = DataIntegrityVerifier
