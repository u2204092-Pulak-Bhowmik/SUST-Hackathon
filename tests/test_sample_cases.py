import json
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)
FIXTURE = Path(__file__).parent / "fixtures" / "sample_cases.json"
REQUIRED_FIELDS = {
    "ticket_id",
    "relevant_transaction_id",
    "evidence_verdict",
    "case_type",
    "severity",
    "department",
    "agent_summary",
    "recommended_next_action",
    "customer_reply",
    "human_review_required",
}


def test_public_sample_cases_match_judged_fields() -> None:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    assert len(cases) == 10
    for case in cases:
        response = client.post("/analyze-ticket", json=case["input"])
        assert response.status_code == 200, case["id"]
        payload = response.json()
        expected = case["expected_output"]
        assert REQUIRED_FIELDS <= set(payload), case["id"]
        for field in (
            "ticket_id",
            "relevant_transaction_id",
            "evidence_verdict",
            "case_type",
            "severity",
            "department",
            "human_review_required",
        ):
            assert payload[field] == expected[field], (case["id"], field, payload)
        assert 0 <= payload["confidence"] <= 1
        assert isinstance(payload["reason_codes"], list)
        _assert_safe_reply(payload["customer_reply"])


def _assert_safe_reply(reply: str) -> None:
    lower = reply.lower()
    unsafe_request = re.compile(
        r"(?<!do not )(?<!don't )(?<!never )\b(share|send|provide|give|tell)\b"
        r".{0,60}\b(pin|otp|password|full card)\b",
        re.IGNORECASE,
    )
    unsafe_promises = (
        "we will refund",
        "we will reverse",
        "your money has been refunded",
        "your account is unblocked",
    )
    assert not unsafe_request.search(reply)
    assert all(phrase not in lower for phrase in unsafe_promises)
