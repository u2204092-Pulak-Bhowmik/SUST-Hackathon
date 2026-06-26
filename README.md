# QueueStorm Investigator

FastAPI service for the SUST CSE Carnival 2026 QueueStorm Investigator preliminary challenge.

## Endpoints

- `GET /health` returns `{"status":"ok"}`
- `POST /analyze-ticket` accepts one ticket and returns the required structured investigation response.
- `GET /api-docs` opens Swagger UI for interactive testing.
- `GET /redoc` opens ReDoc for API schema browsing.

## Tech Stack

- Python 3.12
- FastAPI
- Pydantic v2
- Pytest
- Docker

## Run Locally

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Optional environment variables:

- `PORT`: runtime port if your host platform uses one. The documented command uses `8000`.
- `DUPLICATE_WINDOW_SECONDS`: duplicate-payment matching window. Defaults to `86400`.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Docker

```bash
docker build -t queuestorm-investigator .
docker run -p 8000:8000 queuestorm-investigator
```

## Test

```bash
pytest
```

## Sample Output

`sample_output.json` contains one generated response from the public sample pack.

## Sample Request

```bash
curl -X POST http://localhost:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d '{
    "ticket_id": "TKT-001",
    "complaint": "I sent 5000 taka to a wrong number around 2pm today. Please help.",
    "language": "en",
    "transaction_history": [
      {
        "transaction_id": "TXN-9101",
        "timestamp": "2026-04-14T14:08:22Z",
        "type": "transfer",
        "amount": 5000,
        "counterparty": "+8801719876543",
        "status": "completed"
      }
    ]
  }'
```

## Approach

The service uses deterministic rule-based logic. It normalizes complaint text, extracts amounts and identifiers, classifies the case type, matches relevant transactions, determines an evidence verdict, drafts safe agent/customer text, and validates the final response through Pydantic.

Local-language normalization includes Bangla digit conversion, Bangladesh phone-number canonicalization to `+8801XXXXXXXXX`, and Bangla/Banglish keyword detection for common support phrases.

Transaction matching is scored deterministically:

- transaction ID match: `100`
- amount match: `35`
- expected transaction type match: `25`
- phone/counterparty match: `30`
- supporting status match: `15`
- type mismatch or contradictory status: negative penalty

If multiple eligible transactions have similar top scores and there is no decisive transaction ID or phone-number reference, the service returns `insufficient_data` with `ambiguous_match` instead of guessing.

Duplicate-payment matching uses `DUPLICATE_WINDOW_SECONDS` and defaults to a 24-hour same-day window. Completed duplicate debits are treated as consistent evidence; pending duplicate legs are flagged for verification.

The business logic is split across:

- `normalization.py`: text cleanup, Bangla digit handling, amount and identifier extraction
- `classification.py`: case taxonomy and English/Bangla/Banglish routing signals
- `transaction_matching.py`: transaction candidate selection and evidence verdicts
- `safety_templates.py`: safe summaries, next actions, and customer replies
- `safety.py`: centralized safety checks and safe fallback text
- `output_validation.py`: final schema and safety repair pass
- `config.py`: optional runtime configuration such as duplicate-payment window

## Models

No external AI API or local LLM is used at runtime. The service is fully rule-based to avoid network, quota, latency, cost, or secret dependency during judging.

## Safety Logic

- Never asks customers for PIN, OTP, password, or full card number.
- Avoids refund, reversal, recovery, or account-unblock promises.
- Uses "any eligible amount will be returned through official channels" style wording.
- Escalates phishing/social-engineering reports to `fraud_risk`.
- Ignores prompt-injection instructions inside complaint text.

## Assumptions

- Transaction histories are short, synthetic, and already scoped to the relevant customer.
- Hidden tests follow the enum values and request schema from the problem statement.
- Merchant refund eligibility is policy-dependent and should not be promised by this service.

## Known Limitations

- Language handling is rule-based and keyword driven.
- It does not call payment, ledger, fraud, or merchant systems.
- Very unusual phrasing may be routed as `other` with clarification requested.
