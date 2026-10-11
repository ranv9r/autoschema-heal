"""
Live Groq end-to-end test for AutoSchema-Heal.
Uses the real GROQ_API_KEY from .env to synthesize a JQ transformation
for a Stripe-style drifted payload and validates all 4 property checks pass.
"""

import os
import sys
import time
import json

# Load .env so GROQ_API_KEY is available
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))
except ImportError:
    pass

from pydantic import BaseModel
from autoschema_heal.core.engine import AutoSchemaEngine
from autoschema_heal.synthesis.llm_client import GroqClient
from autoschema_heal.formal.schema import TargetSchema
from autoschema_heal.formal.invariants import InvariantVerifier


class CanonicalPayment(BaseModel):
    transaction_id: str
    customer_email: str
    amount_usd: float
    created_at: str


# Drifted Stripe-style payload (v2 -> v3 breaking change)
DRIFT_PAYLOAD = {
    "charge_id": "ch_live_test_99001",
    "user": {"email": "alice@acme.corp"},
    "amount_cents": 7850,
    "timestamp_epoch": 1700050000,
}

EXPECTED = {
    "transaction_id": "ch_live_test_99001",
    "customer_email": "alice@acme.corp",
    "amount_usd": 78.50,
}


def run_live_test():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("ERROR: GROQ_API_KEY not set in environment / .env")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("  AutoSchema-Heal — Live Groq End-to-End Test")
    print(f"{'='*60}")
    print(f"\n[INPUT] Drifted payload:\n{json.dumps(DRIFT_PAYLOAD, indent=2)}")
    print(f"\n[TARGET SCHEMA] CanonicalPayment:\n"
          f"  transaction_id: str\n"
          f"  customer_email: str\n"
          f"  amount_usd: float\n"
          f"  created_at: str\n")

    groq_client = GroqClient(
        api_key=api_key,
        model="openai/gpt-oss-120b",
        temperature=0.2,
        max_completion_tokens=2048,
    )

    target_schema = TargetSchema(pydantic_model=CanonicalPayment)
    engine = AutoSchemaEngine(
        target_schema=target_schema,
        llm_client=groq_client,
        cegis_max_rounds=5,
        fuzzer_cases=20,
        retention_threshold=0.70,
    )

    print("[STEP] Ingesting drifted payload through CEGIS slow path...")
    t0 = time.perf_counter()
    result = engine.ingest(DRIFT_PAYLOAD)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    print(f"\n{'='*60}")
    print("  RESULT")
    print(f"{'='*60}")

    if result.quarantined:
        print(f"[FAIL] Record quarantined: {result.quarantine_reason}")
        sys.exit(1)

    print(f"[PASS] drift_healed     = {result.drift_healed}")
    print(f"[INFO] cegis_rounds     = {result.cegis_rounds}")
    print(f"[INFO] fast_path        = {result.fast_path}")
    print(f"[INFO] total_latency    = {elapsed_ms:.1f} ms (includes LLM call)")
    print(f"\n[OUTPUT] Transformed record:\n{json.dumps(result.data, indent=2)}")

    # Validate output matches expected values
    errors = []
    assert result.data is not None, "Output data is None"

    if result.data.get("transaction_id") != EXPECTED["transaction_id"]:
        errors.append(f"transaction_id mismatch: got {result.data.get('transaction_id')!r}")
    if result.data.get("customer_email") != EXPECTED["customer_email"]:
        errors.append(f"customer_email mismatch: got {result.data.get('customer_email')!r}")
    if abs(float(result.data.get("amount_usd", 0)) - EXPECTED["amount_usd"]) > 0.01:
        errors.append(f"amount_usd mismatch: got {result.data.get('amount_usd')!r}, expected {EXPECTED['amount_usd']}")
    if "created_at" not in result.data or not result.data["created_at"]:
        errors.append("created_at field missing or empty")

    print(f"\n{'='*60}")
    print("  ASSERTION CHECKS")
    print(f"{'='*60}")

    if errors:
        for e in errors:
            print(f"[FAIL] {e}")
        sys.exit(1)
    else:
        print("[PASS] transaction_id  correct")
        print("[PASS] customer_email  correct")
        print("[PASS] amount_usd      correct (78.50)")
        print("[PASS] created_at      present")

    # Now test the fast path — second record with same schema shape
    print(f"\n[STEP] Ingesting second record (same schema shape -> should hit fast path)...")
    second = {
        "charge_id": "ch_live_test_99002",
        "user": {"email": "bob@corp.io"},
        "amount_cents": 3300,
        "timestamp_epoch": 1700060000,
    }
    t1 = time.perf_counter()
    res2 = engine.ingest(second)
    fast_us = (time.perf_counter() - t1) * 1_000_000.0

    print(f"[INFO] fast_path        = {res2.fast_path}")
    print(f"[INFO] latency          = {fast_us:.1f} us")
    print(f"[OUTPUT] {json.dumps(res2.data, indent=2)}")

    if not res2.fast_path:
        print("[WARN] Expected fast path hit — fingerprint may differ")
    else:
        print("[PASS] Fast path cache hit confirmed")
        if fast_us > 5000:
            print(f"[WARN] Fast path latency {fast_us:.0f} us is higher than expected (possible Python overhead)")
        else:
            print(f"[PASS] Fast path latency {fast_us:.0f} us")

    stats = engine.stats()
    print(f"\n[STATS] {json.dumps(stats, indent=2)}")
    print(f"\n{'='*60}")
    print("  Live test PASSED")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    run_live_test()
