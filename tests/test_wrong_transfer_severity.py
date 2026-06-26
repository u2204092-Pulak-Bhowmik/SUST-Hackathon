"""Wrong-transfer severity is risk-factor driven, not amount-only (issue 7).

Verified (consistent) -> high; verified high-value -> critical; contradicted
(inconsistent) -> medium; ambiguous (insufficient_data) -> medium.
"""

from app.models import CaseType, Severity, TicketRequest
from app.services.analyzer import analyze_ticket


def _severity(complaint: str, history: list[dict]) -> tuple[CaseType, Severity, str]:
    response = analyze_ticket(
        TicketRequest.model_validate(
            {"ticket_id": "WT", "complaint": complaint, "transaction_history": history}
        )
    )
    return response.case_type, response.severity, response.evidence_verdict.value


def _transfer(transaction_id: str, amount: int, counterparty: str, status: str = "completed") -> dict:
    return {
        "transaction_id": transaction_id,
        "timestamp": "2026-04-14T12:00:00Z",
        "type": "transfer",
        "amount": amount,
        "counterparty": counterparty,
        "status": status,
    }


def test_verified_wrong_transfer_is_high() -> None:
    case, severity, verdict = _severity(
        "I sent 5000 to the wrong number around 2pm",
        [_transfer("TXN-1", 5000, "+8801719876543")],
    )
    assert case == CaseType.wrong_transfer
    assert verdict == "consistent"
    assert severity == Severity.high


def test_small_amount_verified_wrong_transfer_is_still_high() -> None:
    # Amount-only logic would have made this medium; a confirmed loss is high.
    _, severity, verdict = _severity(
        "I sent 300 to the wrong number by mistake",
        [_transfer("TXN-1", 300, "+8801719876543")],
    )
    assert verdict == "consistent"
    assert severity == Severity.high


def test_high_value_verified_wrong_transfer_is_critical() -> None:
    _, severity, verdict = _severity(
        "I sent 60000 to the wrong number",
        [_transfer("TXN-1", 60000, "+8801719876543")],
    )
    assert verdict == "consistent"
    assert severity == Severity.critical


def test_contradicted_wrong_transfer_is_medium() -> None:
    # Established recipient (3 prior transfers) contradicts the claim.
    case, severity, verdict = _severity(
        "I sent 2000 to the wrong person, please reverse it",
        [
            _transfer("TXN-1", 2000, "+8801812345678"),
            _transfer("TXN-2", 2500, "+8801812345678"),
            _transfer("TXN-3", 1500, "+8801812345678"),
        ],
    )
    assert case == CaseType.wrong_transfer
    assert verdict == "inconsistent"
    assert severity == Severity.medium


def test_ambiguous_wrong_transfer_is_medium() -> None:
    case, severity, verdict = _severity(
        "I sent 1000 to my brother but he didn't get it",
        [
            _transfer("TXN-1", 1000, "+8801712001122"),
            _transfer("TXN-2", 1000, "+8801812334455"),
        ],
    )
    assert case == CaseType.wrong_transfer
    assert verdict == "insufficient_data"
    assert severity == Severity.medium
