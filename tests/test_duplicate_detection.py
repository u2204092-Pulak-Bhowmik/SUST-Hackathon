"""Duplicate-payment detection rework (issue 5).

* No hard-coded 300s window; window is configurable and inclusive at the boundary.
* Pending/processing legs are included in candidate analysis.
* Distinguishes: both-completed (consistent), one-pending (consistent + review),
  outside-window (insufficient_data), single payment (inconsistent), none.
"""

from app.config import DEFAULT_DUPLICATE_WINDOW_SECONDS, duplicate_window_seconds
from app.models import CaseType, EvidenceVerdict, Transaction
from app.services.normalization import normalize_complaint
from app.services.transaction_matching import match_transaction


_NORM = normalize_complaint("I paid 850 twice for my electricity bill.")


def _tx(transaction_id: str, *, seconds: int = 0, minute: int = 0, status: str = "completed",
        amount: int = 850, counterparty: str = "BILLER-DESCO") -> Transaction:
    return Transaction.model_validate(
        {
            "transaction_id": transaction_id,
            "timestamp": f"2026-04-14T08:{minute:02d}:{seconds:02d}Z",
            "type": "payment",
            "amount": amount,
            "counterparty": counterparty,
            "status": status,
        }
    )


def test_two_completed_debits_are_a_consistent_duplicate() -> None:
    result = match_transaction(
        CaseType.duplicate_payment,
        _NORM,
        [_tx("TXN-1", seconds=30), _tx("TXN-2", seconds=42)],
        window_seconds=300,
    )
    assert result.evidence_verdict == EvidenceVerdict.consistent
    assert result.relevant_transaction_id == "TXN-2"  # the later/suspected duplicate
    assert "duplicate_confirmed" in result.reason_codes


def test_far_apart_default_window_still_detects_same_day_duplicate() -> None:
    # 10 minutes apart: outside the old 300s cap, inside the 24h default window.
    result = match_transaction(
        CaseType.duplicate_payment,
        _NORM,
        [_tx("TXN-1", minute=0), _tx("TXN-2", minute=10)],
    )
    assert result.evidence_verdict == EvidenceVerdict.consistent
    assert result.relevant_transaction_id == "TXN-2"


def test_pending_plus_completed_is_duplicate_flagged_for_review() -> None:
    result = match_transaction(
        CaseType.duplicate_payment,
        _NORM,
        [_tx("TXN-1", seconds=30, status="completed"), _tx("TXN-2", seconds=45, status="pending")],
        window_seconds=300,
    )
    assert result.evidence_verdict == EvidenceVerdict.consistent
    assert result.relevant_transaction_id == "TXN-2"
    assert "pending_duplicate" in result.reason_codes
    assert "needs_verification" in result.reason_codes


def test_window_boundary_is_inclusive() -> None:
    inside = match_transaction(
        CaseType.duplicate_payment, _NORM,
        [_tx("A", seconds=0), _tx("B", seconds=30)], window_seconds=30,
    )
    assert inside.evidence_verdict == EvidenceVerdict.consistent


def test_outside_window_is_insufficient_data() -> None:
    result = match_transaction(
        CaseType.duplicate_payment, _NORM,
        [_tx("A", seconds=0), _tx("B", seconds=30)], window_seconds=20,
    )
    assert result.evidence_verdict == EvidenceVerdict.insufficient_data
    assert result.relevant_transaction_id is None
    assert "outside_duplicate_window" in result.reason_codes


def test_single_matching_payment_is_inconsistent() -> None:
    result = match_transaction(
        CaseType.duplicate_payment, _NORM, [_tx("ONLY", seconds=30)], window_seconds=300,
    )
    assert result.evidence_verdict == EvidenceVerdict.inconsistent
    assert "duplicate_not_found" in result.reason_codes


def test_different_counterparty_is_not_a_duplicate_pair() -> None:
    result = match_transaction(
        CaseType.duplicate_payment, _NORM,
        [_tx("A", seconds=30, counterparty="BILLER-X"), _tx("B", seconds=40, counterparty="BILLER-Y")],
        window_seconds=300,
    )
    assert result.evidence_verdict != EvidenceVerdict.consistent


def test_duplicate_window_env_override(monkeypatch) -> None:
    monkeypatch.setenv("DUPLICATE_WINDOW_SECONDS", "10")
    assert duplicate_window_seconds() == 10
    # gap of 30s now exceeds the configured 10s window -> not a confirmed duplicate.
    result = match_transaction(
        CaseType.duplicate_payment, _NORM, [_tx("A", seconds=0), _tx("B", seconds=30)],
    )
    assert result.evidence_verdict == EvidenceVerdict.insufficient_data


def test_duplicate_window_env_default_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("DUPLICATE_WINDOW_SECONDS", raising=False)
    assert duplicate_window_seconds() == DEFAULT_DUPLICATE_WINDOW_SECONDS


def test_invalid_env_value_falls_back_to_default(monkeypatch) -> None:
    monkeypatch.setenv("DUPLICATE_WINDOW_SECONDS", "not-a-number")
    assert duplicate_window_seconds() == DEFAULT_DUPLICATE_WINDOW_SECONDS
