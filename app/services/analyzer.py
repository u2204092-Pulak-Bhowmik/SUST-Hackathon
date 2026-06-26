from __future__ import annotations

from decimal import Decimal

from app.models import (
    AnalysisResponse,
    CaseType,
    Department,
    EvidenceVerdict,
    Language,
    Severity,
    TicketRequest,
)
from app.services.classification import classify
from app.services.normalization import (
    NormalizedComplaint,
    contains_bengali_script,
    has_banglish_markers,
    normalize_complaint,
)
from app.services.output_validation import validate_and_repair_response
from app.services.safety_templates import (
    build_agent_summary,
    build_customer_reply,
    build_recommended_action,
)
from app.services.transaction_matching import MatchResult, match_transaction


def analyze_ticket(request: TicketRequest) -> AnalysisResponse:
    normalized = normalize_complaint(request.complaint)
    reply_language = _reply_language(request, normalized)
    classification = classify(
        normalized,
        channel=request.channel,
        user_type=request.user_type,
    )
    match = match_transaction(
        classification.case_type,
        normalized,
        request.transaction_history,
    )

    severity = _severity(classification.case_type, match, request)
    human_review_required = _human_review_required(classification.case_type, match, request)
    confidence = _confidence(classification.score, match)

    reason_codes = _dedupe(
        classification.reason_codes
        + match.reason_codes
        + _extra_reason_codes(classification.case_type, match, normalized.has_prompt_injection)
    )

    response = AnalysisResponse(
        ticket_id=request.ticket_id,
        relevant_transaction_id=match.relevant_transaction_id,
        evidence_verdict=match.evidence_verdict,
        case_type=classification.case_type,
        severity=severity,
        department=_department(classification.case_type, classification.department, match),
        agent_summary=build_agent_summary(
            request,
            normalized,
            classification.case_type,
            match,
        ),
        recommended_next_action=build_recommended_action(classification.case_type, match),
        customer_reply=build_customer_reply(classification.case_type, match, reply_language),
        human_review_required=human_review_required,
        confidence=confidence,
        reason_codes=reason_codes,
    )
    return validate_and_repair_response(response, reply_language)


def _reply_language(request: TicketRequest, normalized: NormalizedComplaint) -> str:
    """Resolve the language for the customer reply ("bn" or "en").

    Priority: explicit ``language`` field, then Bengali script in the complaint, then
    Banglish markers. English is the default. Bangla and Banglish/mixed customers receive
    a Bengali-script reply (the customer's own language), per the sample-pack guidance.
    """

    if request.language == Language.bn:
        return "bn"
    if contains_bengali_script(request.complaint):
        return "bn"
    if request.language == Language.mixed:
        return "bn"
    if request.language == Language.en:
        return "en"
    if has_banglish_markers(request.complaint):
        return "bn"
    return "en"


def _department(
    case_type: CaseType,
    original: Department,
    match: MatchResult,
) -> Department:
    if case_type == CaseType.other:
        return Department.customer_support
    if case_type == CaseType.refund_request and match.evidence_verdict == EvidenceVerdict.insufficient_data:
        return Department.customer_support
    return original


def _severity(case_type: CaseType, match: MatchResult, request: TicketRequest) -> Severity:
    amount = _matched_or_largest_amount(match, request)
    if case_type == CaseType.phishing_or_social_engineering:
        return Severity.critical
    if case_type == CaseType.wrong_transfer:
        return _wrong_transfer_severity(match, amount)
    if case_type == CaseType.payment_failed:
        return Severity.high if amount >= Decimal("1000") or match.evidence_verdict == EvidenceVerdict.consistent else Severity.medium
    if case_type == CaseType.duplicate_payment:
        return Severity.high if match.evidence_verdict == EvidenceVerdict.consistent else Severity.medium
    if case_type == CaseType.merchant_settlement_delay:
        return Severity.high if amount >= Decimal("50000") else Severity.medium
    if case_type == CaseType.agent_cash_in_issue:
        return Severity.high if amount >= Decimal("1000") or match.evidence_verdict == EvidenceVerdict.consistent else Severity.medium
    if case_type == CaseType.refund_request:
        return Severity.medium if amount >= Decimal("5000") else Severity.low
    return Severity.low


def _wrong_transfer_severity(match: MatchResult, amount: Decimal) -> Severity:
    """Deterministic wrong-transfer severity from documented risk factors.

    Risk factors, not amount alone:
    * Evidence confidence / confirmed vs ambiguous transfer:
      - ``consistent``  -> money confirmed sent to an unintended recipient (recoverable
        loss requiring a dispute) -> ``high``.
      - ``inconsistent``/``insufficient_data`` -> claim is contradicted or the transaction
        cannot be pinned down yet -> ``medium``.
    * Customer impact: a very high value (>= 50,000 BDT), which also forces manual review,
      escalates a confirmed loss to ``critical``.
    """

    high_value = amount >= Decimal("50000")
    if match.evidence_verdict == EvidenceVerdict.consistent:
        return Severity.critical if high_value else Severity.high
    return Severity.high if high_value else Severity.medium


def _human_review_required(case_type: CaseType, match: MatchResult, request: TicketRequest) -> bool:
    amount = _matched_or_largest_amount(match, request)
    if case_type == CaseType.phishing_or_social_engineering:
        return True
    if match.evidence_verdict == EvidenceVerdict.inconsistent:
        return True
    if amount >= Decimal("50000"):
        return True
    if case_type == CaseType.wrong_transfer:
        return match.relevant_transaction_id is not None
    if case_type == CaseType.duplicate_payment:
        return match.evidence_verdict == EvidenceVerdict.consistent
    if case_type == CaseType.agent_cash_in_issue:
        return match.relevant_transaction_id is not None
    return False


def _confidence(classification_score: float, match: MatchResult) -> float:
    confidence = classification_score + match.confidence_delta
    if match.evidence_verdict == EvidenceVerdict.insufficient_data:
        confidence -= 0.08
    return round(max(0.35, min(0.98, confidence)), 2)


def _extra_reason_codes(
    case_type: CaseType,
    match: MatchResult,
    has_prompt_injection: bool,
) -> list[str]:
    codes: list[str] = []
    if match.evidence_verdict == EvidenceVerdict.consistent:
        codes.append("evidence_consistent")
    elif match.evidence_verdict == EvidenceVerdict.inconsistent:
        codes.append("evidence_inconsistent")
    else:
        codes.append("insufficient_evidence")
    if case_type in {CaseType.wrong_transfer, CaseType.duplicate_payment}:
        codes.append("dispute_review")
    if has_prompt_injection:
        codes.append("prompt_injection_ignored")
    return codes


def _matched_or_largest_amount(match: MatchResult, request: TicketRequest) -> Decimal:
    if match.relevant_transaction_id:
        for tx in request.transaction_history:
            if tx.transaction_id == match.relevant_transaction_id:
                return tx.amount
    if request.transaction_history:
        return max((tx.amount for tx in request.transaction_history), default=Decimal("0"))
    return Decimal("0")


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

