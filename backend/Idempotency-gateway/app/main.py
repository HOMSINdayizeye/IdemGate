import os
import time
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse, HTMLResponse  # Added HTMLResponse
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Ensure these imports match your actual file structure
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

# ── NEW: Root Dashboard Route ───────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def get_test_dashboard():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>FinSafe | Idempotency Gateway Test</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            .bg-finsafe-orange { background-color: #FF8C00; }
            .text-finsafe-orange { color: #FF8C00; }
            .border-finsafe-orange { border-color: #FF8C00; }
        </style>
    </head>
    <body class="bg-gray-50 min-h-screen font-sans">
        <nav class="bg-finsafe-orange p-4 text-white shadow-lg">
            <div class="container mx-auto flex justify-between items-center">
                <h1 class="text-2xl font-bold">FinSafe <span class="font-light">Idempotency Gateway</span></h1>
                <span class="bg-white text-finsafe-orange px-3 py-1 rounded-full text-sm font-bold uppercase">Live Environment</span>
            </div>
        </nav>

        <main class="container mx-auto p-6 grid grid-cols-1 lg:grid-cols-2 gap-8">
            <div class="bg-white p-8 rounded-xl shadow-md border-t-4 border-finsafe-orange">
                <h2 class="text-xl font-semibold mb-6 text-gray-800 border-b pb-2">Simulation Controls</h2>
                
                <div class="space-y-5">
                    <div>
                        <label class="block text-sm font-bold text-gray-600 mb-1 uppercase tracking-tight">Idempotency-Key (Header)</label>
                        <div class="flex gap-2">
                            <input type="text" id="idKey" class="flex-1 p-3 border rounded-lg focus:ring-2 focus:ring-orange-300 outline-none" value="pay-uuid-001">
                            <button onclick="generateUUID()" class="bg-gray-100 px-4 rounded-lg hover:bg-gray-200 transition">Regen</button>
                        </div>
                    </div>
                    
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm font-bold text-gray-600 mb-1 uppercase tracking-tight">Amount</label>
                            <input type="number" id="amount" class="w-full p-3 border rounded-lg outline-none" value="100">
                        </div>
                        <div>
                            <label class="block text-sm font-bold text-gray-600 mb-1 uppercase tracking-tight">Currency</label>
                            <input type="text" id="currency" class="w-full p-3 border rounded-lg outline-none" value="GHS">
                        </div>
                    </div>

                    <button onclick="sendPayment()" id="sendBtn" class="w-full bg-finsafe-orange text-white font-black py-4 rounded-lg hover:bg-orange-600 transition-all shadow-md active:scale-95">
                        SEND PAYMENT REQUEST
                    </button>
                    
                    <div class="grid grid-cols-2 gap-4 pt-4 border-t">
                        <button onclick="testConcurrent()" class="bg-blue-500 text-white py-2 rounded-lg text-sm font-bold hover:bg-blue-600">Simulate Race (Bonus)</button>
                        <button onclick="testConflict()" class="bg-red-500 text-white py-2 rounded-lg text-sm font-bold hover:bg-red-600">Test Payload Conflict</button>
                    </div>
                </div>
            </div>

            <div class="flex flex-col h-full">
                <div class="bg-gray-900 text-gray-300 px-4 py-2 rounded-t-xl font-mono text-xs flex justify-between items-center">
                    <span>GATEWAY_LOGS.log</span>
                    <button onclick="clearLogs()" class="hover:text-white">Clear</button>
                </div>
                <div id="output" class="bg-gray-800 text-white p-4 rounded-b-xl flex-1 font-mono text-xs overflow-y-auto min-h-[500px] max-h-[650px] shadow-inner">
                    <p class="text-gray-500 opacity-50 italic">// No traffic detected yet...</p>
                </div>
            </div>
        </main>

        <script>
            async function log(type, msg, meta = null) {
                const output = document.getElementById('output');
                const time = new Date().toLocaleTimeString();
                let color = "text-white";
                if(type === 'FAIL') color = "text-red-400";
                if(type === 'SUCCESS') color = "text-green-400";
                if(type === 'WAIT') color = "text-blue-300";

                const entry = document.createElement('div');
                entry.className = `mb-4 pb-4 border-b border-gray-700 ${color}`;
                entry.innerHTML = `
                    <div class="flex justify-between text-[10px] uppercase font-bold opacity-60 mb-2">
                        <span>[${time}] ${type}</span>
                        <span>${meta || ''}</span>
                    </div>
                    <pre class="whitespace-pre-wrap leading-relaxed">${JSON.stringify(msg, null, 2)}</pre>
                `;
                output.prepend(entry);
            }

            async function sendPayment() {
                const btn = document.getElementById('sendBtn');
                const key = document.getElementById('idKey').value;
                const body = {
                    amount: parseFloat(document.getElementById('amount').value),
                    currency: document.getElementById('currency').value
                };

                btn.disabled = true;
                btn.style.opacity = "0.5";
                
                try {
                    const start = Date.now();
                    const resp = await fetch('/api/process-payment', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Idempotency-Key': key },
                        body: JSON.stringify(body)
                    });
                    const duration = Date.now() - start;
                    const data = await resp.json();
                    
                    const hit = resp.headers.get('X-Cache-Hit') === 'true';
                    log(resp.ok ? 'SUCCESS' : 'FAIL', data, `STATUS: ${resp.status} | TIME: ${duration}ms | CACHE: ${hit}`);
                } catch (e) {
                    log('FAIL', e.message);
                } finally {
                    btn.disabled = false;
                    btn.style.opacity = "1";
                }
            }

            function generateUUID() {
                document.getElementById('idKey').value = 'pay-' + Math.random().toString(36).substr(2, 9);
            }

            function clearLogs() {
                document.getElementById('output').innerHTML = '';
            }

            async function testConcurrent() {
                const key = 'race-' + Math.random().toString(36).substr(2, 5);
                document.getElementById('idKey').value = key;
                log('WAIT', `Firing 2 simultaneous requests with key: ${key}`);
                await Promise.all([sendPayment(), sendPayment()]);
            }

            async function testConflict() {
                const key = 'conflict-' + Math.random().toString(36).substr(2, 5);
                document.getElementById('idKey').value = key;
                document.getElementById('amount').value = 100;
                log('WAIT', 'Scenario: Same key, different body...');
                await sendPayment();
                document.getElementById('amount').value = 500;
                setTimeout(() => sendPayment(), 500);
            }
        </script>
    </body>
    </html>
    """

# ── LOGGING MIDDLEWARE ────────────────────────────────────────────────────────

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    key = request.headers.get("idempotency-key", "-")
    logging.info(f"{request.method} {request.url.path} {response.status_code} {duration:.0f}ms key={key}")
    return response

# ── EXISTING APIS ─────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok", "service": "FinSafe Idempotency Gateway"}

@app.post("/api/process-payment", status_code=201)
async def process_payment_route(
    payment: PaymentRequest,
    idempotency_key: Optional[str] = Header(None),
):
    if not idempotency_key or not idempotency_key.strip():
        return JSONResponse(status_code=400, content={"error": "Missing required header: Idempotency-Key"})

    key = idempotency_key.strip()
    body_hash = hash_body(payment.model_dump())

    existing = store.get(key)
    if existing:
        if existing["body_hash"] != body_hash:
            return JSONResponse(status_code=409, content={"error": "Idempotency key already used for a different request body."})
        # and add an attribute which says this is a cache hit
        return JSONResponse(status_code=existing["status_code"], content=existing["response_body"], headers={"X-Cache-Hit": "true"})

    if store.is_in_flight(key):
        result = await store.wait_for_in_flight(key)
        return JSONResponse(status_code=result["status_code"], content=result["response_body"], headers={"X-Cache-Hit": "true"})

    store.mark_in_flight(key)
    try:
        result = await process_payment(payment.amount, payment.currency)
        store.set(key, body_hash, 201, result)
        return JSONResponse(status_code=201, content=result)
    finally:
        store.complete_in_flight(key)