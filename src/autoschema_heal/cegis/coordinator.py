"""
CEGIS Loop Coordinator and State Machine.

Orchestrates the inductive synthesis loop between:
Synthesizer <---> Formal Verifier <---> Adversarial Fuzzer <---> Audit Logger
"""

from __future__ import annotations
import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from autoschema_heal.formal.schema import TargetSchema
from autoschema_heal.formal.invariants import InvariantVerifier, VerificationOracle
from autoschema_heal.fuzzer.property_fuzzer import PropertyFuzzer
from autoschema_heal.synthesis.synthesizer import CEGISSynthesizer
from autoschema_heal.synthesis.llm_client import BaseLLMClient
from autoschema_heal.cegis.audit import RoundAudit, VerificationCertificate, generate_certificate


@dataclass
class CEGISResult:
    success: bool
    synthesized_program: Optional[str] = None
    rounds_taken: int = 0
    certificate: Optional[VerificationCertificate] = None
    error_message: Optional[str] = None


class CEGISCoordinator:
    """
    Manages the Counterexample-Guided Inductive Synthesis loop.
    """

    def __init__(
        self,
        target_schema: TargetSchema,
        llm_client: BaseLLMClient,
        max_rounds: int = 5,
        fuzzer_cases_per_round: int = 30,
        retention_threshold: float = 0.70,
        entropy_threshold: Optional[float] = None,
    ) -> None:
        self.target_schema = target_schema
        self.llm_client = llm_client
        self.max_rounds = max_rounds
        self.fuzzer_cases = fuzzer_cases_per_round
        
        effective_threshold = entropy_threshold if entropy_threshold is not None else retention_threshold
        self.verifier = InvariantVerifier(
            target_schema=self.target_schema,
            retention_threshold=effective_threshold,
        )
        self.oracle = self.verifier  # Backwards compatibility alias
        self.fuzzer = PropertyFuzzer(
            verifier=self.verifier,
            fuzzer_cases=self.fuzzer_cases,
        )

    def run_cegis(self, drift_payload: Dict[str, Any], fingerprint: str) -> CEGISResult:
        """
        Executes the iterative CEGIS loop until a certified sound program is synthesized
        or max_rounds is exhausted.
        """
        synthesizer = CEGISSynthesizer(self.llm_client, self.target_schema)
        rounds_audit: List[RoundAudit] = []

        for round_idx in range(1, self.max_rounds + 1):
            # 1. Untrusted Synthesis Step
            valid_syntax, candidate_jq, syntax_err = synthesizer.synthesize(drift_payload)
            if not valid_syntax:
                # Syntax failed before evaluation
                rounds_audit.append(
                    RoundAudit(
                        round_number=round_idx,
                        candidate_program=candidate_jq,
                        program_hash="syntax_error",
                        verifier_passed=False,
                        fuzzer_passed=False,
                        fuzzer_cases_tested=0,
                        failure_reason=f"JQ Syntax Error: {syntax_err}",
                    )
                )
                synthesizer.record_counterexample(
                    round_num=round_idx,
                    candidate_code=candidate_jq,
                    counterexample_input=drift_payload,
                    invariant_failed="I_syntax",
                    error_message=f"Syntax Error: {syntax_err}",
                )
                continue

            prog_hash = hashlib.sha256(candidate_jq.encode("utf-8")).hexdigest()[:12]

            # 2. Formal Invariants Verification on Drift Sample
            verifier_passed, results = self.verifier.evaluate_all(candidate_jq, drift_payload)
            if not verifier_passed:
                failed_res = next(r for r in results if not r.passed)
                rounds_audit.append(
                    RoundAudit(
                        round_number=round_idx,
                        candidate_program=candidate_jq,
                        program_hash=prog_hash,
                        verifier_passed=False,
                        fuzzer_passed=False,
                        fuzzer_cases_tested=0,
                        failure_reason=failed_res.error_message,
                        counterexample=drift_payload,
                    )
                )
                synthesizer.record_counterexample(
                    round_num=round_idx,
                    candidate_code=candidate_jq,
                    counterexample_input=drift_payload,
                    invariant_failed=failed_res.invariant_name,
                    error_message=failed_res.error_message or "Unknown verification error",
                )
                continue

            # 3. Adversarial Property Fuzzing Check
            fuzz_result = self.fuzzer.fuzz_candidate(candidate_jq, drift_payload)
            if not fuzz_result.survived:
                rounds_audit.append(
                    RoundAudit(
                        round_number=round_idx,
                        candidate_program=candidate_jq,
                        program_hash=prog_hash,
                        verifier_passed=True,
                        fuzzer_passed=False,
                        fuzzer_cases_tested=fuzz_result.cases_tested,
                        failure_reason=fuzz_result.violation_reason,
                        counterexample=fuzz_result.counterexample,
                    )
                )
                synthesizer.record_counterexample(
                    round_num=round_idx,
                    candidate_code=candidate_jq,
                    counterexample_input=fuzz_result.counterexample,
                    invariant_failed=fuzz_result.invariant_failed or "I_fuzz",
                    error_message=fuzz_result.violation_reason or "Fuzzer invariant violation",
                )
                continue

            # If we reached here: candidate passed Formal Verifier AND survived Adversarial Fuzzer!
            rounds_audit.append(
                RoundAudit(
                    round_number=round_idx,
                    candidate_program=candidate_jq,
                    program_hash=prog_hash,
                    verifier_passed=True,
                    fuzzer_passed=True,
                    fuzzer_cases_tested=fuzz_result.cases_tested,
                )
            )

            cert = generate_certificate(
                fingerprint=fingerprint,
                final_program=candidate_jq,
                rounds_audit=rounds_audit,
                certified_sound=True,
            )
            return CEGISResult(
                success=True,
                synthesized_program=candidate_jq,
                rounds_taken=round_idx,
                certificate=cert,
            )

        # Max rounds exhausted
        failed_cert = generate_certificate(
            fingerprint=fingerprint,
            final_program=candidate_jq,
            rounds_audit=rounds_audit,
            certified_sound=False,
        )
        return CEGISResult(
            success=False,
            rounds_taken=self.max_rounds,
            certificate=failed_cert,
            error_message=f"CEGIS loop failed to converge within {self.max_rounds} rounds.",
        )
