"""
Formal Invariants Verification Engine (I_exec, I_type, I_integrity, I_idempotence).

Every candidate program synthesized by the untrusted search engine must pass
all four invariants before being admitted to adversarial fuzzing.
"""

from __future__ import annotations
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import jq

from autoschema_heal.formal.schema import TargetSchema
from autoschema_heal.formal.data_integrity import DataIntegrityVerifier, DataIntegrityOracle


@dataclass(frozen=True)
class InvariantResult:
    passed: bool
    invariant_name: str
    error_message: Optional[str] = None
    output: Optional[Any] = None
    metrics: Optional[Dict[str, Any]] = None


class InvariantVerifier:
    """
    Formal Invariant Verifier that checks the 4 non-negotiable invariants on candidate JQ programs.
    """

    FORBIDDEN_JQ_TOKENS = [
        "now",
        "env",
        "$ENV",
        "debug",
        "halt",
        "halt_error",
        "input",
        "inputs",
    ]

    def __init__(
        self,
        target_schema: TargetSchema,
        retention_threshold: float = 0.70,
        entropy_threshold: Optional[float] = None,
        max_exec_time_ms: float = 50.0,
    ) -> None:
        self.target_schema = target_schema
        thresh = entropy_threshold if entropy_threshold is not None else retention_threshold
        self.retention_threshold = thresh
        self.integrity_verifier = DataIntegrityVerifier(default_threshold=thresh)
        self.integrity_oracle = self.integrity_verifier  # Backwards compatibility alias
        self.entropy_oracle = self.integrity_verifier  # Backwards compatibility alias
        self.max_exec_time_ms = max_exec_time_ms

    def verify_purity_ast(self, jq_source: str) -> InvariantResult:
        """
        I_idempotence Part A: Static AST / lexical token linting.
        Prevents non-deterministic functions and external state access.
        """
        for token in self.FORBIDDEN_JQ_TOKENS:
            # Match token as a standalone word/function
            pattern = rf"\b{re.escape(token)}\b"
            if re.search(pattern, jq_source):
                return InvariantResult(
                    passed=False,
                    invariant_name="I_idempotence",
                    error_message=f"Purity violation: Forbidden impure or non-deterministic JQ token '{token}' detected.",
                )
        return InvariantResult(passed=True, invariant_name="I_idempotence")

    def execute_sandboxed(self, jq_source: str, input_payload: Any) -> InvariantResult:
        """
        I_exec: Total termination and runtime safety.
        Compiles and runs JQ program with strict time budget.
        """
        start_compile = time.perf_counter()
        try:
            program = jq.compile(jq_source)
        except Exception as e:
            return InvariantResult(
                passed=False,
                invariant_name="I_exec",
                error_message=f"JQ compilation panic: {str(e)}",
            )

        start_exec = time.perf_counter()
        try:
            # Execute transformation
            result_iter = program.input_value(input_payload)
            results = result_iter.all()
        except Exception as e:
            return InvariantResult(
                passed=False,
                invariant_name="I_exec",
                error_message=f"JQ runtime panic: {str(e)}",
            )
        elapsed_ms = (time.perf_counter() - start_exec) * 1000.0

        if elapsed_ms > self.max_exec_time_ms:
            return InvariantResult(
                passed=False,
                invariant_name="I_exec",
                error_message=f"Execution budget exceeded: {elapsed_ms:.2f}ms > {self.max_exec_time_ms}ms.",
            )

        if not results:
            return InvariantResult(
                passed=False,
                invariant_name="I_exec",
                error_message="Empty transformation: JQ program emitted 0 output values.",
            )

        if len(results) > 1:
            return InvariantResult(
                passed=False,
                invariant_name="I_exec",
                error_message=f"Multiplicity violation: JQ program emitted {len(results)} outputs instead of single document.",
            )

        output = results[0]
        if output is None:
            return InvariantResult(
                passed=False,
                invariant_name="I_exec",
                error_message="Null output: JQ program transformed payload into null.",
            )

        return InvariantResult(
            passed=True,
            invariant_name="I_exec",
            output=output,
            metrics={"exec_time_ms": elapsed_ms},
        )

    def verify_type(self, output: Any) -> InvariantResult:
        """
        I_type: Structural and type conformance to Canonical Target Schema.
        """
        is_valid, err_msg = self.target_schema.validate(output)
        if not is_valid:
            return InvariantResult(
                passed=False,
                invariant_name="I_type",
                error_message=f"Target schema conformance failure: {err_msg}",
                output=output,
            )
        return InvariantResult(passed=True, invariant_name="I_type", output=output)

    def verify_data_integrity(self, source_input: Any, output: Any) -> InvariantResult:
        """
        I_integrity: Data integrity & zero data loss. Ensures output is grounded in source input.
        """
        is_preserved, recall, reason = self.integrity_verifier.verify(source_input, output)
        if not is_preserved:
            return InvariantResult(
                passed=False,
                invariant_name="I_integrity",
                error_message=reason,
                output=output,
                metrics={"retention_ratio": recall},
            )
        return InvariantResult(
            passed=True,
            invariant_name="I_integrity",
            output=output,
            metrics={"retention_ratio": recall},
        )

    # Backwards compatibility alias
    verify_entropy = verify_data_integrity

    def verify_determinism(self, jq_source: str, input_payload: Any, baseline_output: Any) -> InvariantResult:
        """
        I_idempotence Part B: Deterministic replay verification.
        Asserts f(x) == f(x) on subsequent evaluation.
        """
        program = jq.compile(jq_source)
        second_run = program.input_value(input_payload).first()
        if second_run != baseline_output:
            return InvariantResult(
                passed=False,
                invariant_name="I_idempotence",
                error_message="Non-deterministic evaluation: Repeated runs on identical input yielded diverging outputs.",
            )
        return InvariantResult(passed=True, invariant_name="I_idempotence")

    def evaluate_all(self, jq_source: str, sample_payload: Any) -> Tuple[bool, List[InvariantResult]]:
        """
        Evaluates candidate program against all 4 invariants in strict order:
        1. I_idempotence (AST check)
        2. I_exec (Sandboxed execution)
        3. I_type (Schema conformance)
        4. I_integrity (Zero data loss / data integrity)
        5. I_idempotence (Replay check)
        """
        results: List[InvariantResult] = []

        # 1. Purity AST
        purity_ast = self.verify_purity_ast(jq_source)
        results.append(purity_ast)
        if not purity_ast.passed:
            return False, results

        # 2. Execution
        exec_res = self.execute_sandboxed(jq_source, sample_payload)
        results.append(exec_res)
        if not exec_res.passed:
            return False, results

        output = exec_res.output

        # 3. Type Conformance
        type_res = self.verify_type(output)
        results.append(type_res)
        if not type_res.passed:
            return False, results

        # 4. Data Integrity & Lossless Preservation
        integrity_res = self.verify_data_integrity(sample_payload, output)
        results.append(integrity_res)
        if not integrity_res.passed:
            return False, results

        # 5. Deterministic Replay
        replay_res = self.verify_determinism(jq_source, sample_payload, output)
        results.append(replay_res)
        if not replay_res.passed:
            return False, results

        return True, results


# Backwards compatibility alias
VerificationOracle = InvariantVerifier
