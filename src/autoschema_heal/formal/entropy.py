"""
Compatibility bridge redirecting to data_integrity.py.
"""

from autoschema_heal.formal.data_integrity import (
    DEFAULT_FALLBACK_VALUES,
    extract_leaves,
    are_scalars_semantically_linked,
    DataIntegrityVerifier,
    DataIntegrityOracle,
    EntropyPreservationOracle,
)

__all__ = [
    "DEFAULT_FALLBACK_VALUES",
    "extract_leaves",
    "are_scalars_semantically_linked",
    "DataIntegrityVerifier",
    "DataIntegrityOracle",
    "EntropyPreservationOracle",
]
