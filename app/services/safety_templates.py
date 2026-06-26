from __future__ import annotations

from app.models import CaseType, EvidenceVerdict, TicketRequest, Transaction
from app.services.normalization import NormalizedComplaint
from app.services.safety import SAFE_CREDENTIAL_WARNING, SAFE_CREDENTIAL_WARNING_BN
from app.services.transaction_matching import MatchResult


__all__ = [
    "SAFE_CREDENTIAL_WARNING",
    "SAFE_CREDENTIAL_WARNING_BN",
    "build_agent_summary",
    "build_recommended_action",
    "build_customer_reply",
]


def build_agent_summary(
    request: TicketRequest,
    normalized: NormalizedComplaint,
    case_type: CaseType,
    match: MatchResult,
) -> str:
    tx = _find_transaction(request.transaction_history, match.relevant_transaction_id)
    if case_type == CaseType.phishing_or_social_engineering:
        return (
            "Customer reports a suspicious contact or credential request. "
            "Treat as social engineering risk and protect credentials."
        )
    if case_type == CaseType.wrong_transfer:
        if tx and match.evidence_verdict == EvidenceVerdict.inconsistent:
            return (
                f"Customer claims {tx.transaction_id} ({_money(tx.amount)} BDT to "
                f"{tx.counterparty}) was a wrong transfer, but history suggests the "
                "recipient may be established."
            )
        if tx:
            return (
                f"Customer reports a possible wrong transfer involving {tx.transaction_id} "
                f"for {_money(tx.amount)} BDT to {tx.counterparty}."
            )
        return (
            "Customer reports a transfer issue, but the provided history contains multiple "
            "or insufficient possible matches."
        )
    if case_type == CaseType.payment_failed:
        if tx:
            return (
                f"Customer reports failed payment or balance deduction for {tx.transaction_id} "
                f"({_money(tx.amount)} BDT, status {tx.status.value})."
            )
        return "Customer reports a failed payment or balance deduction, but no matching payment is visible."
    if case_type == CaseType.refund_request:
        if tx:
            return (
                f"Customer requests refund guidance for {tx.transaction_id}, a "
                f"{tx.status.value} merchant payment of {_money(tx.amount)} BDT."
            )
        return "Customer requests a refund, but the payment needing review is not identifiable."
    if case_type == CaseType.duplicate_payment:
        if tx:
            return (
                f"Customer reports a duplicate payment. {tx.transaction_id} appears to be "
                f"the suspected duplicate for {_money(tx.amount)} BDT to {tx.counterparty}."
            )
        return "Customer reports duplicate payment, but the provided history does not show a clear duplicate pair."
    if case_type == CaseType.merchant_settlement_delay:
        if tx:
            return (
                f"Merchant reports delayed settlement for {tx.transaction_id} "
                f"({_money(tx.amount)} BDT, status {tx.status.value})."
            )
        return "Merchant reports settlement delay, but no matching settlement transaction is visible."
    if case_type == CaseType.agent_cash_in_issue:
        if tx:
            return (
                f"Customer reports cash-in through {tx.counterparty} not reflected in balance; "
                f"{tx.transaction_id} is {_money(tx.amount)} BDT with status {tx.status.value}."
            )
        return "Customer reports an agent cash-in issue, but no matching cash-in transaction is visible."
    if normalized.amounts:
        return (
            f"Customer raises a general money issue mentioning {_money(normalized.amounts[0])} BDT, "
            "but the complaint lacks enough detail to classify confidently."
        )
    return "Customer raises a vague account or money concern without enough transaction detail."


def build_recommended_action(case_type: CaseType, match: MatchResult) -> str:
    tx_ref = match.relevant_transaction_id or "the relevant transaction"
    if case_type == CaseType.phishing_or_social_engineering:
        return (
            "Escalate to fraud_risk immediately, reassure the customer that official support "
            "never asks for credentials, and log the reported channel for pattern analysis."
        )
    if match.evidence_verdict == EvidenceVerdict.insufficient_data:
        return (
            "Ask the customer for the transaction ID, amount, counterparty, and approximate "
            "time before initiating any dispute or reversal workflow."
        )
    if case_type == CaseType.wrong_transfer:
        return (
            f"Verify {tx_ref} with the customer and route through the wrong-transfer "
            "dispute workflow for human review."
        )
    if case_type == CaseType.payment_failed:
        return (
            f"Check ledger state for {tx_ref}. If a failed payment caused a balance debit, "
            "process only the eligible return path through official operations."
        )
    if case_type == CaseType.refund_request:
        return (
            "Explain that refund eligibility depends on policy and merchant confirmation; "
            "do not promise a refund without authorization."
        )
    if case_type == CaseType.duplicate_payment:
        return (
            f"Verify the suspected duplicate {tx_ref} with payments_ops and biller/merchant "
            "records before any reversal action."
        )
    if case_type == CaseType.merchant_settlement_delay:
        return (
            f"Route {tx_ref} to merchant_operations to verify settlement batch status and "
            "communicate an updated ETA if a delay is confirmed."
        )
    if case_type == CaseType.agent_cash_in_issue:
        return (
            f"Route {tx_ref} to agent_operations to verify agent settlement state and resolve "
            "within the standard cash-in SLA."
        )
    return "Ask for specific transaction details and keep the ticket in customer_support until clarified."


def build_customer_reply(case_type: CaseType, match: MatchResult, language: str = "en") -> str:
    if language == "bn":
        return _build_customer_reply_bn(case_type, match)
    tx_ref = match.relevant_transaction_id
    if case_type == CaseType.phishing_or_social_engineering:
        return (
            "Thank you for reaching out before sharing any information. We never ask for "
            "your PIN, OTP, or password under any circumstances. Please do not share these "
            "with anyone, even if they claim to be from us. Our fraud team has been notified."
        )
    if match.evidence_verdict == EvidenceVerdict.insufficient_data:
        if case_type == CaseType.wrong_transfer:
            return (
                "Thank you for reaching out. We need one more detail to identify the right "
                "transaction, such as the recipient number or transaction ID. "
                f"{SAFE_CREDENTIAL_WARNING}"
            )
        return (
            "Thank you for reaching out. To help you faster, please share the transaction ID, "
            f"amount involved, and a short description of what went wrong. {SAFE_CREDENTIAL_WARNING}"
        )
    if case_type == CaseType.wrong_transfer:
        return (
            f"We have received your request regarding transaction {tx_ref}. Our dispute team "
            f"will review the case and contact you through official support channels. {SAFE_CREDENTIAL_WARNING}"
        )
    if case_type == CaseType.payment_failed:
        return (
            f"We have noted that transaction {tx_ref} may have caused an unexpected balance "
            "deduction. Our payments team will review it, and any eligible amount will be "
            f"returned through official channels. {SAFE_CREDENTIAL_WARNING}"
        )
    if case_type == CaseType.refund_request:
        return (
            "Thank you for reaching out. Refund eligibility for completed merchant payments "
            "depends on the merchant or policy review. Please use official merchant or support "
            f"channels for follow-up. {SAFE_CREDENTIAL_WARNING}"
        )
    if case_type == CaseType.duplicate_payment:
        return (
            f"We have noted the possible duplicate payment for transaction {tx_ref}. Our "
            "payments team will verify it, and any eligible amount will be returned through "
            f"official channels. {SAFE_CREDENTIAL_WARNING}"
        )
    if case_type == CaseType.merchant_settlement_delay:
        return (
            f"We have noted your concern about settlement {tx_ref}. Our merchant operations "
            "team will check the batch status and update you through official channels. "
            f"{SAFE_CREDENTIAL_WARNING}"
        )
    if case_type == CaseType.agent_cash_in_issue:
        return (
            f"We have noted your concern about transaction {tx_ref}. Our agent operations "
            f"team will verify the cash-in status and update you through official channels. {SAFE_CREDENTIAL_WARNING}"
        )
    return (
        "Thank you for reaching out. Please share the transaction ID, amount, and what went "
        f"wrong so we can check the right record. {SAFE_CREDENTIAL_WARNING}"
    )


def _build_customer_reply_bn(case_type: CaseType, match: MatchResult) -> str:
    """Bangla (Bengali-script) customer replies mirroring the safe English templates.

    Every reply ends with the credential-safety reminder and never promises a refund,
    reversal, or unblock; eligible returns use the passive "ফেরত দেওয়া হবে" phrasing.
    """

    tx_ref = match.relevant_transaction_id
    if case_type == CaseType.phishing_or_social_engineering:
        return (
            "কোনো তথ্য শেয়ার করার আগে যোগাযোগ করার জন্য ধন্যবাদ। আমরা কখনোই আপনার পিন, "
            "ওটিপি বা পাসওয়ার্ড চাই না। কেউ নিজেকে আমাদের প্রতিনিধি দাবি করলেও এগুলো কারো "
            "সাথে শেয়ার করবেন না। বিষয়টি আমাদের ফ্রড টিমকে জানানো হয়েছে।"
        )
    if match.evidence_verdict == EvidenceVerdict.insufficient_data:
        if case_type == CaseType.wrong_transfer:
            return (
                "যোগাযোগ করার জন্য ধন্যবাদ। সঠিক লেনদেনটি চিহ্নিত করতে আমাদের আরও একটি তথ্য "
                "প্রয়োজন, যেমন প্রাপকের নম্বর বা লেনদেন আইডি। "
                f"{SAFE_CREDENTIAL_WARNING_BN}"
            )
        return (
            "যোগাযোগ করার জন্য ধন্যবাদ। দ্রুত সহায়তার জন্য অনুগ্রহ করে লেনদেন আইডি, সংশ্লিষ্ট "
            f"পরিমাণ এবং কী সমস্যা হয়েছে তা জানান। {SAFE_CREDENTIAL_WARNING_BN}"
        )
    if case_type == CaseType.wrong_transfer:
        return (
            f"আপনার লেনদেন {tx_ref} সম্পর্কিত অনুরোধটি আমরা পেয়েছি। আমাদের ডিসপিউট টিম "
            "বিষয়টি পর্যালোচনা করে অফিসিয়াল সাপোর্ট চ্যানেলের মাধ্যমে আপনার সাথে যোগাযোগ করবে। "
            f"{SAFE_CREDENTIAL_WARNING_BN}"
        )
    if case_type == CaseType.payment_failed:
        return (
            f"আপনার লেনদেন {tx_ref} এর কারণে অনাকাঙ্ক্ষিত ব্যালেন্স কর্তন হয়ে থাকতে পারে বলে "
            "আমরা লক্ষ্য করেছি। আমাদের পেমেন্টস টিম এটি পর্যালোচনা করবে এবং উপযুক্ত যেকোনো "
            f"পরিমাণ অফিসিয়াল চ্যানেলের মাধ্যমে ফেরত দেওয়া হবে। {SAFE_CREDENTIAL_WARNING_BN}"
        )
    if case_type == CaseType.refund_request:
        return (
            "যোগাযোগ করার জন্য ধন্যবাদ। সম্পন্ন হওয়া মার্চেন্ট পেমেন্টের রিফান্ড মার্চেন্ট বা "
            "পলিসি পর্যালোচনার উপর নির্ভর করে। অনুগ্রহ করে ফলো-আপের জন্য অফিসিয়াল মার্চেন্ট বা "
            f"সাপোর্ট চ্যানেল ব্যবহার করুন। {SAFE_CREDENTIAL_WARNING_BN}"
        )
    if case_type == CaseType.duplicate_payment:
        return (
            f"আপনার লেনদেন {tx_ref} এর সম্ভাব্য ডুপ্লিকেট পেমেন্টটি আমরা লক্ষ্য করেছি। আমাদের "
            "পেমেন্টস টিম এটি যাচাই করবে এবং উপযুক্ত যেকোনো পরিমাণ অফিসিয়াল চ্যানেলের মাধ্যমে "
            f"ফেরত দেওয়া হবে। {SAFE_CREDENTIAL_WARNING_BN}"
        )
    if case_type == CaseType.merchant_settlement_delay:
        return (
            f"আপনার সেটেলমেন্ট {tx_ref} সম্পর্কিত উদ্বেগটি আমরা লক্ষ্য করেছি। আমাদের মার্চেন্ট "
            "অপারেশন্স টিম ব্যাচ স্ট্যাটাস যাচাই করে অফিসিয়াল চ্যানেলের মাধ্যমে আপনাকে জানাবে। "
            f"{SAFE_CREDENTIAL_WARNING_BN}"
        )
    if case_type == CaseType.agent_cash_in_issue:
        return (
            f"আপনার লেনদেন {tx_ref} সম্পর্কিত বিষয়ে আমরা অবগত হয়েছি। আমাদের এজেন্ট অপারেশন্স "
            "টিম ক্যাশ-ইন স্ট্যাটাস যাচাই করে অফিসিয়াল চ্যানেলের মাধ্যমে আপনাকে জানাবে। "
            f"{SAFE_CREDENTIAL_WARNING_BN}"
        )
    return (
        "যোগাযোগ করার জন্য ধন্যবাদ। সঠিক রেকর্ডটি যাচাই করতে অনুগ্রহ করে লেনদেন আইডি, পরিমাণ "
        f"এবং কী সমস্যা হয়েছে তা জানান। {SAFE_CREDENTIAL_WARNING_BN}"
    )


def _find_transaction(transactions: list[Transaction], transaction_id: str | None) -> Transaction | None:
    if transaction_id is None:
        return None
    return next((tx for tx in transactions if tx.transaction_id == transaction_id), None)


def _money(value: object) -> str:
    text = str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text

