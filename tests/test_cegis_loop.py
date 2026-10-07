"""
End-to-End Test Suite for AutoSchema-Heal CEGIS Pipeline.
"""

from pydantic import BaseModel
from autoschema_heal.formal.schema import TargetSchema
from autoschema_heal.core.engine import AutoSchemaEngine
from autoschema_heal.synthesis.llm_client import MockLLMClient


class CanonicalPayment(BaseModel):
    transaction_id: str
    customer_email: str
    amount_usd: float
    created_at: str


def test_end_to_end_cegis_healing_and_caching():
    # Target canonical contract
    target_schema = TargetSchema(pydantic_model=CanonicalPayment)

    # Initialize engine with MockLLMClient (simulating genuine 2-round CEGIS refinement)
    engine = AutoSchemaEngine(
        target_schema=target_schema,
        llm_client=MockLLMClient(simulate_cegis_round_failure=True),
        fuzzer_cases=15,
        retention_threshold=0.70,
    )

    # Sample drifted payload (e.g., Stripe v3 breaking changes)
    drift_payload = {
        "charge_id": "ch_98124_stripe",
        "user": {"email": "customer@acme.corp"},
        "amount_cents": 12900,
        "timestamp_epoch": 1700000000,
    }

    # Event 1: Unseen drift -> triggers CEGIS loop
    res1 = engine.ingest(drift_payload)
    assert res1.quarantined is False
    assert res1.drift_healed is True
    assert res1.fast_path is False
    assert res1.cegis_rounds == 2  # Proves CEGIS learned from Round 1 counterexample!
    assert res1.data is not None
    assert res1.data["transaction_id"] == "ch_98124_stripe"
    assert res1.data["customer_email"] == "customer@acme.corp"
    assert res1.data["amount_usd"] == 129.0
    assert "2023-11-14" in res1.data["created_at"]

    # Event 2: Second payload with same shape -> MUST hit Fast Path!
    subsequent_payload = {
        "charge_id": "ch_98125_stripe",
        "user": {"email": "bob@acme.corp"},
        "amount_cents": 4500,
        "timestamp_epoch": 1700000500,
    }
    res2 = engine.ingest(subsequent_payload)
    assert res2.fast_path is True
    assert res2.drift_healed is False
    assert res2.data["amount_usd"] == 45.0
    assert res2.latency_microseconds < 1000.0  # Ultra-fast microsecond execution!

    # Telemetry verification
    stats = engine.stats()
    assert stats["total_processed"] == 2
    assert stats["slow_path_count"] == 1
    assert stats["fast_path_count"] == 1
    assert stats["cache_stats"]["size"] == 1
