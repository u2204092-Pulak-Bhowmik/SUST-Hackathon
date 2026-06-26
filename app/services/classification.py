from __future__ import annotations

from dataclasses import dataclass

from app.models import CaseType, Channel, Department, UserType
from app.services.normalization import NormalizedComplaint, contains_any


@dataclass(frozen=True)
class Classification:
    case_type: CaseType
    department: Department
    reason_codes: list[str]
    score: float


# --- Phishing / social engineering -------------------------------------------------
# Narrow, signal-driven detection. A bare credential noun, or generic "fraud"/"scam",
# is NOT enough on its own; there must be a credible credential-request or
# social-engineering context.
_CREDENTIAL_NOUNS = (
    "otp",
    "o t p",
    "one time password",
    "one-time password",
    "pin",
    "password",
    "passcode",
    "bkash code",
    "verification code",
    "security code",
    "ওটিপি",
    "পিন",
    "পাসওয়ার্ড",
    "পাসকোড",
    "ভেরিফিকেশন কোড",
)
_CREDENTIAL_REQUEST_CONTEXT = (
    "asked for",
    "ask for",
    "asking for",
    "wants my",
    "want my",
    "wanted my",
    "share my",
    "share your",
    "told me to share",
    "told me to give",
    "told me to send",
    "give them",
    "send them",
    "demanded",
    "chaiche",
    "chaichilo",
    "chay",
    "chaile",
    "dite bolche",
    "dite bollo",
    "share korte bolche",
    "জানতে চেয়েছে",
    "চেয়েছে",
    "চাইছে",
    "চাইলো",
    "দিতে বলেছে",
    "শেয়ার করতে বলেছে",
)
_SOCIAL_ENGINEERING = (
    "someone called",
    "somebody called",
    "got a call",
    "received a call",
    "unknown number called",
    "random call",
    "suspicious call",
    "suspicious sms",
    "suspicious message",
    "suspicious link",
    "click the link",
    "click this link",
    "clicked a link",
    "clicked the link",
    "anydesk",
    "screen share",
    "remote access",
    "claiming to be",
    "claim to be from",
    "claims to be from",
    "pretending to be",
    "impersonat",
    "posing as",
    "phone kore",
    "call dise",
    "call diye",
    "call diya",
    "sms diye",
    "sms kore",
    "link e click",
    "link pathaiche",
    "ফোন করেছে",
    "কল করেছে",
    "কল দিয়েছে",
    "কল দিছে",
    "লিংক",
    "লিঙ্ক",
    "নিজেকে বিকাশ",
)
_ACCOUNT_BLOCK_THREAT = (
    "account will be blocked",
    "account will get blocked",
    "account block kore dibe",
    "account block kore debe",
    "block kore dibe",
    "blocked if i don't",
    "blocked if i dont",
    "blocked if you don't",
    "blocked if i do not",
    "ব্লক করে দেবে",
    "ব্লক করে দিবে",
    "ব্লক হয়ে যাবে",
    "অ্যাকাউন্ট ব্লক করে",
    "একাউন্ট ব্লক করে",
)
_PHISHING_EXPLICIT = (
    "phishing",
    "social engineering",
    "otp chay",
    "otp chaiche",
    "otp chaile",
    "otp dite bolche",
    "pin chay",
    "pin chaiche",
    "password chay",
    "password chaiche",
    "ওটিপি চেয়েছে",
    "পিন চেয়েছে",
    "পাসওয়ার্ড চেয়েছে",
    "ওটিপি চাইছে",
)


# --- Duplicate payment -------------------------------------------------------------
_DUPLICATE = (
    "twice",
    "two times",
    "double",
    "duplicate",
    "deducted twice",
    "charged twice",
    "only paid once",
    "duibar",
    "dui bar",
    "dui baar",
    "2 bar",
    "2 baar",
    "double kata",
    "double deduct",
    "duibar keteche",
    "দুইবার",
    "দুই বার",
    "ডাবল",
    "দ্বিগুণ",
)


# --- Agent cash-in -----------------------------------------------------------------
# Agent-specific signals only. Generic "didn't receive" phrases ("paisi na", "paini",
# "পাইনি") were removed because they collide with wrong-transfer and other complaints.
_AGENT_CASH_IN = (
    "cash in",
    "cash-in",
    "cashin",
    "agent",
    "cash in korchi",
    "cashin korchi",
    "cash in korechi",
    "cashin korechi",
    "agent er kache",
    "agent theke",
    "agent ke",
    "balance ashe nai",
    "balance aseni",
    "balance e ashe nai",
    "balance e aseni",
    "ক্যাশ ইন",
    "ক্যাশইন",
    "এজেন্ট",
    "এজেন্টের কাছে",
)


# --- Wrong transfer ----------------------------------------------------------------
# Decisive on their own.
_WRONG_TRANSFER_STRONG = (
    "wrong number",
    "wrong person",
    "wrong recipient",
    "wrong receiver",
    "wrong account",
    "wrong individual",
    "to the wrong",
    "typed it wrong",
    "typed the wrong",
    "typed wrong number",
    "bhul number",
    "vul number",
    "bhool number",
    "vool number",
    "bhul nombor",
    "bhul nombore",
    "onno number",
    "onnno number",
    "onnor number",
    "onno manush",
    "onno lok",
    "ভুল নম্বর",
    "ভুল নাম্বার",
    "ভূল নম্বর",
    "ভূল নাম্বার",
    "অন্য নম্বর",
    "অন্য নাম্বার",
    "ভুল মানুষ",
    "ভুল লোক",
    "ভুল ব্যক্তি",
)
# A "money left my account" signal.
_SEND_MARKERS = (
    "i sent",
    "sent ",
    "i transferred",
    "transferred ",
    "send korechi",
    "sent it",
    "transfer korechi",
    "transfer korlam",
    "pathaisi",
    "pathiyechi",
    "pathalam",
    "pathiyechilam",
    "pathai disi",
    "pathay disi",
    "পাঠিয়েছি",
    "পাঠালাম",
    "পাঠিয়েছিলাম",
    "পাঠাইছি",
    "ট্রান্সফার করেছি",
    "সেন্ড করেছি",
)
# Ambiguous on their own; only imply a wrong transfer when paired with a send marker.
_NON_RECEIPT_OR_MISTAKE = (
    "didn't get",
    "did not get",
    "didnt get",
    "not received",
    "did not receive",
    "didn't receive",
    "hasn't received",
    "has not received",
    "not responding",
    "isn't responding",
    "no response",
    "reverse it",
    "reverse the transfer",
    "please reverse",
    "by mistake",
    "mistake",
    "mistakenly",
    "bhul kore",
    "vul kore",
    "paisi na",
    "pai nai",
    "pay nai",
    "paini",
    "ভুল করে",
    "পাইনি",
    "পাই নাই",
    "পায়নি",
    "পাইসি না",
    "পাইছে না",
    "ফেরত পায়নি",
)


# --- Payment failed ----------------------------------------------------------------
_PAYMENT_FAILED = (
    "payment failed",
    "app showed failed",
    "transaction failed",
    "failed",
    "balance was deducted",
    "deducted",
    "money deducted",
    "recharge",
    "bill payment failed",
    "fail hoise",
    "fail hoyeche",
    "failed hoise",
    "failed hoyeche",
    "payment fail",
    "payment hoy nai",
    "payment hoyni",
    "balance keteche",
    "balance kete niyeche",
    "taka keteche",
    "deduct hoise",
    "deduct hoyeche",
    "recharge fail",
    "ফেইল",
    "ফেল",
    "ব্যর্থ",
    "কেটে",
    "কাটা",
    "ব্যালেন্স কেটে",
    "ডিডাক্ট",
)


# --- Refund ------------------------------------------------------------------------
# "refund" intent. A bare "cancel" is NOT a refund request; it must carry transaction
# or payment context.
_REFUND_STRONG = (
    "refund",
    "return my money",
    "money back",
    "give my money back",
    "changed my mind",
    "change my mind",
    "don't want it",
    "do not want it",
    "dont want it",
    "refund chai",
    "refund din",
    "taka ferot",
    "ferot chai",
    "ferot din",
    "money ferot",
    "রিফান্ড",
    "ফেরত",
    "টাকা ফেরত",
    "ফেরত চাই",
)
_CANCEL_WORDS = (
    "cancel",
    "batil",
    "বাতিল",
)
_CANCEL_CONTEXT = (
    "transaction",
    "payment",
    "order",
    "purchase",
    "taka",
    "money",
    "amount",
    "lenden",
    "লেনদেন",
    "পেমেন্ট",
    "অর্ডার",
    "টাকা",
)


# --- Merchant settlement -----------------------------------------------------------
# Bare "merchant" was removed so a generic merchant mention does not become a
# settlement complaint.
_SETTLEMENT = (
    "settlement",
    "settled",
    "settle",
    "payout",
    "sales",
    "merchant settlement",
    "settle hoy nai",
    "settlement hoy nai",
    "settlement paini",
    "sales er taka",
    "bikrir taka",
    "payout paini",
    "সেটেল",
    "সেটেলমেন্ট",
    "পেআউট",
    "সেলস",
    "বিক্রি",
)


def _is_phishing(text: str) -> bool:
    if contains_any(text, _PHISHING_EXPLICIT):
        return True
    if contains_any(text, _ACCOUNT_BLOCK_THREAT):
        return True
    has_credential = contains_any(text, _CREDENTIAL_NOUNS)
    has_social = contains_any(text, _SOCIAL_ENGINEERING)
    has_request = contains_any(text, _CREDENTIAL_REQUEST_CONTEXT)
    if has_credential and (has_request or has_social):
        return True
    return False


def _is_wrong_transfer(text: str) -> bool:
    if contains_any(text, _WRONG_TRANSFER_STRONG):
        return True
    if contains_any(text, _SEND_MARKERS) and contains_any(text, _NON_RECEIPT_OR_MISTAKE):
        return True
    return False


def _is_refund(text: str) -> bool:
    if contains_any(text, _REFUND_STRONG):
        return True
    if contains_any(text, _CANCEL_WORDS) and contains_any(text, _CANCEL_CONTEXT):
        return True
    return False


def classify(
    normalized: NormalizedComplaint,
    *,
    channel: Channel | None,
    user_type: UserType | None,
) -> Classification:
    text = normalized.text

    if _is_phishing(text):
        return Classification(
            CaseType.phishing_or_social_engineering,
            Department.fraud_risk,
            ["phishing", "credential_protection"],
            0.95,
        )

    if contains_any(text, _DUPLICATE):
        return Classification(
            CaseType.duplicate_payment,
            Department.payments_ops,
            ["duplicate_payment_claim"],
            0.88,
        )

    if contains_any(text, _AGENT_CASH_IN):
        return Classification(
            CaseType.agent_cash_in_issue,
            Department.agent_operations,
            ["agent_cash_in"],
            0.86,
        )

    if _is_wrong_transfer(text):
        return Classification(
            CaseType.wrong_transfer,
            Department.dispute_resolution,
            ["wrong_transfer_claim"],
            0.84,
        )

    if contains_any(text, _PAYMENT_FAILED):
        return Classification(
            CaseType.payment_failed,
            Department.payments_ops,
            ["payment_failed"],
            0.84,
        )

    if _is_refund(text):
        return Classification(
            CaseType.refund_request,
            Department.customer_support,
            ["refund_request"],
            0.8,
        )

    if contains_any(text, _SETTLEMENT) or (
        user_type == UserType.merchant and contains_any(text, ("settle", "payout", "sales"))
    ):
        return Classification(
            CaseType.merchant_settlement_delay,
            Department.merchant_operations,
            ["merchant_settlement"],
            0.9,
        )

    return Classification(
        CaseType.other,
        Department.customer_support,
        ["vague_or_other"],
        0.55,
    )
