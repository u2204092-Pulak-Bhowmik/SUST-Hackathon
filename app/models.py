from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Language(str, Enum):
    en = "en"
    bn = "bn"
    mixed = "mixed"


class Channel(str, Enum):
    in_app_chat = "in_app_chat"
    call_center = "call_center"
    email = "email"
    merchant_portal = "merchant_portal"
    field_agent = "field_agent"


class UserType(str, Enum):
    customer = "customer"
    merchant = "merchant"
    agent = "agent"
    unknown = "unknown"


class TransactionType(str, Enum):
    transfer = "transfer"
    payment = "payment"
    cash_in = "cash_in"
    cash_out = "cash_out"
    settlement = "settlement"
    refund = "refund"


class TransactionStatus(str, Enum):
    completed = "completed"
    failed = "failed"
    pending = "pending"
    reversed = "reversed"


class EvidenceVerdict(str, Enum):
    consistent = "consistent"
    inconsistent = "inconsistent"
    insufficient_data = "insufficient_data"


class CaseType(str, Enum):
    wrong_transfer = "wrong_transfer"
    payment_failed = "payment_failed"
    refund_request = "refund_request"
    duplicate_payment = "duplicate_payment"
    merchant_settlement_delay = "merchant_settlement_delay"
    agent_cash_in_issue = "agent_cash_in_issue"
    phishing_or_social_engineering = "phishing_or_social_engineering"
    other = "other"


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Department(str, Enum):
    customer_support = "customer_support"
    dispute_resolution = "dispute_resolution"
    payments_ops = "payments_ops"
    merchant_operations = "merchant_operations"
    agent_operations = "agent_operations"
    fraud_risk = "fraud_risk"


class Transaction(BaseModel):
    model_config = ConfigDict(extra="allow")

    transaction_id: str
    timestamp: datetime
    type: TransactionType
    amount: Decimal = Field(ge=0)
    counterparty: str
    status: TransactionStatus

    @field_validator("transaction_id", "counterparty")
    @classmethod
    def non_empty_string(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class TicketRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    ticket_id: str
    complaint: str
    language: Language | None = None
    channel: Channel | None = None
    user_type: UserType | None = None
    campaign_context: str | None = None
    transaction_history: list[Transaction] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("ticket_id")
    @classmethod
    def ticket_id_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("ticket_id must not be empty")
        return value

    @field_validator("complaint")
    @classmethod
    def complaint_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("complaint must not be empty")
        return value


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticket_id: str
    relevant_transaction_id: str | None
    evidence_verdict: EvidenceVerdict
    case_type: CaseType
    severity: Severity
    department: Department
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    confidence: float = Field(ge=0, le=1)
    reason_codes: list[str] = Field(default_factory=list)

