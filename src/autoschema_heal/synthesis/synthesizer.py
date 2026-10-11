"""
CEGIS Prompt Construction and Candidate Synthesizer Engine.

Formats formal inductive synthesis queries with counterexample feedback stacks
and invokes the untrusted search backend.
"""

from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from autoschema_heal.formal.schema import TargetSchema
from autoschema_heal.synthesis.grammar import sanitize_jq_code, validate_jq_syntax
from autoschema_heal.synthesis.llm_client import BaseLLMClient


@dataclass
class CounterexampleRecord:
    round_num: int
    candidate_program: str
    counterexample_input: Any
    invariant_failed: str
    error_message: str


class CEGISSynthesizer:
    """
    Synthesizes pure JQ transformations under inductive CEGIS constraints.
    """

    def __init__(self, llm_client: BaseLLMClient, target_schema: TargetSchema) -> None:
        self.llm_client = llm_client
        self.target_schema = target_schema
        self.history: List[CounterexampleRecord] = []

    def record_counterexample(
        self,
        round_num: int,
        candidate_code: str,
        counterexample_input: Any,
        invariant_failed: str,
        error_message: str,
    ) -> None:
        """Adds a minimal failing counterexample to the refinement stack."""
        self.history.append(
            CounterexampleRecord(
                round_num=round_num,
                candidate_program=candidate_code,
                counterexample_input=counterexample_input,
                invariant_failed=invariant_failed,
                error_message=error_message,
            )
        )

    def build_prompt(self, drift_sample: Dict[str, Any]) -> str:
        """Constructs the formal CEGIS synthesis prompt."""
        prompt_parts: List[str] = [
            "You are an expert formal methods and data engineering synthesizer.",
            "TASK: Synthesize a PURE, DETERMINISTIC JQ transformation filter that transforms an upstream drifted JSON payload into the Canonical Target Schema.",
            "",
            "### STRICT ARCHITECTURAL CONSTRAINTS:",
            "1. Output ONLY the raw JQ filter. Do NOT include markdown code blocks, explanation, or commentary.",
            "2. PURE & DETERMINISTIC: Do NOT use `now`, `env`, `debug`, or `halt`.",
            "3. TOTAL & SAFE: Must handle nulls, missing fields, numeric type coercions, and timestamp conversions.",
            "4. DATA INTEGRITY (I_integrity): Do NOT output constant dummy data or drop real payload data. Real source data must be preserved and mapped to canonical target fields.",
            "",
            "### UPSTREAM DRIFT SAMPLE INPUT:",
            json.dumps(drift_sample, indent=2),
            "",
            "### CANONICAL TARGET SCHEMA (JSON Schema):",
            self.target_schema.get_json_schema_str(),
        ]

        # Add counterexample feedback history if any exists
        if self.history:
            prompt_parts.append("")
            prompt_parts.append("### COUNTEREXAMPLE FROM PREVIOUS ROUND(S):")
            for record in self.history:
                prompt_parts.extend([
                    f"--- Round {record.round_num} Failure ---",
                    f"Candidate JQ Program:\n{record.candidate_program}",
                    f"Failing Counterexample Payload:\n{json.dumps(record.counterexample_input, indent=2)}",
                    f"Violated Invariant: {record.invariant_failed}",
                    f"Verifier Diagnostic:\n{record.error_message}",
                    "Your new candidate MUST fix this failure while remaining valid for all inputs.",
                ])

        prompt_parts.extend([
            "",
            "### CANDIDATE PURE JQ FILTER (compact, raw code only, no explanation, no markdown fences):",
        ])
        return "\n".join(prompt_parts)

    def synthesize(self, drift_sample: Dict[str, Any]) -> Tuple[bool, str, Optional[str]]:
        """
        Executes synthesis query and validates raw syntax.
        Returns (is_syntax_valid, sanitized_jq, syntax_error_if_any).
        """
        prompt = self.build_prompt(drift_sample)
        raw_response = self.llm_client.generate_candidate(prompt)
        cleaned_jq = sanitize_jq_code(raw_response)
        
        is_valid, err = validate_jq_syntax(cleaned_jq)
        return is_valid, cleaned_jq, err
