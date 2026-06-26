"""Bangla / Banglish customer_reply support (issue 2).

Every Bengali or Banglish complaint must produce a Bengali-script customer_reply that is
safe (no PIN/OTP request, no unauthorized promise).
"""

from app.models import CaseType
from app.services.analyzer import analyze_ticket
from app.models import TicketRequest
from app.services.normalization import contains_bengali_script
from app.services.safety import contains_unsafe_content


def _analyze(**kwargs):
    return analyze_ticket(TicketRequest.model_validate(kwargs))


def _assert_bn_and_safe(response) -> None:
    assert contains_bengali_script(response.customer_reply), response.customer_reply
    assert not contains_unsafe_content(response.customer_reply), response.customer_reply
    # No English credential-request phrasing leaked in.
    lowered = response.customer_reply.lower()
    assert "share your pin" not in lowered
    assert "otp" not in lowered  # English token should not appear in a Bengali reply


def test_bangla_wrong_transfer_reply_is_bengali_and_safe() -> None:
    response = _analyze(
        ticket_id="BN-WT",
        complaint="আমি ভুল নম্বরে ৫০০০ টাকা পাঠিয়েছি, ফেরত দরকার।",
        language="bn",
        transaction_history=[
            {
                "transaction_id": "TXN-1",
                "timestamp": "2026-04-14T12:00:00Z",
                "type": "transfer",
                "amount": 5000,
                "counterparty": "+8801711111111",
                "status": "completed",
            }
        ],
    )
    assert response.case_type == CaseType.wrong_transfer
    _assert_bn_and_safe(response)


def test_bangla_failed_payment_reply_is_bengali_and_safe() -> None:
    response = _analyze(
        ticket_id="BN-PF",
        complaint="আমি ১২০০ টাকা রিচার্জে দিয়েছি কিন্তু ফেইল দেখাচ্ছে, অথচ ব্যালেন্স কেটে নিয়েছে।",
        language="bn",
        transaction_history=[
            {
                "transaction_id": "TXN-2",
                "timestamp": "2026-04-14T16:00:00Z",
                "type": "payment",
                "amount": 1200,
                "counterparty": "MERCHANT-OP",
                "status": "failed",
            }
        ],
    )
    assert response.case_type == CaseType.payment_failed
    _assert_bn_and_safe(response)


def test_bangla_refund_reply_is_bengali_and_safe() -> None:
    response = _analyze(
        ticket_id="BN-RF",
        complaint="পণ্যটি আর চাই না, আমার ৫০০ টাকা ফেরত চাই।",
        language="bn",
        transaction_history=[
            {
                "transaction_id": "TXN-3",
                "timestamp": "2026-04-14T13:00:00Z",
                "type": "payment",
                "amount": 500,
                "counterparty": "MERCHANT-7821",
                "status": "completed",
            }
        ],
    )
    assert response.case_type == CaseType.refund_request
    _assert_bn_and_safe(response)


def test_bangla_phishing_reply_is_bengali_and_safe() -> None:
    response = _analyze(
        ticket_id="BN-PH",
        complaint="কেউ ফোন করে নিজেকে বিকাশ দাবি করে আমার ওটিপি চেয়েছে এবং বলেছে একাউন্ট ব্লক হয়ে যাবে।",
        language="bn",
        transaction_history=[],
    )
    assert response.case_type == CaseType.phishing_or_social_engineering
    _assert_bn_and_safe(response)


def test_bangla_agent_cash_in_reply_is_bengali_and_safe() -> None:
    response = _analyze(
        ticket_id="BN-AC",
        complaint=(
            "আমি আজ সকালে এজেন্টের কাছে ২০০০ টাকা ক্যাশ ইন করেছি কিন্তু আমার ব্যালেন্সে টাকা আসেনি।"
        ),
        language="bn",
        transaction_history=[
            {
                "transaction_id": "TXN-9701",
                "timestamp": "2026-04-14T09:30:00Z",
                "type": "cash_in",
                "amount": 2000,
                "counterparty": "AGENT-318",
                "status": "pending",
            }
        ],
    )
    assert response.case_type == CaseType.agent_cash_in_issue
    _assert_bn_and_safe(response)


def test_bengali_script_without_language_field_still_replies_in_bangla() -> None:
    response = _analyze(
        ticket_id="BN-NOLANG",
        complaint="আমি ভুল নম্বরে ১০০০ টাকা পাঠিয়েছি।",
        transaction_history=[
            {
                "transaction_id": "TXN-4",
                "timestamp": "2026-04-14T12:00:00Z",
                "type": "transfer",
                "amount": 1000,
                "counterparty": "+8801711111111",
                "status": "completed",
            }
        ],
    )
    _assert_bn_and_safe(response)


def test_banglish_latin_without_language_field_replies_in_bangla() -> None:
    response = _analyze(
        ticket_id="BANGLISH",
        complaint="ami agent er kache 2000 cash in korchi kintu balance e ashe nai",
        transaction_history=[
            {
                "transaction_id": "TXN-5",
                "timestamp": "2026-04-14T09:30:00Z",
                "type": "cash_in",
                "amount": 2000,
                "counterparty": "AGENT-1",
                "status": "pending",
            }
        ],
    )
    assert response.case_type == CaseType.agent_cash_in_issue
    _assert_bn_and_safe(response)


def test_mixed_language_field_produces_bangla_reply() -> None:
    response = _analyze(
        ticket_id="MIXED",
        complaint="Ami bhul number e 1500 taka pathaisi, please help.",
        language="mixed",
        transaction_history=[
            {
                "transaction_id": "TXN-6",
                "timestamp": "2026-04-14T12:00:00Z",
                "type": "transfer",
                "amount": 1500,
                "counterparty": "+8801711111111",
                "status": "completed",
            }
        ],
    )
    assert response.case_type == CaseType.wrong_transfer
    _assert_bn_and_safe(response)


def test_english_complaint_stays_english() -> None:
    response = _analyze(
        ticket_id="EN",
        complaint="I sent 5000 to the wrong number, please help.",
        language="en",
        transaction_history=[
            {
                "transaction_id": "TXN-7",
                "timestamp": "2026-04-14T12:00:00Z",
                "type": "transfer",
                "amount": 5000,
                "counterparty": "+8801711111111",
                "status": "completed",
            }
        ],
    )
    assert not contains_bengali_script(response.customer_reply)
