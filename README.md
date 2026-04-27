# Idempotency Gateway — FinSafe Transactions Ltd.

A payment idempotency layer built with **Python (FastAPI)** that guarantees every payment is processed **exactly once**, no matter how many times a client retries the same request.

##  Documents available in this readme.md

- [Architecture Diagram](#architecture-diagram)
- [Setup Instructions](#setup-instructions)
- [API Documentation](#api-documentation)
- [Design Decisions](#design-decisions)
- [Developer's Choice](#developers-choice-24-hour-ttl-expiry)
- [Running Tests](#running-tests)

## Architecture Diagram

### Sequence Diagram

The diagram below shows the full request lifecycle through the gateway.

sequenceDiagram
    participant C as Client
    participant G as Idempotency Gateway
    participant S as In-Memory Store
    participant P as Payment Processor

    C->>G: POST /api/process-payment\nIdempotency-Key: abc123\n{ amount: 100, currency: GHS }

    G->>G: Validate header and body

    G->>S: Lookup key "abc123"

    alt Key found — same body
        S-->>G: Return cached entry
        G-->>C: 201 Created + X-Cache-Hit: true (instant)

    else Key found — different body
        S-->>G: Return cached entry
        G-->>C: 409 Conflict

    else Key is in-flight (concurrent request)
        G->>G: Await asyncio.Event
        G->>S: Read result after event fires
        G-->>C: 201 Created + X-Cache-Hit: true

    else Key not found
        S-->>G: null
        G->>G: Mark key as in-flight
        G->>P: Process payment (2s simulated delay)
        P-->>G: { status: success, transaction_id: txn_... }
        G->>S: Save result with 24h TTL
        G->>G: Signal in-flight complete
        G-->>C: 201 Created
    end
```
===========================================
## Flowchart
===========================================
flowchart TD
    A([Client Request]) --> B{Idempotency-Key\nheader present?}
    B -- No --> C[400 Bad Request]
    B -- Yes --> D{Valid body?\namount and currency}
    D -- No --> E[422 Unprocessable Entity]
    D -- Yes --> F{Key exists\nin store?}

    F -- Yes --> G{Same body hash?}
    G -- Yes --> H[Return cached response\nX-Cache-Hit: true]
    G -- No --> I[409 Conflict\nKey reused with different body]

    F -- No --> J{Key currently\nin-flight?}
    J -- Yes --> K[Wait on asyncio.Event\nuntil first request finishes]
    K --> L[Return result\nX-Cache-Hit: true]

    J -- No --> M[Mark key as in-flight]
    M --> N[Send to Payment Processor\n2 second delay]
    N --> O[Save result to store\nwith 24h TTL]
    O --> P[Signal in-flight complete]
    P --> Q([201 Created])
```

---

## Setup Instructions

### Prerequisites

- Python 3.10 or higher
- pip

### 1. Clone the repository

```bash
git clone https://github.com/HOMSINdayizeye/IdemGate.git
cd backend/Idempotency-gateway
```

### 2. Create a virtual environment

```bash
python -m venv venv

# Activate on Linux/Mac
source venv/bin/activate

# Activate on Windows
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up environment variables

```bash
cp .env.example .env
```

The `.env.example` file contains:

```
PORT=8000
```

### 5. Start the server

```bash
python run.py
```

Server will be running at `http://localhost:8000`

---

## API Documentation

### `GET /health`

Check that the server is running.

**Response `200 OK`:**
```json
{
  "status": "ok",
  "service": "FinSafe Idempotency Gateway"
}
```

---

### `POST /api/process-payment`

Process a payment. The client must include a unique `Idempotency-Key` header with every request.

**Required Headers:**

| Header            | Description                                      |
|-------------------|--------------------------------------------------|
| `Idempotency-Key` | A unique string per transaction (e.g. a UUID)    |
| `Content-Type`    | `application/json`                               |

**Request Body:**

| Field      | Type   | Required | Description                    |
|------------|--------|----------|--------------------------------|
| `amount`   | float  | Yes      | Payment amount, must be > 0    |
| `currency` | string | Yes      | Currency code e.g. GHS, USD    |

---

#### Example 1 — First payment request

```bash
curl -X POST http://localhost:8000/api/process-payment \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: pay-uuid-001" \
  -d '{"amount": 100, "currency": "GHS"}'
```

**Response `201 Created`** *(after ~2 second processing delay)*:

```json
{
  "status": "success",
  "message": "Charged 100.0 GHS",
  "transaction_id": "txn_a1b2c3d4e5f6",
  "amount": 100.0,
  "currency": "GHS",
  "processed_at": "2024-01-15T10:30:00.123456"
}
```

---

#### Example 2 — Duplicate request (same key, same body)

```bash
curl -X POST http://localhost:8000/api/process-payment \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: pay-uuid-001" \
  -d '{"amount": 100, "currency": "GHS"}'
```

**Response `201 Created`** *(instant, no delay)*:

Response body is identical to the first request.
Response includes the header: `X-Cache-Hit: true`

---

#### Example 3 — Same key, different amount (fraud/error check)

```bash
curl -X POST http://localhost:8000/api/process-payment \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: pay-uuid-001" \
  -d '{"amount": 500, "currency": "GHS"}'
```

**Response `409 Conflict`:**

```json
{
  "error": "Idempotency key already used for a different request body."
}
```

---

#### Example 4 — Missing Idempotency-Key header

```bash
curl -X POST http://localhost:8000/api/process-payment \
  -H "Content-Type: application/json" \
  -d '{"amount": 100, "currency": "GHS"}'
```

**Response `400 Bad Request`:**

```json
{
  "error": "Missing required header: Idempotency-Key"
}
```

---

#### Example 5 — Invalid body (negative amount)

```bash
curl -X POST http://localhost:8000/api/process-payment \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: pay-uuid-002" \
  -d '{"amount": -50, "currency": "GHS"}'
```

**Response `422 Unprocessable Entity`**

---

#### Error Response Summary

| Status Code | Cause                                            |
|-------------|--------------------------------------------------|
| `400`       | `Idempotency-Key` header is missing or empty     |
| `409`       | Key already used with a different request body   |
| `422`       | Invalid body — missing fields or invalid values  |
| `500`       | Internal server error                            |

---

## Design Decisions

### 1. In-Memory Store using a Python Dictionary

I chose to use a plain Python dictionary wrapped in a class (`IdempotencyStore`) rather than setting up Redis or a database. This keeps the project dependency-free and easy to run locally. The dictionary is sufficient for the scale of this challenge. In a real production environment, I would swap this for Redis to support multiple server instances and survive restarts.

### 2. SHA-256 Hashing for Body Comparison

Instead of storing the full request body, I hash it with SHA-256 before saving. When a duplicate request arrives, I compare the hashes. This is memory efficient and also avoids storing raw payment data (amounts, currencies) in plain text in memory, which is a good practice for any financial system.

### 3. asyncio.Event for Concurrent In-Flight Requests

The bonus user story requires handling two identical requests arriving at the exact same time. I solved this using Python's built-in `asyncio.Event`. When the first request starts processing, I mark the key as in-flight and attach an Event to it. If a second request with the same key arrives before the first finishes, it awaits the Event. Once the first request completes and saves its result, it fires the Event and the waiting request reads the result from the store and returns it. No second payment is ever processed.

### 4. Pydantic Models for Validation

I used FastAPI's Pydantic integration to validate the request body. The `PaymentRequest` model enforces that `amount` is a positive number and `currency` is a non-empty string. FastAPI returns a clear `422` response automatically when the body is invalid, without any manual if-statement checks needed in the route.

### 5. FastAPI Lifespan for Background Cleanup

I used FastAPI's `lifespan` context manager to start a background `asyncio` task when the server boots. This task runs every hour and clears expired keys from the store. This prevents memory from growing unbounded over time.

---

## Developer's Choice: 24-Hour TTL Expiry

**Feature:** Every idempotency key stored in the gateway automatically expires after **24 hours**.

**Why I added this:**

In a real Fintech system, idempotency keys cannot live forever. If a key is stored permanently:
- Memory grows without limit over time, eventually crashing the server
- A key from months ago could accidentally block a legitimate new transaction if a client reuses a key pattern
- It creates a compliance risk since payment audit records should have clear retention policies

The industry standard (used by Stripe and PayPal) is a **24-hour TTL** on idempotency keys. This matches the realistic retry window — if a client hasn't retried within 24 hours, the original transaction concern has passed.

**How it works:**

- Every entry saved to the store includes an `expires_at` timestamp (`now + 24 hours`)
- The `store.get()` method checks expiry on every read and silently deletes the entry if it has expired
- A background task runs every hour via `asyncio` to sweep and remove all stale entries proactively

---

## Running Tests

```bash
cd backend/Idempotency-gateway
python -m pytest tests/ -v
```

The test suite covers:

| Test | User Story |
|------|------------|
| Successful payment returns 201 | Story 1 |
| Missing header returns 400 | Story 1 |
| Invalid body returns 422 | Story 1 |
| Duplicate request returns cached response | Story 2 |
| Duplicate request has `X-Cache-Hit: true` | Story 2 |
| Duplicate request returns instantly | Story 2 |
| Payload mismatch returns 409 | Story 3 |
| Concurrent requests do not double-charge | Bonus |
| Expired key is treated as new request | Developer's Choice |
| Valid key is returned correctly | Developer's Choice |
