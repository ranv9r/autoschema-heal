"""
Tests for Adversarial Fuzzer and Delta-Debugging Shrinker.
"""

from autoschema_heal.fuzzer.shrinker import CounterexampleShrinker
from autoschema_heal.fuzzer.mutators import generate_adversarial_mutations


def test_delta_debugging_shrinker():
    # Synthetic bug: fails only when "culprit_key" == "crash"
    def synthetic_verifier(payload):
        if isinstance(payload, dict) and payload.get("culprit_key") == "crash":
            return False, "Synthetic crash triggered"
        return True, None

    noisy_failing_payload = {
        "innocent_1": "data1",
        "innocent_2": [1, 2, 3],
        "culprit_key": "crash",
        "innocent_3": {"nested": True},
    }

    shrinker = CounterexampleShrinker(synthetic_verifier)
    shrunk_payload, err = shrinker.shrink(noisy_failing_payload)

    # Shrunk payload must isolate culprit_key and drop innocent fields
    assert "culprit_key" in shrunk_payload
    assert "innocent_1" not in shrunk_payload
    assert "innocent_2" not in shrunk_payload
    assert "innocent_3" not in shrunk_payload
    assert err == "Synthetic crash triggered"


def test_mutator_generates_diverse_domain_boundary_cases():
    base = {"amount": 100, "created_at": "2026-10-06T12:00:00Z", "name": "Alice"}
    mutations = generate_adversarial_mutations(base, count=30)
    assert len(mutations) >= 15
    # Must contain numeric variations (0 or negative)
    amounts = [m.get("amount") for m in mutations if "amount" in m]
    assert 0 in amounts or 0.0 in amounts or -100 in amounts
