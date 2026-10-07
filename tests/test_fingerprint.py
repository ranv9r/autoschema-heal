"""
Tests for Structural AST Shape Fingerprinting.
Validates key-ordering invariance, nested type extraction, and shape hash collision resistance.
"""

from autoschema_heal.core.fingerprint import fingerprint_payload, extract_shape


def test_key_ordering_invariance():
    # Documents with different key orderings MUST produce identical fingerprints
    doc_a = {"alpha": 1, "beta": "text", "gamma": True}
    doc_b = {"gamma": False, "alpha": 9999, "beta": "different_string"}

    fp_a = fingerprint_payload(doc_a)
    fp_b = fingerprint_payload(doc_b)

    assert fp_a == fp_b, "AST Fingerprinter must be strictly invariant to key ordering and scalar values"


def test_structural_nesting_sensitivity():
    # Documents with differing nesting MUST produce distinct fingerprints
    doc_flat = {"user_id": 10, "email": "a@b.com"}
    doc_nested = {"user": {"id": 10, "email": "a@b.com"}}

    fp_flat = fingerprint_payload(doc_flat)
    fp_nested = fingerprint_payload(doc_nested)

    assert fp_flat != fp_nested, "Fingerprinter must differentiate flat vs nested object topologies"


def test_array_shape_inference():
    # Homogeneous lists should produce consistent shape
    list_doc1 = {"items": [1, 2, 3, 4]}
    list_doc2 = {"items": [100, 200]}

    assert fingerprint_payload(list_doc1) == fingerprint_payload(list_doc2)
