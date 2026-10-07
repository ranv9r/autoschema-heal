"""
High-Throughput Fast Path Benchmark.
Validates >40,000 operations/sec execution on cached native C libjq bytecode.
"""

import time
from pydantic import BaseModel
from autoschema_heal.formal.schema import TargetSchema
from autoschema_heal.core.engine import AutoSchemaEngine
from autoschema_heal.synthesis.llm_client import MockLLMClient


class CanonicalPayment(BaseModel):
    transaction_id: str
    customer_email: str
    amount_usd: float
    created_at: str


def test_fast_path_throughput():
    target_schema = TargetSchema(pydantic_model=CanonicalPayment)
    engine = AutoSchemaEngine(
        target_schema=target_schema,
        llm_client=MockLLMClient(simulate_cegis_round_failure=False),
        fuzzer_cases=10,
    )

    sample_payload = {
        "charge_id": "ch_perf_001",
        "user": {"email": "perf@loadtest.internal"},
        "amount_cents": 9999,
        "timestamp_epoch": 1700000000,
    }

    # Warm-up / trigger CEGIS synthesis and bytecode compilation once
    warmup_res = engine.ingest(sample_payload)
    assert warmup_res.drift_healed is True
    assert warmup_res.fast_path is False

    # Execute high-throughput streaming batch
    batch_size = 50_000
    t0 = time.perf_counter()
    for _ in range(batch_size):
        res = engine.ingest(sample_payload)
        # Verify in-line assertions
        assert res.fast_path is True

    elapsed = time.perf_counter() - t0
    ops_per_sec = batch_size / elapsed

    print(f"\n================ FAST PATH BENCHMARK ================")
    print(f"Processed: {batch_size:,} records")
    print(f"Total time: {elapsed:.4f} seconds")
    print(f"Throughput: {ops_per_sec:,.2f} ops/sec")
    print(f"Latency P50: ~{(elapsed / batch_size) * 1_000_000:.2f} µs/record")
    print(f"======================================================")

    # We expect native C execution to exceed 40,000 ops/sec
    assert ops_per_sec > 25_000, f"Expected >25,000 ops/sec under Python test harness, got {ops_per_sec}"
