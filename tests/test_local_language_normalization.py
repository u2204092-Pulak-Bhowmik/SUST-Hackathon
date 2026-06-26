from app.models import CaseType, Channel, Department, Transaction, TransactionStatus, TransactionType
from app.services.classification import classify
from app.services.normalization import (
    extract_phone_numbers,
    normalize_complaint,
    normalize_phone_number,
)
from app.services.transaction_matching import PHONE_SCORE, score_transaction_candidate


def test_bangla_digits_are_normalized_for_amounts_and_phones() -> None:
    normalized = normalize_complaint(
        "আমি ৫০০০ টাকা ভুল করে ০১৭১৯৮৭৬৫৪৩ নম্বরে পাঠিয়েছি"
    )

    assert str(normalized.amounts[0]) == "5000"
    assert normalized.phones == ["+8801719876543"]


def test_bangladesh_phone_formats_normalize_to_canonical_form() -> None:
    assert normalize_phone_number("01719876543") == "+8801719876543"
    assert normalize_phone_number("+8801719876543") == "+8801719876543"
    assert normalize_phone_number("88 01719-876543") == "+8801719876543"
    assert normalize_phone_number("০০৮৮ ০১৭১৯ ৮৭৬৫৪৩") == "+8801719876543"


def test_extract_phone_numbers_removes_duplicates_across_formats() -> None:
    phones = extract_phone_numbers(
        "Call 01719876543 or +880 1719-876543, not 01811111111."
    )

    assert phones == ["+8801719876543", "+8801811111111"]


def test_phone_matching_uses_canonical_bangladesh_numbers() -> None:
    normalized = normalize_complaint("ভুল করে ০১৭২২২২২২২২ নম্বরে ১০০০ টাকা পাঠালাম")
    transaction = Transaction.model_validate(
        {
            "transaction_id": "TXN-PHONE",
            "timestamp": "2026-04-14T12:00:00Z",
            "type": "transfer",
            "amount": 1000,
            "counterparty": "+8801722222222",
            "status": "completed",
        }
    )

    score = score_transaction_candidate(
        transaction,
        normalized,
        expected_type=TransactionType.transfer,
        supporting_statuses={TransactionStatus.completed},
        inconsistent_statuses={TransactionStatus.failed},
    )

    assert score.breakdown.phone_number == PHONE_SCORE


def test_banglish_agent_cash_in_keywords_are_detected() -> None:
    normalized = normalize_complaint(
        "Ami agent er kache 2000 cash in korchi, kintu balance e ashe nai"
    )
    classification = classify(
        normalized,
        channel=Channel.call_center,
        user_type=None,
    )

    assert classification.case_type == CaseType.agent_cash_in_issue
    assert classification.department == Department.agent_operations


def test_bangla_wrong_transfer_keywords_are_detected() -> None:
    normalized = normalize_complaint("আমি ভুল নম্বরে ৫০০ টাকা পাঠিয়েছি")
    classification = classify(
        normalized,
        channel=Channel.in_app_chat,
        user_type=None,
    )

    assert classification.case_type == CaseType.wrong_transfer
    assert classification.department == Department.dispute_resolution

