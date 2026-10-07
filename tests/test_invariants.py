"""
Unit tests for Formal Invariant Verifier and Data Integrity Verification.
"""

from pydantic import BaseModel, Field
from autoschema_heal.formal.schema import TargetSchema
from autoschema_heal.formal.invariants import InvariantVerifier, VerificationOracle


class CanonicalPayment(BaseModel):
    transaction_id: str
    customer_email: str
    amount_usd: float
    created_at: str


def test_invariants_happy_path():
    schema = TargetSchema(pydantic_model=CanonicalPayment)
    verifier = InvariantVerifier(target_schema=schema, retention_threshold=0.70)

    # Drifted payload
    drift_payload = {
        "charge_id": "ch_7721",
        "user": {"email": "customer@example.com"},
        "amount_cents": 2550,
        "timestamp_epoch": 1700000000,
    }

    # Sound candidate JQ program
    candidate_jq = """
    {
      transaction_id: .charge_id,
      customer_email: .user.email,
      amount_usd: (.amount_cents / 100),
      created_at: (.timestamp_epoch | todate)
    }
    """

    passed, results = verifier.evaluate_all(candidate_jq, drift_payload)
    assert passed is True
    assert all(r.passed for r in results)


def test_data_integrity_catches_degenerate_dummy_program():
    schema = TargetSchema(pydantic_model=CanonicalPayment)
    verifier = InvariantVerifier(target_schema=schema, retention_threshold=0.70)

    drift_payload = {
        "charge_id": "ch_7721",
        "user": {"email": "customer@example.com"},
        "amount_cents": 2550,
        "timestamp_epoch": 1700000000,
    }

    # Cheating candidate: conforms to TargetSchema but drops all real user data
    cheating_jq = """
    {
      transaction_id: "tx_dummy_const",
      customer_email: "dummy@nowhere.com",
      amount_usd: 1.0,
      created_at: "2026-01-01T00:00:00Z"
    }
    """

    passed, results = verifier.evaluate_all(cheating_jq, drift_payload)
    assert passed is False
    # I_exec and I_type pass, but I_integrity MUST fail
    failed_invariants = [r for r in results if not r.passed]
    assert len(failed_invariants) == 1
    assert failed_invariants[0].invariant_name == "I_integrity"
    assert "I_integrity violation" in failed_invariants[0].error_message


def test_purity_ast_rejects_impure_tokens():
    schema = TargetSchema(pydantic_model=CanonicalPayment)
    verifier = InvariantVerifier(target_schema=schema)

    impure_jq = """
    {
      transaction_id: .charge_id,
      customer_email: .user.email,
      amount_usd: 10.0,
      created_at: (now | todate)
    }
    """
    passed, results = verifier.evaluate_all(impure_jq, {"charge_id": "x", "user": {"email": "y"}})
    assert passed is False
    assert results[0].invariant_name == "I_idempotence"
    assert "Forbidden impure" in results[0].error_message
