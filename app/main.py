from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.models import AnalysisResponse, TicketRequest
from app.services.analyzer import analyze_ticket


app = FastAPI(
    title="QueueStorm Investigator",
    version="1.0.0",
    description="Rule-based FastAPI service for support-ticket investigation.",
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_, exc: RequestValidationError) -> JSONResponse:
    status_code = 400
    message = "Invalid request body."
    for error in exc.errors():
        location = tuple(error.get("loc", ()))
        if "complaint" in location and "empty" in str(error.get("msg", "")).lower():
            status_code = 422
            message = "Complaint must not be empty."
            break
    return JSONResponse(status_code=status_code, content={"error": message})


@app.exception_handler(Exception)
async def generic_exception_handler(_, __: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"error": "Internal error while analyzing ticket."},
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/analyze-ticket", response_model=AnalysisResponse)
async def analyze_ticket_endpoint(request: TicketRequest) -> AnalysisResponse:
    return analyze_ticket(request)

