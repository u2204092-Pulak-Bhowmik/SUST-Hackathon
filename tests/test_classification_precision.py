"""Regression tests for intent-classification precision fixes.

Covers:
* "paisi na" / "পাইসি না" no longer falsely become wrong_transfer (issue 3),
* narrowed phishing detection: generic fraud/scam/code/block are not phishing (issue 4),
* refund precision: a bare "cancel" is not a refund request (issue 8).
"""

from app.models import CaseType, Channel, UserType
from app.services.classification import classify
from app.services.normalization import normalize_complaint


def _classify(text: str, *, channel: Channel | None = None, user_type: UserType | None = None):
    return classify(normalize_complaint(text), channel=channel, user_type=user_type)


# --- issue 3: "paisi na" must not become wrong_transfer on its own ------------------
def test_paisi_na_alone_is_not_wrong_transfer() -> None:
    result = _classify("Ami taka paisi na. Please check.")
    assert result.case_type != CaseType.wrong_transfer
    assert result.case_type == CaseType.other


def test_bengali_paisi_na_alone_is_not_wrong_transfer() -> None:
    result = _classify("আমি টাকা পাইসি না। চেক করেন।")
    assert result.case_type != CaseType.wrong_transfer


def test_paini_alone_is_not_wrong_transfer_or_agent() -> None:
    result = _classify("Amar taka ekhono paini.")
    assert result.case_type not in {CaseType.wrong_transfer, CaseType.agent_cash_in_issue}


def test_send_marker_plus_non_receipt_is_wrong_transfer() -> None:
    # The legitimate combination still classifies as wrong_transfer.
    result = _classify("Ami 1000 taka pathaisi kintu o paisi na bolche.")
    assert result.case_type == CaseType.wrong_transfer


def test_explicit_wrong_number_is_wrong_transfer() -> None:
    assert _classify("I sent money to the wrong number").case_type == CaseType.wrong_transfer
    assert _classify("আমি ভুল নম্বরে টাকা পাঠিয়েছি").case_type == CaseType.wrong_transfer


# --- issue 4: phishing must require a credible credential/social signal -------------
def test_generic_fraud_word_is_not_phishing() -> None:
    result = _classify("I think this is a fraud, my money is gone.")
    assert result.case_type != CaseType.phishing_or_social_engineering


def test_generic_scam_word_is_not_phishing() -> None:
    result = _classify("The merchant scammed me on this purchase.")
    assert result.case_type != CaseType.phishing_or_social_engineering


def test_app_code_not_working_is_not_phishing() -> None:
    result = _classify("The bKash code is not working on my app.")
    assert result.case_type != CaseType.phishing_or_social_engineering


def test_system_account_blocked_is_not_phishing() -> None:
    # An account already blocked by the system is not a social-engineering threat.
    result = _classify("আমার একাউন্ট ব্লক হয়ে গেছে, খুলে দিন।")
    assert result.case_type != CaseType.phishing_or_social_engineering


def test_otp_request_call_is_phishing() -> None:
    result = _classify("Someone called me and asked for my OTP.")
    assert result.case_type == CaseType.phishing_or_social_engineering


def test_account_block_threat_is_phishing() -> None:
    result = _classify(
        "A caller said my account will be blocked if I don't share the code."
    )
    assert result.case_type == CaseType.phishing_or_social_engineering


def test_bengali_otp_request_is_phishing() -> None:
    result = _classify("কেউ ফোন করে আমার ওটিপি চেয়েছে।")
    assert result.case_type == CaseType.phishing_or_social_engineering


# --- issue 8: bare "cancel" is not a refund request --------------------------------
def test_bare_cancel_is_not_refund() -> None:
    result = _classify("Please cancel.")
    assert result.case_type != CaseType.refund_request


def test_cancel_with_payment_context_is_refund() -> None:
    assert _classify("I want to cancel this payment.").case_type == CaseType.refund_request
    assert _classify("Please cancel my order and refund.").case_type == CaseType.refund_request


def test_bengali_cancel_payment_is_refund() -> None:
    assert _classify("আমার পেমেন্ট বাতিল করতে চাই।").case_type == CaseType.refund_request


def test_change_of_mind_is_refund() -> None:
    result = _classify("I changed my mind and don't want it, please refund.")
    assert result.case_type == CaseType.refund_request
