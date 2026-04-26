# Idempotency Gateway — FinSafe Transactions Ltd.

A production-grade payment idempotency layer built with **FastAPI (Python)**. Ensures every payment is processed **exactly once**, no matter how many times a client retries.

---

## Architecture Diagram

```
Client                     Idempotency Gateway              Payment Processor
  |                                |                                |
  |-- POST /api/process-payment -->|                                |
  |   Header: Idempotency-Key: X  |                                |
  |                                |                                |
  |              [ Is key in store? ]                               |
  |                    |       |                                    |
  |                   YES      NO                                   |
  |                    |       |                                    |
  |         [ Same body hash? ]  [ Is key in-flight? ]             |
  |           |        |            |          |                    |
  |          YES       NO          YES         NO                   |
  |           |        |            |          |                    |
  |    Return cached  409       Wait for    Mark in-flight          |
  |    response +   Conflict    result +    process payment ------->|
  |    X-Cache-Hit             X-Cache-Hit         |               |
  |        |                       |        Save to store          |
  |        |                       |        Complete in-flight      |
  |<-------+<----------------------+<--------------+               |
  |                   201 Created                                   |
```

**Flow Summary:**
1. Request arrives with `Idempotency-Key` header
2. Gateway checks the in-memory store for the key
3. **Found + same body** → return cached response instantly (no processing)
4. **Found + different body** → return `409 Conflict`
5. **In-flight** → wait for the first request to finish, return its result
6. **Not found** → process the payment, save result, return `201 Created`

---

## Setup Instructions

### Prerequisites
- Python 3.10+
- pip

### 1. Clone the repository
```bash
git clone <your-repo-url>
cd backend/Idempotency-gateway
```

### 2. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate      # Linux/Mac
venv\Scripts\activate         # Windows
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
```bash
cp .env.example .env
```

### 5. Start the server
```bash
python run.py
```

Server runs at `http://localhost:8000`

---

## API Documentation

### `GET /health`
Check if the server is running.

**Response:**
```json
{
  "status": "ok",
  "service": "FinSafe Idempotency Gateway"
}
```

---

### `POST /api/process-payment`

Process a payment. Requires a unique `Idempotency-Key` header.

**Headers:**
| Header | Required | Description |
|--------|----------|-------------|
| `Idempotency-Key` | Yes | Unique string per transaction (e.g. UUID) |
| `Content-Type` | Yes | `application/json` |

**Request Body:**
```json
{
  "amount": 100,
  "currency": "GHS"
}
```

**Example — First Request:**
```bash
curl -X POST http://localhost:8000/api/process-payment \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: pay_abc123" \
  -d '{"amount": 100, "currency": "GHS"}'
```

**Response `201 Created`:**
```json
{
  "status": "success",
  "message": "Charged 100.0 GHS",
  "transaction_id": "txn_a1b2c3d4e5f6",
  "amount": 100.0,
  "currency": "GHS",
  "processed_at": "2024-01-15T10:30:00.000000"
}
```

---

**Example — Duplicate Request (same key + same body):**
```bash
curl -X POST http://localhost:8000/api/process-payment \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: pay_abc123" \
  -d '{"amount": 100, "currency": "GHS"}'
```

**Response `201 Created` + Header `X-Cache-Hit: true`:**
```json
{
  "status": "success",
  "message": "Charged 100.0 GHS",
  "transaction_id": "txn_a1b2c3d4e5f6",
  ...
}
```

---

**Example — Payload Mismatch (same key, different body):**
```bash
curl -X POST http://localhost:8000/api/process-payment \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: pay_abc123" \
  -d '{"amount": 500, "currency": "GHS"}'
```

**Response `409 Conflict`:**
```json
{
  "error": "Idempotency key already used for a different request body."
}
```

---

**Error Responses:**

| Status | Cause |
|--------|-------|
| `400` | Missing `Idempotency-Key` header |
| `409` | Same key used with different request body |
| `422` | Invalid request body (e.g. negative amount, missing fields) |
| `500` | Internal server error |

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Design Decisions

### 1. In-Memory Store (Python Dictionary)
Used a plain Python dictionary wrapped in a class. No Redis or database required. This is sufficient for the challenge and keeps setup simple. In production, Redis would be used for distributed deployments.

### 2. SHA-256 Body Hashing
Request bodies are hashed with SHA-256 before storing. This allows comparing payloads efficiently without storing the full body, and prevents storing sensitive payment data in plain text.

### 3. asyncio.Event for In-Flight Requests
When two identical requests arrive simultaneously, the second one awaits an `asyncio.Event`. When the first request completes, it sets the event and the second request reads the result from the store. This avoids double-processing without locking or external queuing.

### 4. FastAPI Header Validation
FastAPI automatically maps the `idempotency_key` parameter to the `Idempotency-Key` HTTP header (underscore-to-hyphen conversion). Invalid bodies return `422` via Pydantic validation automatically.

---

## Developer's Choice: 24-Hour TTL Expiry

**Feature:** Every idempotency key automatically expires after **24 hours**.

**Why this matters for Fintech:**
- Idempotency keys should not live forever. A key stored indefinitely wastes memory and can cause confusion months later if a client reuses an old key.
- Stripe, PayPal, and other payment processors use 24-hour TTL as the industry standard.
- After expiry, the same key is treated as a completely new transaction — matching real-world retry window expectations.

**Implementation:**
- Each store entry has an `expires_at` timestamp (`now + 24 hours`)
- `store.get()` checks expiry on every read and silently deletes stale entries
- A background `asyncio` task runs every hour to sweep and remove all expired keys

---

## Pre-Submission Checklist

- [x] Repository is public
- [x] No `node_modules`, `.env` with real keys, or `.DS_Store`
- [x] `python run.py` starts the server immediately
- [x] Architecture diagram included
- [x] Original README replaced with this documentation
- [x] API endpoints documented with curl examples
- [x] Multiple meaningful commits
