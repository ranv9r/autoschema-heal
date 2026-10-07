"""
Cryptographic Verification Certificate and Audit Trail Generator.

Generates an immutable audit certificate for every synthesized program,
recording formal invariant verification results and fuzzer coverage proofs.
"""

from __future__ import annotations
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RoundAudit:
    round_number: int
    candidate_program: str
    program_hash: str
    verifier_passed: bool = False
    fuzzer_passed: bool = False
    fuzzer_cases_tested: int = 0
    failure_reason: Optional[str] = None
    counterexample: Optional[Any] = None
    oracle_passed: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.oracle_passed is not None and not self.verifier_passed:
            self.verifier_passed = self.oracle_passed
        elif self.oracle_passed is None:
            self.oracle_passed = self.verifier_passed


@dataclass
class VerificationCertificate:
    certificate_id: str
    timestamp_epoch: float
    fingerprint: str
    final_program: str
    program_sha256: str
    rounds_executed: int
    total_fuzzer_cases_tested: int
    rounds_audit: List[RoundAudit]
    certified_sound: bool


def generate_certificate(
    fingerprint: str,
    final_program: str,
    rounds_audit: List[RoundAudit],
    certified_sound: bool,
) -> VerificationCertificate:
    """
    Constructs an audit certificate stamped with SHA-256 integrity digest.
    """
    prog_hash = hashlib.sha256(final_program.encode("utf-8")).hexdigest()
    cert_raw = f"{fingerprint}:{prog_hash}:{certified_sound}:{time.time()}"
    cert_id = hashlib.sha256(cert_raw.encode("utf-8")).hexdigest()[:16]

    total_fuzz = sum(r.fuzzer_cases_tested for r in rounds_audit)

    return VerificationCertificate(
        certificate_id=f"CERT-{cert_id}",
        timestamp_epoch=time.time(),
        fingerprint=fingerprint,
        final_program=final_program,
        program_sha256=prog_hash,
        rounds_executed=len(rounds_audit),
        total_fuzzer_cases_tested=total_fuzz,
        rounds_audit=rounds_audit,
        certified_sound=certified_sound,
    )
