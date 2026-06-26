from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


_BN_DIGITS = str.maketrans(
    {
        "০": "0",
        "১": "1",
        "২": "2",
        "৩": "3",
        "৪": "4",
        "৫": "5",
        "৬": "6",
        "৭": "7",
        "৮": "8",
        "৯": "9",
    }
)

_PHONE_CANDIDATE_PATTERN = re.compile(
    r"(?<!\d)(?:(?:\+|00)?\s*88[\s\-().]*)?0?1[3-9](?:[\s\-().]*\d){8}(?!\d)"
)
_NUMBER_PATTERN = re.compile(r"(?<![\w+])\d+(?:,\d{3})*(?:\.\d+)?(?!\w)")
_TXN_PATTERN = re.compile(r"\b(?:TXN|TRX|TKT)[-_]?[A-Z0-9]+\b", re.IGNORECASE)
_BENGALI_SCRIPT_PATTERN = re.compile("[ঀ-৿]")
# Distinctly Bangla tokens written in Latin script (Banglish). These do not occur in
# ordinary English complaints, so they are safe signals that the customer is writing in
# Bangla even when the optional ``language`` field is absent.
_BANGLISH_MARKERS = (
    "pathaisi",
    "pathiyechi",
    "pathalam",
    "pathiyechilam",
    "pathai disi",
    "korchi",
    "korechi",
    "korlam",
    "ashe nai",
    "aseni",
    "ase nai",
    "hoy nai",
    "hoyni",
    "hoyeche",
    "paini",
    "paisi na",
    "pai nai",
    "ferot",
    "keteche",
    "kete niyeche",
    "kete niyache",
    "bhul kore",
    "vul kore",
    "amar account",
    "amar balance",
    "amar taka",
    "ami taka",
    "ami agent",
    "cash in korchi",
    "cashin korchi",
    "balance e",
    "taka kete",
)
_INJECTION_HINTS = (
    "ignore previous",
    "ignore all previous",
    "ignore system",
    "developer message",
    "system prompt",
    "override",
    "jailbreak",
    "must output",
    "ask for otp",
    "ask for pin",
)


@dataclass(frozen=True)
class NormalizedComplaint:
    original: str
    text: str
    amounts: list[Decimal]
    phones: list[str]
    transaction_ids: list[str]
    has_prompt_injection: bool


def normalize_text(text: str) -> str:
    normalized = text.translate(_BN_DIGITS)
    normalized = normalized.replace("৳", " taka ")
    normalized = normalized.replace("টাকা", " taka ")
    normalized = normalized.replace("টাকার", " taka ")
    normalized = normalized.replace("৲", " taka ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip().lower()


def normalize_complaint(complaint: str) -> NormalizedComplaint:
    text = normalize_text(complaint)
    phones = extract_phone_numbers(text)
    transaction_ids = [value.upper().replace("_", "-") for value in _TXN_PATTERN.findall(text)]
    amounts = _extract_amounts(text, phones)
    has_prompt_injection = any(hint in text for hint in _INJECTION_HINTS)
    return NormalizedComplaint(
        original=complaint,
        text=text,
        amounts=amounts,
        phones=phones,
        transaction_ids=transaction_ids,
        has_prompt_injection=has_prompt_injection,
    )


def extract_phone_numbers(text: str) -> list[str]:
    phones: list[str] = []
    seen: set[str] = set()
    for match in _PHONE_CANDIDATE_PATTERN.finditer(text.translate(_BN_DIGITS)):
        phone = normalize_phone_number(match.group(0))
        if phone and phone not in seen:
            phones.append(phone)
            seen.add(phone)
    return phones


def normalize_phone_number(value: str) -> str | None:
    digits = re.sub(r"\D", "", value.translate(_BN_DIGITS))
    if digits.startswith("00"):
        digits = digits[2:]

    national: str | None = None
    if len(digits) == 13 and digits.startswith("8801"):
        national = "0" + digits[3:]
    elif len(digits) == 12 and digits.startswith("8801"):
        national = "0" + digits[3:]
    elif len(digits) == 11 and digits.startswith("01"):
        national = digits
    elif len(digits) == 10 and digits.startswith("1"):
        national = "0" + digits

    if not national or not re.fullmatch(r"01[3-9]\d{8}", national):
        return None
    return "+880" + national[1:]


def _extract_amounts(text: str, phones: list[str]) -> list[Decimal]:
    text_without_phones = _PHONE_CANDIDATE_PATTERN.sub(" ", text.translate(_BN_DIGITS))
    phone_digits = _phone_digit_variants(phones)
    amounts: list[Decimal] = []
    seen: set[Decimal] = set()
    for match in _NUMBER_PATTERN.finditer(text_without_phones):
        raw = match.group(0).replace(",", "")
        if raw in phone_digits:
            continue
        try:
            amount = Decimal(raw)
        except InvalidOperation:
            continue
        if amount <= 0 or amount > Decimal("10000000"):
            continue
        if amount not in seen:
            amounts.append(amount)
            seen.add(amount)
    return amounts


def _phone_digit_variants(phones: list[str]) -> set[str]:
    variants: set[str] = set()
    for phone in phones:
        digits = re.sub(r"\D", "", phone)
        if not digits:
            continue
        variants.add(digits)
        if digits.startswith("880"):
            variants.add("0" + digits[3:])
            variants.add(digits[3:])
    return variants


def contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = normalize_text(text)
    return any(normalize_text(keyword) in normalized for keyword in keywords)


def contains_bengali_script(text: str) -> bool:
    """True if the text contains any Bengali (Unicode block) character."""

    return bool(_BENGALI_SCRIPT_PATTERN.search(text))


def has_banglish_markers(text: str) -> bool:
    """True if Latin-script text contains distinctly Bangla tokens (Banglish)."""

    normalized = normalize_text(text)
    return any(marker in normalized for marker in _BANGLISH_MARKERS)
