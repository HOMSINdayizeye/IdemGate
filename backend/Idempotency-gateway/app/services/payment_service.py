import asyncio
import uuid
from datetime import datetime


async def process_payment(amount: float, currency: str) -> dict:
    await asyncio.sleep(2)
    return {
        "status": "success",
        "message": f"Charged {amount} {currency}",
        "transaction_id": f"txn_{uuid.uuid4().hex[:12]}",
        "amount": amount,
        "currency": currency,
        "processed_at": datetime.utcnow().isoformat(),
    }
