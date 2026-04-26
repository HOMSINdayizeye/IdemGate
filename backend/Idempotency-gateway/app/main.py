import os
import time
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from app.store.idempotency_store import store
from app.services.payment_service import process_payment
from app.utils.hash_body import hash_body
from app.models.payment import PaymentRequest


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()


async def _cleanup_loop():
    while True:
        await asyncio.sleep(3600)
        store.cleanup()
        logging.info("Ran idempotency store cleanup")


app = FastAPI(title="FinSafe Idempotency Gateway", lifespan=lifespan)


# ── Logging middleware ────────────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    key = request.headers.get("idempotency-key", "-")
    logging.info(
        f"{request.method} {request.url.path} {response.status_code} "
        f"{duration:.0f}ms key={key}"
    )
    return response


# ── Global exception handler ─────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logging.error(f"Unhandled error: {exc}")
    return JSONResponse(status_code=500, content={"error": "Internal server error"})


# ── Health check ─────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "FinSafe Idempotency Gateway"}


# ── Payment route ─────────────────────────────────────────────────────────────

@app.post("/api/process-payment", status_code=201)
async def process_payment_route(
    payment: PaymentRequest,
    idempotency_key: Optional[str] = Header(None),
):
    # Validate Idempotency-Key header
    if not idempotency_key or not idempotency_key.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "Missing required header: Idempotency-Key"},
        )

    key = idempotency_key.strip()
    body_hash = hash_body(payment.model_dump())

    # Check store for existing entry
    existing = store.get(key)
    if existing:
        # Same key, different body — reject
        if existing["body_hash"] != body_hash:
            return JSONResponse(
                status_code=409,
                content={
                    "error": "Idempotency key already used for a different request body."
                },
            )
        # Same key, same body — return cached response
        return JSONResponse(
            status_code=existing["status_code"],
            content=existing["response_body"],
            headers={"X-Cache-Hit": "true"},
        )

    # In-flight check — another request with same key is being processed
    if store.is_in_flight(key):
        result = await store.wait_for_in_flight(key)
        return JSONResponse(
            status_code=result["status_code"],
            content=result["response_body"],
            headers={"X-Cache-Hit": "true"},
        )

    # Mark as in-flight before processing
    store.mark_in_flight(key)
    try:
        result = await process_payment(payment.amount, payment.currency)
        store.set(key, body_hash, 201, result)
        return JSONResponse(status_code=201, content=result)
    finally:
        store.complete_in_flight(key)
