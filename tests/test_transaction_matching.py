from app.models import CaseType, EvidenceVerdict, Transaction, TransactionStatus, TransactionType
from app.services.normalization import normalize_complaint
from app.services.transaction_matching import (
    AMOUNT_SCORE,
    PHONE_SCORE,
    STATUS_SUPPORT_SCORE,
    TRANSACTION_ID_SCORE,
    TYPE_MATCH_SCORE,
    match_transaction,
    score_transaction_candidate,
)


def test_candidate_score_breaks_down_matching_signals() -> None:
    normalized = normalize_complaint(
        "Please check TXN-ABC. I paid 1200 to 01711111111 and it failed."
    )
    transaction = _tx(
        "TXN-ABC",
        type_="payment",
        amount=1200,
        counterparty="+8801711111111",
        status="failed",
    )

    score = score_transaction_candidate(
        transaction,
        normalized,
        expected_type=TransactionType.payment,
        supporting_statuses={TransactionStatus.failed},
        inconsistent_statuses={TransactionStatus.completed},
    )

    assert score.breakdown.transaction_id == TRANSACTION_ID_SCORE
    assert score.breakdown.amount == AMOUNT_SCORE
    assert score.breakdown.transaction_type == TYPE_MATCH_SCORE
    assert score.breakdown.phone_number == PHONE_SCORE
    assert score.breakdown.status == STATUS_SUPPORT_SCORE
    assert score.total == (
        TRANSACTION_ID_SCORE
        + AMOUNT_SCORE
        + TYPE_MATCH_SCORE
        + PHONE_SCORE
        + STATUS_SUPPORT_SCORE
    )


def test_transaction_id_is_decisive_even_when_amount_differs() -> None:
    normalized = normalize_complaint("TXN-LOW was sent to the wrong number.")
    result = match_transaction(
        CaseType.wrong_transfer,
        normalized,
        [
            _tx("TXN-HIGH", type_="transfer", amount=5000, status="completed"),
            _tx("TXN-LOW", type_="transfer", amount=500, status="completed"),
        ],
    )

    assert result.relevant_transaction_id == "TXN-LOW"
    assert result.evidence_verdict == EvidenceVerdict.consistent
    assert result.candidate_scores[0].transaction.transaction_id == "TXN-LOW"


def test_phone_number_disambiguates_equal_amount_transfers() -> None:
    normalized = normalize_complaint(
        "I sent 1000 to 01722222222 by mistake. Please help."
    )
    result = match_transaction(
        CaseType.wrong_transfer,
        normalized,
        [
            _tx(
                "TXN-OTHER",
                type_="transfer",
                amount=1000,
                counterparty="+8801711111111",
                status="completed",
            ),
            _tx(
                "TXN-PHONE",
                type_="transfer",
                amount=1000,
                counterparty="+8801722222222",
                status="completed",
            ),
        ],
    )

    assert result.relevant_transaction_id == "TXN-PHONE"
    assert result.evidence_verdict == EvidenceVerdict.consistent


def test_ambiguous_equal_scores_return_insufficient_data() -> None:
    normalized = normalize_complaint("I sent 1000 to the wrong number yesterday.")
    result = match_transaction(
        CaseType.wrong_transfer,
        normalized,
        [
            _tx(
                "TXN-A",
                type_="transfer",
                amount=1000,
                counterparty="+8801711111111",
                status="completed",
            ),
            _tx(
                "TXN-B",
                type_="transfer",
                amount=1000,
                counterparty="+8801822222222",
                status="completed",
            ),
        ],
    )

    assert result.relevant_transaction_id is None
    assert result.evidence_verdict == EvidenceVerdict.insufficient_data
    assert "ambiguous_match" in result.reason_codes
    assert "similar deterministic scores" in result.notes[0]


def _tx(
    transaction_id: str,
    *,
    type_: str,
    amount: int,
    counterparty: str = "+8801711111111",
    status: str,
) -> Transaction:
    return Transaction.model_validate(
        {
            "transaction_id": transaction_id,
            "timestamp": "2026-04-14T12:00:00Z",
            "type": type_,
            "amount": amount,
            "counterparty": counterparty,
            "status": status,
        }
    )

