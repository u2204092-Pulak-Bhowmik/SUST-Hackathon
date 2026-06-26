from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.config import duplicate_window_seconds
from app.models import CaseType, EvidenceVerdict, Transaction, TransactionStatus, TransactionType
from app.services.normalization import NormalizedComplaint, normalize_phone_number


TRANSACTION_ID_SCORE = 100
AMOUNT_SCORE = 35
TYPE_MATCH_SCORE = 25
TYPE_MISMATCH_PENALTY = -15
PHONE_SCORE = 30
STATUS_SUPPORT_SCORE = 15
STATUS_INCONSISTENT_PENALTY = -10
MIN_MATCH_SCORE = 25
AMBIGUITY_SCORE_GAP = 5


@dataclass(frozen=True)
class ScoreBreakdown:
    transaction_id: int = 0
    amount: int = 0
    transaction_type: int = 0
    phone_number: int = 0
    status: int = 0

    @property
    def total(self) -> int:
        return (
            self.transaction_id
            + self.amount
            + self.transaction_type
            + self.phone_number
            + self.status
        )


@dataclass(frozen=True)
class CandidateScore:
    transaction: Transaction
    breakdown: ScoreBreakdown

    @property
    def total(self) -> int:
        return self.breakdown.total

    @property
    def has_decisive_reference(self) -> bool:
        return self.breakdown.transaction_id > 0 or self.breakdown.phone_number > 0

    @property
    def has_expected_type(self) -> bool:
        return self.breakdown.transaction_type > 0

    def summary(self) -> str:
        parts = (
            f"id={self.breakdown.transaction_id}",
            f"amount={self.breakdown.amount}",
            f"type={self.breakdown.transaction_type}",
            f"phone={self.breakdown.phone_number}",
            f"status={self.breakdown.status}",
        )
        return f"{self.transaction.transaction_id}: total={self.total} ({', '.join(parts)})"


@dataclass(frozen=True)
class MatchResult:
    relevant_transaction_id: str | None
    evidence_verdict: EvidenceVerdict
    confidence_delta: float
    reason_codes: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    candidate_scores: list[CandidateScore] = field(default_factory=list)


def match_transaction(
    case_type: CaseType,
    normalized: NormalizedComplaint,
    transactions: list[Transaction],
    *,
    window_seconds: int | None = None,
) -> MatchResult:
    ordered = _newest_first(transactions)

    if case_type == CaseType.phishing_or_social_engineering:
        return MatchResult(
            None,
            EvidenceVerdict.insufficient_data,
            0.03,
            ["safety_only_case"],
            ["No transaction evidence is needed for a credential-safety report."],
        )

    if not ordered:
        return MatchResult(
            None,
            EvidenceVerdict.insufficient_data,
            -0.15,
            ["no_transaction_history"],
            ["No transaction history was provided."],
        )

    if case_type == CaseType.duplicate_payment:
        window = window_seconds if window_seconds is not None else duplicate_window_seconds()
        return _match_duplicate(normalized, ordered, window)
    if case_type == CaseType.wrong_transfer:
        return _match_wrong_transfer(normalized, ordered)
    if case_type == CaseType.payment_failed:
        return _match_by_type_and_status(
            normalized,
            ordered,
            expected_type=TransactionType.payment,
            supporting_statuses={TransactionStatus.failed},
            inconsistent_statuses={TransactionStatus.completed, TransactionStatus.reversed},
            label="payment_failed",
        )
    if case_type == CaseType.refund_request:
        return _match_by_type_and_status(
            normalized,
            ordered,
            expected_type=TransactionType.payment,
            supporting_statuses={TransactionStatus.completed},
            inconsistent_statuses={TransactionStatus.failed, TransactionStatus.pending},
            label="refund_request",
        )
    if case_type == CaseType.merchant_settlement_delay:
        return _match_by_type_and_status(
            normalized,
            ordered,
            expected_type=TransactionType.settlement,
            supporting_statuses={TransactionStatus.pending},
            inconsistent_statuses={TransactionStatus.completed, TransactionStatus.reversed},
            label="merchant_settlement",
        )
    if case_type == CaseType.agent_cash_in_issue:
        return _match_by_type_and_status(
            normalized,
            ordered,
            expected_type=TransactionType.cash_in,
            supporting_statuses={TransactionStatus.pending, TransactionStatus.failed},
            inconsistent_statuses={TransactionStatus.completed, TransactionStatus.reversed},
            label="agent_cash_in",
        )

    return MatchResult(
        None,
        EvidenceVerdict.insufficient_data,
        -0.1,
        ["needs_clarification"],
        ["Complaint lacks enough specific evidence to identify a transaction."],
    )


def score_transaction_candidate(
    tx: Transaction,
    normalized: NormalizedComplaint,
    *,
    expected_type: TransactionType | None,
    supporting_statuses: set[TransactionStatus],
    inconsistent_statuses: set[TransactionStatus],
) -> CandidateScore:
    transaction_id = (
        TRANSACTION_ID_SCORE
        if tx.transaction_id.upper() in normalized.transaction_ids
        else 0
    )
    amount = (
        AMOUNT_SCORE
        if normalized.amounts and any(_same_amount(tx.amount, value) for value in normalized.amounts)
        else 0
    )
    transaction_type = _type_score(tx, expected_type)
    phone_number = PHONE_SCORE if _counterparty_phone_referenced(tx, normalized) else 0
    status = _status_score(tx, supporting_statuses, inconsistent_statuses)

    return CandidateScore(
        transaction=tx,
        breakdown=ScoreBreakdown(
            transaction_id=transaction_id,
            amount=amount,
            transaction_type=transaction_type,
            phone_number=phone_number,
            status=status,
        ),
    )


def _match_duplicate(
    normalized: NormalizedComplaint,
    transactions: list[Transaction],
    window_seconds: int,
) -> MatchResult:
    ranked = _rank_candidates(
        transactions,
        normalized,
        expected_type=TransactionType.payment,
        supporting_statuses={TransactionStatus.completed},
        inconsistent_statuses={TransactionStatus.failed, TransactionStatus.reversed},
    )
    # Candidate debits: payment-type, money-leaving statuses (completed or pending),
    # restricted to the complained amount when one is given. Pending/processing legs are
    # intentionally kept so a not-yet-settled second charge is still detected.
    debits = [
        tx
        for tx in transactions
        if tx.type == TransactionType.payment
        and tx.status in {TransactionStatus.completed, TransactionStatus.pending}
        and _amount_relevant(tx, normalized.amounts)
    ]
    by_oldest = sorted(debits, key=lambda tx: (tx.timestamp, tx.transaction_id))

    matching_pair_exists = False
    closest_pair: tuple[Transaction, Transaction] | None = None
    closest_gap = float("inf")

    for index, first in enumerate(by_oldest):
        for second in by_oldest[index + 1 :]:
            # Same amount, same counterparty, same transaction type => a duplicate pair.
            if first.amount != second.amount or first.counterparty != second.counterparty:
                continue
            if first.type != second.type:
                continue
            matching_pair_exists = True
            gap = abs((second.timestamp - first.timestamp).total_seconds())
            if gap <= window_seconds and (
                gap < closest_gap
                or (gap == closest_gap and _pair_tiebreaker(first, second, closest_pair))
            ):
                closest_pair = (first, second)
                closest_gap = gap

    if closest_pair:
        first, second = closest_pair
        duplicate = second
        both_completed = (
            first.status == TransactionStatus.completed
            and second.status == TransactionStatus.completed
        )
        if both_completed:
            return MatchResult(
                duplicate.transaction_id,
                EvidenceVerdict.consistent,
                0.08,
                ["duplicate_payment", "transaction_match", "duplicate_confirmed"],
                [
                    f"Two completed payments of {duplicate.amount} BDT to "
                    f"{duplicate.counterparty} occurred {int(closest_gap)} seconds apart.",
                    *_score_notes(ranked),
                ],
                ranked,
            )
        # One leg still pending: a duplicate is visible but one charge has not settled.
        # Flag for verification (human_review is forced via the consistent verdict).
        return MatchResult(
            duplicate.transaction_id,
            EvidenceVerdict.consistent,
            0.0,
            ["duplicate_payment", "transaction_match", "pending_duplicate", "needs_verification"],
            [
                f"Two matching payments of {duplicate.amount} BDT to "
                f"{duplicate.counterparty} occurred {int(closest_gap)} seconds apart; one is "
                "still pending and must be verified before any action.",
                *_score_notes(ranked),
            ],
            ranked,
        )

    if matching_pair_exists:
        # Matching debits exist but are spread further apart than the duplicate window,
        # so they more likely reflect separate payments than a single double charge.
        return MatchResult(
            None,
            EvidenceVerdict.insufficient_data,
            -0.08,
            ["duplicate_payment", "outside_duplicate_window", "needs_clarification"],
            [
                "Matching payments exist but fall outside the duplicate-detection window; "
                "confirm with the customer which charges are disputed.",
                *_score_notes(ranked),
            ],
            ranked,
        )

    selected = _select_scored_candidate(ranked, expected_type=TransactionType.payment)
    if selected:
        ambiguity = _detect_ambiguity(selected, ranked, expected_type=TransactionType.payment)
        if ambiguity:
            return MatchResult(
                None,
                EvidenceVerdict.insufficient_data,
                -0.1,
                ["duplicate_payment", "ambiguous_match", "needs_clarification"],
                [ambiguity, *_score_notes(ranked)],
                ranked,
            )
        return MatchResult(
            selected.transaction.transaction_id,
            EvidenceVerdict.inconsistent,
            -0.08,
            ["duplicate_not_found", "evidence_inconsistent"],
            ["Only one matching payment is visible in the provided history.", *_score_notes(ranked)],
            ranked,
        )
    return MatchResult(
        None,
        EvidenceVerdict.insufficient_data,
        -0.12,
        ["no_duplicate_match"],
        ["No matching payment pair was found in the provided history.", *_score_notes(ranked)],
        ranked,
    )


def _match_wrong_transfer(
    normalized: NormalizedComplaint,
    transactions: list[Transaction],
) -> MatchResult:
    ranked = _rank_candidates(
        transactions,
        normalized,
        expected_type=TransactionType.transfer,
        supporting_statuses={TransactionStatus.completed},
        inconsistent_statuses={TransactionStatus.failed, TransactionStatus.reversed},
    )
    selected = _select_scored_candidate(ranked, expected_type=TransactionType.transfer)

    if selected is None:
        return MatchResult(
            None,
            EvidenceVerdict.insufficient_data,
            -0.14,
            ["no_transfer_match"],
            ["No transfer in the provided history matches the complaint details.", *_score_notes(ranked)],
            ranked,
        )

    ambiguity = _detect_ambiguity(selected, ranked, expected_type=TransactionType.transfer)
    if ambiguity:
        return MatchResult(
            None,
            EvidenceVerdict.insufficient_data,
            -0.1,
            ["ambiguous_match", "needs_clarification"],
            [ambiguity, *_score_notes(ranked)],
            ranked,
        )

    tx = selected.transaction
    same_counterparty = [
        history_tx
        for history_tx in transactions
        if history_tx.type == TransactionType.transfer
        and history_tx.counterparty == tx.counterparty
        and history_tx.status == TransactionStatus.completed
    ]
    if len(same_counterparty) >= 3 and tx.status == TransactionStatus.completed:
        return MatchResult(
            tx.transaction_id,
            EvidenceVerdict.inconsistent,
            -0.03,
            ["established_recipient_pattern", "evidence_inconsistent"],
            [
                f"History shows {len(same_counterparty)} completed transfers to "
                f"{tx.counterparty}, which weakens the wrong-transfer claim.",
                *_score_notes(ranked),
            ],
            ranked,
        )

    if tx.status in {TransactionStatus.failed, TransactionStatus.reversed}:
        return MatchResult(
            tx.transaction_id,
            EvidenceVerdict.inconsistent,
            -0.08,
            ["failed_transfer", "evidence_inconsistent"],
            ["The matched transfer did not complete, so the data does not support a completed wrong transfer.", *_score_notes(ranked)],
            ranked,
        )

    if tx.status == TransactionStatus.pending:
        return MatchResult(
            tx.transaction_id,
            EvidenceVerdict.insufficient_data,
            -0.04,
            ["pending_transfer", "status_unclear"],
            ["The matched transfer is still pending, so the evidence is not conclusive.", *_score_notes(ranked)],
            ranked,
        )

    return MatchResult(
        tx.transaction_id,
        EvidenceVerdict.consistent,
        0.06,
        ["transaction_match"],
        [
            f"Transfer {tx.transaction_id} for {tx.amount} BDT to "
            f"{tx.counterparty} aligns with the complaint.",
            *_score_notes(ranked),
        ],
        ranked,
    )


def _match_by_type_and_status(
    normalized: NormalizedComplaint,
    transactions: list[Transaction],
    *,
    expected_type: TransactionType,
    supporting_statuses: set[TransactionStatus],
    inconsistent_statuses: set[TransactionStatus],
    label: str,
) -> MatchResult:
    ranked = _rank_candidates(
        transactions,
        normalized,
        expected_type=expected_type,
        supporting_statuses=supporting_statuses,
        inconsistent_statuses=inconsistent_statuses,
    )
    selected = _select_scored_candidate(ranked, expected_type=expected_type)

    if selected is None:
        return MatchResult(
            None,
            EvidenceVerdict.insufficient_data,
            -0.12,
            [label, "no_transaction_match"],
            [f"No {expected_type.value} transaction matches the complaint details.", *_score_notes(ranked)],
            ranked,
        )

    ambiguity = _detect_ambiguity(selected, ranked, expected_type=expected_type)
    if ambiguity:
        return MatchResult(
            None,
            EvidenceVerdict.insufficient_data,
            -0.1,
            [label, "ambiguous_match", "needs_clarification"],
            [ambiguity, *_score_notes(ranked)],
            ranked,
        )

    tx = selected.transaction
    if tx.status in supporting_statuses:
        return MatchResult(
            tx.transaction_id,
            EvidenceVerdict.consistent,
            0.06,
            [label, "transaction_match"],
            [
                f"{tx.type.value} transaction {tx.transaction_id} has status "
                f"{tx.status.value}, which supports the complaint.",
                *_score_notes(ranked),
            ],
            ranked,
        )

    if tx.status in inconsistent_statuses:
        return MatchResult(
            tx.transaction_id,
            EvidenceVerdict.inconsistent,
            -0.06,
            [label, "evidence_inconsistent"],
            [
                f"{tx.type.value} transaction {tx.transaction_id} has status "
                f"{tx.status.value}, which does not support the complaint.",
                *_score_notes(ranked),
            ],
            ranked,
        )

    return MatchResult(
        tx.transaction_id,
        EvidenceVerdict.insufficient_data,
        -0.04,
        [label, "status_unclear"],
        [f"Transaction {tx.transaction_id} exists, but status {tx.status.value} is inconclusive.", *_score_notes(ranked)],
        ranked,
    )


def _rank_candidates(
    transactions: list[Transaction],
    normalized: NormalizedComplaint,
    *,
    expected_type: TransactionType | None,
    supporting_statuses: set[TransactionStatus],
    inconsistent_statuses: set[TransactionStatus],
) -> list[CandidateScore]:
    scores = [
        score_transaction_candidate(
            tx,
            normalized,
            expected_type=expected_type,
            supporting_statuses=supporting_statuses,
            inconsistent_statuses=inconsistent_statuses,
        )
        for tx in transactions
    ]
    return sorted(
        scores,
        key=lambda score: (
            score.total,
            score.breakdown.transaction_id,
            score.breakdown.phone_number,
            score.breakdown.amount,
            score.transaction.timestamp,
            score.transaction.transaction_id,
        ),
        reverse=True,
    )


def _select_scored_candidate(
    ranked: list[CandidateScore],
    *,
    expected_type: TransactionType | None,
) -> CandidateScore | None:
    for score in ranked:
        if score.total < MIN_MATCH_SCORE:
            continue
        if expected_type is not None and not score.has_expected_type and not score.has_decisive_reference:
            continue
        return score
    return None


def _detect_ambiguity(
    selected: CandidateScore,
    ranked: list[CandidateScore],
    *,
    expected_type: TransactionType | None,
) -> str | None:
    if selected.has_decisive_reference:
        return None

    rivals = [
        score
        for score in ranked
        if score.transaction.transaction_id != selected.transaction.transaction_id
        and score.total >= MIN_MATCH_SCORE
        and selected.total - score.total <= AMBIGUITY_SCORE_GAP
        and (expected_type is None or score.has_expected_type or score.has_decisive_reference)
    ]
    if not rivals:
        return None

    tied_ids = [selected.transaction.transaction_id] + [
        score.transaction.transaction_id for score in rivals
    ]
    return (
        f"Ambiguous match: {len(tied_ids)} transactions have similar deterministic "
        f"scores ({', '.join(tied_ids)}). Ask for transaction ID or counterparty."
    )


def _type_score(tx: Transaction, expected_type: TransactionType | None) -> int:
    if expected_type is None:
        return 0
    return TYPE_MATCH_SCORE if tx.type == expected_type else TYPE_MISMATCH_PENALTY


def _status_score(
    tx: Transaction,
    supporting_statuses: set[TransactionStatus],
    inconsistent_statuses: set[TransactionStatus],
) -> int:
    if tx.status in supporting_statuses:
        return STATUS_SUPPORT_SCORE
    if tx.status in inconsistent_statuses:
        return STATUS_INCONSISTENT_PENALTY
    return 0


def _pair_tiebreaker(
    first: Transaction,
    second: Transaction,
    closest_pair: tuple[Transaction, Transaction] | None,
) -> bool:
    if closest_pair is None:
        return True
    current_key = (second.timestamp, second.transaction_id, first.transaction_id)
    closest_key = (
        closest_pair[1].timestamp,
        closest_pair[1].transaction_id,
        closest_pair[0].transaction_id,
    )
    return current_key > closest_key


def _counterparty_phone_referenced(tx: Transaction, normalized: NormalizedComplaint) -> bool:
    counterparty_phone = normalize_phone_number(tx.counterparty)
    return bool(counterparty_phone and counterparty_phone in normalized.phones)


def _amount_relevant(tx: Transaction, amounts: list[Decimal]) -> bool:
    if not amounts:
        return True
    return any(_same_amount(tx.amount, amount) for amount in amounts)


def _same_amount(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) <= Decimal("0.01")


def _score_notes(ranked: list[CandidateScore], limit: int = 3) -> list[str]:
    if not ranked:
        return []
    top_scores = "; ".join(score.summary() for score in ranked[:limit])
    return [f"Candidate scores: {top_scores}."]


def _newest_first(transactions: list[Transaction]) -> list[Transaction]:
    return sorted(transactions, key=lambda tx: tx.timestamp, reverse=True)
