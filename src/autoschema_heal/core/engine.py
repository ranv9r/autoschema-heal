"""
High-Throughput Autonomous Data Ingestion Pipeline Engine.

Implements the Dual-Path Architecture:
- Fast Path: Zero-cost native C libjq execution from in-memory cache (>40k ops/sec).
- Slow Path: Autonomous CEGIS schema-healing on unseen drift.
"""

from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from autoschema_heal.core.cache import ProgramCache, CachedProgram
from autoschema_heal.core.fingerprint import fingerprint_payload
from autoschema_heal.formal.schema import TargetSchema
from autoschema_heal.cegis.coordinator import CEGISCoordinator, CEGISResult
from autoschema_heal.synthesis.llm_client import BaseLLMClient, MockLLMClient


@dataclass
class IngestionResult:
    data: Optional[Dict[str, Any]]
    fast_path: bool
    latency_microseconds: float
    fingerprint: str
    drift_healed: bool = False
    quarantined: bool = False
    quarantine_reason: Optional[str] = None
    cegis_rounds: int = 0


class AutoSchemaEngine:
    """
    Main Autonomous Data Ingestion Pipeline with CEGIS Self-Healing.
    """

    def __init__(
        self,
        target_schema: TargetSchema,
        llm_client: Optional[BaseLLMClient] = None,
        cache_size: int = 10_000,
        cegis_max_rounds: int = 5,
        fuzzer_cases: int = 30,
        retention_threshold: float = 0.70,
        entropy_threshold: Optional[float] = None,
    ) -> None:
        self.target_schema = target_schema
        self.cache = ProgramCache(max_size=cache_size)
        self.llm_client = llm_client or MockLLMClient()
        
        effective_threshold = entropy_threshold if entropy_threshold is not None else retention_threshold
        self.cegis = CEGISCoordinator(
            target_schema=self.target_schema,
            llm_client=self.llm_client,
            max_rounds=cegis_max_rounds,
            fuzzer_cases_per_round=fuzzer_cases,
            retention_threshold=effective_threshold,
        )

        # Telemetry
        self.total_processed = 0
        self.fast_path_count = 0
        self.slow_path_count = 0
        self.quarantine_count = 0
        self.dlq: List[Dict[str, Any]] = []

    def ingest(self, payload: Dict[str, Any]) -> IngestionResult:
        """
        Ingests a single payload through the pipeline.
        Executes on Fast Path if fingerprint is cached, else triggers CEGIS synthesis.
        """
        t0 = time.perf_counter()
        self.total_processed += 1

        # 1. Structural AST Fingerprint (O(size(x)))
        fp = fingerprint_payload(payload)

        # 2. Fast Path Cache Lookup
        cached_prog = self.cache.get(fp)
        if cached_prog is not None:
            # FAST PATH: Native C execution via libjq
            transformed = cached_prog.compiled_program.input_value(payload).first()
            elapsed_us = (time.perf_counter() - t0) * 1_000_000.0
            self.fast_path_count += 1
            return IngestionResult(
                data=transformed,
                fast_path=True,
                latency_microseconds=elapsed_us,
                fingerprint=fp,
            )

        # 3. Cache Miss: Check if payload already conforms natively to target schema
        is_native, _ = self.target_schema.validate(payload)
        if is_native:
            # Identity pass-through; register identity filter "." in cache
            self.cache.put(fp, ".", audit_hash="IDENTITY", timestamp=time.time())
            elapsed_us = (time.perf_counter() - t0) * 1_000_000.0
            self.fast_path_count += 1
            return IngestionResult(
                data=payload,
                fast_path=True,
                latency_microseconds=elapsed_us,
                fingerprint=fp,
            )

        # 4. SLOW PATH: Upstream Schema Drift Detected!
        self.slow_path_count += 1
        cegis_res = self.cegis.run_cegis(payload, fingerprint=fp)

        if not cegis_res.success or cegis_res.synthesized_program is None:
            # Healing failed: divert to Quarantine / DLQ
            self.quarantine_count += 1
            self.dlq.append({
                "payload": payload,
                "fingerprint": fp,
                "error": cegis_res.error_message,
                "certificate": cegis_res.certificate,
            })
            elapsed_us = (time.perf_counter() - t0) * 1_000_000.0
            return IngestionResult(
                data=None,
                fast_path=False,
                latency_microseconds=elapsed_us,
                fingerprint=fp,
                quarantined=True,
                quarantine_reason=cegis_res.error_message,
                cegis_rounds=cegis_res.rounds_taken,
            )

        # 5. Healing Succeeded: JIT compile into native C cache
        cached_prog = self.cache.put(
            fingerprint=fp,
            jq_source=cegis_res.synthesized_program,
            audit_hash=cegis_res.certificate.certificate_id if cegis_res.certificate else "",
            timestamp=time.time(),
        )

        # Execute on current payload
        transformed = cached_prog.compiled_program.input_value(payload).first()
        elapsed_us = (time.perf_counter() - t0) * 1_000_000.0

        return IngestionResult(
            data=transformed,
            fast_path=False,
            latency_microseconds=elapsed_us,
            fingerprint=fp,
            drift_healed=True,
            cegis_rounds=cegis_res.rounds_taken,
        )

    def stats(self) -> Dict[str, Any]:
        """Returns comprehensive operational telemetry."""
        fast_rate = (self.fast_path_count / self.total_processed * 100.0) if self.total_processed > 0 else 0.0
        return {
            "total_processed": self.total_processed,
            "fast_path_count": self.fast_path_count,
            "slow_path_count": self.slow_path_count,
            "quarantine_count": self.quarantine_count,
            "fast_path_percentage": round(fast_rate, 2),
            "cache_stats": self.cache.stats(),
        }
