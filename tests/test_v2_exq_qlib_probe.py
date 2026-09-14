"""Schema-level tests for the EXQ-001 offline Qlib raw probe."""

from quant_stack_v2.af002 import _mapping


def test_residual_intersection_is_a_list_not_a_mapping() -> None:
    """The Qlib probe must accept the list schema emitted by EXQ-001."""
    payload = {"lifecycle_and_suspension": {"free_residual_intersection": []}}
    rows = _mapping(payload, "lifecycle_and_suspension").get("free_residual_intersection")
    assert isinstance(rows, list)
