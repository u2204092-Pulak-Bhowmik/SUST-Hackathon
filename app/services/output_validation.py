from __future__ import annotations

from app.models import AnalysisResponse
from app.services.safety import (
    contains_unsafe_content,
    promises_unauthorized_action,
    requests_credentials,
    safe_agent_summary_fallback,
    safe_customer_reply_fallback,
    safe_next_action_fallback,
)


def validate_and_repair_response(
    response: AnalysisResponse,
    reply_language: str = "en",
) -> AnalysisResponse:
    """Final safety + completeness pass applied to every generated text field.

    ``customer_reply``, ``recommended_next_action`` and ``agent_summary`` are each scanned
    for credential requests, unauthorized financial promises, and suspicious-third-party
    instructions. Any violation is rewritten to a guaranteed-safe value (in the customer's
    language for the customer reply). Empty fields are backfilled.
    """

    updates: dict[str, object] = {}
    reason_codes = list(response.reason_codes)

    if contains_unsafe_content(response.customer_reply):
        updates["customer_reply"] = safe_customer_reply_fallback(reply_language)
        reason_codes.append("customer_reply_safety_repaired")

    if requests_credentials(response.recommended_next_action) or promises_unauthorized_action(
        response.recommended_next_action
    ):
        updates["recommended_next_action"] = safe_next_action_fallback()
        reason_codes.append("next_action_safety_repaired")

    if requests_credentials(response.agent_summary) or promises_unauthorized_action(
        response.agent_summary
    ):
        updates["agent_summary"] = safe_agent_summary_fallback()
        reason_codes.append("agent_summary_safety_repaired")

    if response.agent_summary.strip() == "" and "agent_summary" not in updates:
        updates["agent_summary"] = safe_agent_summary_fallback()
    if response.recommended_next_action.strip() == "" and "recommended_next_action" not in updates:
        updates["recommended_next_action"] = "Review the ticket and request clarification if required."
    if response.customer_reply.strip() == "" and "customer_reply" not in updates:
        updates["customer_reply"] = safe_customer_reply_fallback(reply_language)

    if reason_codes != response.reason_codes:
        updates["reason_codes"] = _dedupe(reason_codes)
    if not updates:
        return response
    return AnalysisResponse.model_validate(response.model_dump() | updates)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result
