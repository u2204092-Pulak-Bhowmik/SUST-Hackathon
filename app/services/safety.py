"""Centralized safety checks for every user- and agent-facing text field.

The generators in :mod:`app.services.safety_templates` only ever produce safe text,
but this module is the single enforcement point that guarantees it. It detects, in both
English and Bangla:

* requests for a credential (PIN / OTP / password / passcode / full card number),
* promises of a refund, reversal, account unblock, or recovery without authority,
* instructions to contact a suspicious third party.

The standard credential-safety reminder is intentionally phrased as a *negation*
("do not share ... "), so the request patterns below are written to never flag it.
"""

from __future__ import annotations

import re


# English credential warning appended to most replies.
SAFE_CREDENTIAL_WARNING = "Please do not share your PIN or OTP with anyone."
# Bangla equivalent (matches the public sample pack wording).
SAFE_CREDENTIAL_WARNING_BN = (
    "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
)


# A request verb close to a credential noun, unless directly negated ("do not share ...").
_EN_CREDENTIAL_REQUEST = re.compile(
    r"(?<!do not )(?<!don't )(?<!never )(?<!not )"
    r"\b(share|send|provide|give|tell|enter|submit|type|confirm|verify|reveal)\b"
    r"[^.?!]{0,60}"
    r"\b(pin|otp|password|passcode|one[- ]time password|full card(?: number)?|card number|cvv)\b",
    re.IGNORECASE,
)
# Bangla is verb-final, so an actual request reads "<credential> ... <give/share verb>".
# The safe warning ends in "শেয়ার করবেন না" (will NOT share) and uses none of these
# imperative request verbs, so it is never matched.
_BN_CREDENTIAL_REQUEST = re.compile(
    r"(পিন|ওটিপি|পাসওয়ার্ড|পাসকোড|ভেরিফিকেশন কোড)"
    r"[^।!?]{0,40}"
    r"(দিন|দাও|দেন|দিবেন|বলুন|বলেন|পাঠান|পাঠাও|জানান|লিখুন|শেয়ার করুন|শেয়ার করো|প্রবেশ করান|প্রদান করুন)"
)

_EN_UNAUTHORIZED_PROMISE = re.compile(
    r"\b(we|i)\s+(will|can|shall|are going to|'ll)\s+"
    r"(refund|reverse|unblock|reactivate|recover|return your money)\b|"
    r"\b(has|have|is|are|been)\s+(refunded|reversed|unblocked|reactivated|recovered)\b|"
    r"\bguarantee(?:d|ing)?\s+(a\s+)?(refund|reversal|recovery|unblock)\b|"
    r"\byour\s+(money|balance|amount|account)\s+(has been|is|will be)\s+"
    r"(refunded|reversed|unblocked|returned to you)\b",
    re.IGNORECASE,
)
# Bangla active promises ("we will refund", "已 refunded"). The safe templates use the
# passive eligible-amount phrasing ("ফেরত দেওয়া হবে"), which is not matched here.
_BN_UNAUTHORIZED_PROMISE = re.compile(
    r"(রিফান্ড|ফেরত|রিভার্স|আনব্লক)\s*"
    r"(করে\s*(দেব|দিচ্ছি|দিলাম|দিয়েছি|দিয়ে দিয়েছি|দিয়ে দেব|দেওয়া হয়েছে)|নিশ্চিত)"
)

_SUSPICIOUS_THIRD_PARTY = re.compile(
    r"\b(contact|call|message|reach out to|dial|text)\b"
    r"[^.?!]{0,50}"
    r"\b(the caller|that number|the person who called|the number that called|"
    r"this unknown number|the unknown number)\b",
    re.IGNORECASE,
)


_ALL_PATTERNS = (
    _EN_CREDENTIAL_REQUEST,
    _BN_CREDENTIAL_REQUEST,
    _EN_UNAUTHORIZED_PROMISE,
    _BN_UNAUTHORIZED_PROMISE,
    _SUSPICIOUS_THIRD_PARTY,
)


def requests_credentials(text: str) -> bool:
    """True if the text asks for a PIN/OTP/password/passcode/full card number."""

    return bool(_EN_CREDENTIAL_REQUEST.search(text) or _BN_CREDENTIAL_REQUEST.search(text))


def promises_unauthorized_action(text: str) -> bool:
    """True if the text promises a refund/reversal/unblock/recovery without authority."""

    return bool(_EN_UNAUTHORIZED_PROMISE.search(text) or _BN_UNAUTHORIZED_PROMISE.search(text))


def contains_unsafe_content(text: str) -> bool:
    """True if any safety rule is violated by the given text."""

    return any(pattern.search(text) for pattern in _ALL_PATTERNS)


def safe_customer_reply_fallback(language: str = "en") -> str:
    """A guaranteed-safe customer reply used when generated text is rejected."""

    if language == "bn":
        return (
            "যোগাযোগ করার জন্য ধন্যবাদ। আমরা অফিসিয়াল সাপোর্ট চ্যানেলের মাধ্যমে আপনার "
            f"বিষয়টি পর্যালোচনা করব। {SAFE_CREDENTIAL_WARNING_BN}"
        )
    return (
        "Thank you for reaching out. We will review your concern through official "
        f"support channels. {SAFE_CREDENTIAL_WARNING}"
    )


def safe_agent_summary_fallback() -> str:
    return "Customer complaint requires review with the provided transaction history."


def safe_next_action_fallback() -> str:
    return (
        "Verify eligibility through the responsible operations team before any refund, "
        "reversal, recovery, or account action."
    )
