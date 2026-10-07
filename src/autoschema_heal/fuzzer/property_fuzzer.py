"""
Adversarial Differential Property Fuzzer.

Subjects candidate JQ programs to a battery of mutated inputs.
Extracts minimal counterexamples on invariant violations to drive the CEGIS loop.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from autoschema_heal.formal.invariants import InvariantVerifier, VerificationOracle
from autoschema_heal.fuzzer.mutators import generate_adversarial_mutations
from autoschema_heal.fuzzer.shrinker import CounterexampleShrinker


@dataclass(frozen=True)
class FuzzResult:
    survived: bool
    cases_tested: int
    counterexample: Optional[Any] = None
    violation_reason: Optional[str] = None
    invariant_failed: Optional[str] = None


class PropertyFuzzer:
    """
    Orchestrates property-based fuzzing and delta-debugging extraction.
    """

    def __init__(
        self,
        verifier: Optional[InvariantVerifier] = None,
        fuzzer_cases: int = 40,
        oracle: Optional[VerificationOracle] = None,
    ) -> None:
        self.verifier = verifier or oracle
        if self.verifier is None:
            raise ValueError("Must provide an InvariantVerifier instance.")
        self.oracle = self.verifier  # Backwards compatibility alias
        self.fuzzer_cases = fuzzer_cases

    def fuzz_candidate(self, jq_source: str, base_payload: Dict[str, Any]) -> FuzzResult:
        """
        Executes adversarial fuzz suite against candidate JQ source.
        Returns FuzzResult with minimal counterexample upon violation.
        """
        mutated_suite = generate_adversarial_mutations(base_payload, count=self.fuzzer_cases)
        cases_tested = 0

        for mutant in mutated_suite:
            cases_tested += 1
            passed, results = self.verifier.evaluate_all(jq_source, mutant)
            if not passed:
                # Invariant violated! Find the first failed invariant
                failed = next(r for r in results if not r.passed)
                inv_name = failed.invariant_name
                err_msg = failed.error_message

                # Define failure predicate for delta-debugging
                def failure_predicate(test_payload: Any) -> Tuple[bool, Optional[str]]:
                    p, res = self.verifier.evaluate_all(jq_source, test_payload)
                    if p:
                        return True, None
                    f = next(r for r in res if not r.passed)
                    return False, f.error_message

                # Shrink counterexample to minimal reproducible form
                shrinker = CounterexampleShrinker(failure_predicate)
                shrunk_payload, shrunk_err = shrinker.shrink(mutant)

                return FuzzResult(
                    survived=False,
                    cases_tested=cases_tested,
                    counterexample=shrunk_payload,
                    violation_reason=shrunk_err or err_msg,
                    invariant_failed=inv_name,
                )

        return FuzzResult(
            survived=True,
            cases_tested=cases_tested,
        )
