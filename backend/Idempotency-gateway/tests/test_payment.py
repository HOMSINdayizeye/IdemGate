import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.store.idempotency_store import store


@pytest.fixture(autouse=True)
def clear_store():
    store.clear()
    yield
    store.clear()


# ─── User Story 1: Happy Path ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_successful_payment():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/process-payment",
            headers={"idempotency-key": "key-happy-001"},
            json={"amount": 100, "currency": "GHS"},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["message"] == "Charged 100.0 GHS"
    assert body["status"] == "success"
    assert "transaction_id" in body


@pytest.mark.asyncio
async def test_missing_idempotency_key_returns_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/process-payment",
            json={"amount": 100, "currency": "GHS"},
        )
    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["error"]


@pytest.mark.asyncio
async def test_invalid_body_missing_amount_returns_422():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/process-payment",
            headers={"idempotency-key": "key-invalid-001"},
            json={"currency": "GHS"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_invalid_body_negative_amount_returns_422():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/process-payment",
            headers={"idempotency-key": "key-invalid-002"},
            json={"amount": -50, "currency": "GHS"},
        )
    assert response.status_code == 422


# ─── User Story 2: Duplicate Request ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_request_returns_cached_response():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.post(
            "/api/process-payment",
            headers={"idempotency-key": "key-dup-001"},
            json={"amount": 200, "currency": "USD"},
        )
        second = await client.post(
            "/api/process-payment",
            headers={"idempotency-key": "key-dup-001"},
            json={"amount": 200, "currency": "USD"},
        )
    assert second.status_code == 201
    assert second.json() == first.json()


@pytest.mark.asyncio
async def test_duplicate_request_has_cache_hit_header():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/process-payment",
            headers={"idempotency-key": "key-dup-002"},
            json={"amount": 50, "currency": "EUR"},
        )
        second = await client.post(
            "/api/process-payment",
            headers={"idempotency-key": "key-dup-002"},
            json={"amount": 50, "currency": "EUR"},
        )
    assert second.headers.get("x-cache-hit") == "true"


@pytest.mark.asyncio
async def test_duplicate_request_returns_instantly():
    import time
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/process-payment",
            headers={"idempotency-key": "key-dup-003"},
            json={"amount": 75, "currency": "NGN"},
        )
        start = time.time()
        await client.post(
            "/api/process-payment",
            headers={"idempotency-key": "key-dup-003"},
            json={"amount": 75, "currency": "NGN"},
        )
        duration = time.time() - start
    assert duration < 0.5


# ─── User Story 3: Payload Mismatch ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_payload_mismatch_returns_409():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        await client.post(
            "/api/process-payment",
            headers={"idempotency-key": "key-mismatch-001"},
            json={"amount": 100, "currency": "GHS"},
        )
        second = await client.post(
            "/api/process-payment",
            headers={"idempotency-key": "key-mismatch-001"},
            json={"amount": 500, "currency": "GHS"},
        )
    assert second.status_code == 409
    assert "Idempotency key already used for a different request body" in second.json()["error"]


# ─── Bonus: In-Flight Race Condition ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_in_flight_race_condition():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        responses = await asyncio.gather(
            client.post(
                "/api/process-payment",
                headers={"idempotency-key": "key-inflight-001"},
                json={"amount": 300, "currency": "NGN"},
            ),
            client.post(
                "/api/process-payment",
                headers={"idempotency-key": "key-inflight-001"},
                json={"amount": 300, "currency": "NGN"},
            ),
        )
    statuses = [r.status_code for r in responses]
    assert all(s == 201 for s in statuses)

    cache_hits = [r.headers.get("x-cache-hit") for r in responses]
    assert cache_hits.count("true") >= 1


# ─── Developer's Choice: TTL Expiry ──────────────────────────────────────────

def test_expired_key_is_treated_as_new():
    from datetime import datetime, timedelta
    key = "key-ttl-001"
    store._store[key] = {
        "body_hash": "abc123",
        "status_code": 201,
        "response_body": {"message": "Charged 100.0 GHS"},
        "expires_at": datetime.utcnow() - timedelta(seconds=1),
    }
    result = store.get(key)
    assert result is None


def test_valid_key_is_returned_correctly():
    key = "key-ttl-002"
    store.set(key, "def456", 201, {"message": "Charged 200.0 USD"})
    result = store.get(key)
    assert result is not None
    assert result["response_body"]["message"] == "Charged 200.0 USD"
