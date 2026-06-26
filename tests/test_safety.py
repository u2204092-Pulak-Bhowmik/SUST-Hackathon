"""Centralized safety coverage (issue 6).

* Every case type yields safe agent_summary, recommended_next_action, and customer_reply.
* The centralized check rewrites unsafe credential requests and unauthorized promises in
  every field, in both English and Bangla, without flagging the safe templates.
"""

import pytest

from app.models import (
    AnalysisResponse,
    CaseType,
    Department,
    EvidenceVerdict,
    Severity,
    TicketRequest,
)
from app.services.analyzer import analyze_ticket
from app.services.normalization import contains_bengali_script
from app.services.output_validation import validate_and_repair_response
from app.services.safety import (
    SAFE_CREDENTIAL_WARNING,
    contains_unsafe_content,
    promises_unauthorized_action,
    requests_credentials,
)


# --- end-to-end: every case type produces safe text --------------------------------
_CASES = {
    "wrong_transfer": ("I sent 5000 to the wrong number", "transfer", 5000, "completed"),
    "payment_failed": ("I paid 1200 for recharge but it failed and balance deducted", "payment", 1200, "failed"),
    "refund_request": ("I changed my mind, please refund my 500", "payment", 500, "completed"),
    "duplicate_payment": ("I was charged twice for 850", "payment", 850, "completed"),
    "merchant_settlement_delay": ("My merchant settlement of 15000 is delayed", "settlement", 15000, "pending"),
    "agent_cash_in_issue": ("I did cash in 2000 with the agent but balance not reflected", "cash_in", 2000, "pending"),
}


@pytest.mark.parametrize("label,spec", list(_CASES.items()))
def test_every_case_type_produces_safe_fields(label, spec) -> None:
    complaint, txtype, amount, status = spec
    response = analyze_ticket(
        TicketRequest.model_validate(
            {
                "ticket_id": f"SAFE-{label}",
                "complaint": complaint,
                "transaction_history": [
                    {
                        "transaction_id": "TXN-1",
                        "timestamp": "2026-04-14T12:00:00Z",
                        "type": txtype,
                        "amount": amount,
                        "counterparty": "+8801711111111" if txtype == "transfer" else "MERCHANT-1",
                        "status": status,
                    },
                    {
                        "transaction_id": "TXN-2",
                        "timestamp": "2026-04-14T12:00:11Z",
                        "type": txtype,
                        "amount": amount,
                        "counterparty": "+8801711111111" if txtype == "transfer" else "MERCHANT-1",
                        "status": status,
                    },
                ],
            }
        )
    )
    for field in (response.agent_summary, response.recommended_next_action, response.customer_reply):
        assert not contains_unsafe_content(field), (label, field)


def test_merchant_settlement_reply_includes_credential_warning() -> None:
    response = analyze_ticket(
        TicketRequest.model_validate(
            {
                "ticket_id": "MS-1",
                "complaint": "I am a merchant, my settlement of 15000 is delayed.",
                "user_type": "merchant",
                "channel": "merchant_portal",
                "transaction_history": [
                    {
                        "transaction_id": "TXN-9901",
                        "timestamp": "2026-04-13T18:00:00Z",
                        "type": "settlement",
                        "amount": 15000,
                        "counterparty": "MERCHANT-SELF",
                        "status": "pending",
                    }
                ],
            }
        )
    )
    assert response.case_type == CaseType.merchant_settlement_delay
    assert SAFE_CREDENTIAL_WARNING in response.customer_reply


# --- unit: centralized repair rewrites unsafe content ------------------------------
def _resp(**over) -> AnalysisResponse:
    base = dict(
        ticket_id="T",
        relevant_transaction_id=None,
        evidence_verdict=EvidenceVerdict.consistent,
        case_type=CaseType.other,
        severity=Severity.low,
        department=Department.customer_support,
        agent_summary="A neutral summary.",
        recommended_next_action="Review the ticket.",
        customer_reply="A neutral reply.",
        human_review_required=False,
        confidence=0.5,
        reason_codes=[],
    )
    base.update(over)
    return AnalysisResponse.model_validate(base)


def test_repairs_english_credential_request_in_reply() -> None:
    repaired = validate_and_repair_response(_resp(customer_reply="Please share your OTP to verify."))
    assert "customer_reply_safety_repaired" in repaired.reason_codes
    assert not contains_unsafe_content(repaired.customer_reply)


def test_repairs_english_refund_promise_in_reply() -> None:
    repaired = validate_and_repair_response(_resp(customer_reply="We will refund you the full amount."))
    assert not contains_unsafe_content(repaired.customer_reply)


def test_repairs_bangla_credential_request_with_bangla_fallback() -> None:
    repaired = validate_and_repair_response(
        _resp(customer_reply="অনুগ্রহ করে আপনার পিন দিন এবং ওটিপি পাঠান।"), "bn"
    )
    assert "customer_reply_safety_repaired" in repaired.reason_codes
    assert not contains_unsafe_content(repaired.customer_reply)
    assert contains_bengali_script(repaired.customer_reply)


def test_repairs_unsafe_recommended_next_action() -> None:
    repaired = validate_and_repair_response(
        _resp(recommended_next_action="We will reverse the transaction immediately.")
    )
    assert "next_action_safety_repaired" in repaired.reason_codes
    assert not promises_unauthorized_action(repaired.recommended_next_action)


def test_repairs_unsafe_agent_summary() -> None:
    repaired = validate_and_repair_response(
        _resp(agent_summary="Ask the customer to share their PIN and OTP.")
    )
    assert "agent_summary_safety_repaired" in repaired.reason_codes
    assert not requests_credentials(repaired.agent_summary)


def test_safe_credential_warning_is_not_flagged() -> None:
    # The negated warning must never be treated as a credential request.
    assert not requests_credentials(SAFE_CREDENTIAL_WARNING)
    assert not contains_unsafe_content(
        "Any eligible amount will be returned through official channels. "
        + SAFE_CREDENTIAL_WARNING
    )


def test_safe_response_is_returned_unchanged() -> None:
    response = _resp(
        customer_reply=(
            "Any eligible amount will be returned through official channels. "
            + SAFE_CREDENTIAL_WARNING
        )
    )
    repaired = validate_and_repair_response(response)
    assert repaired.reason_codes == []
    assert repaired.customer_reply == response.customer_reply
