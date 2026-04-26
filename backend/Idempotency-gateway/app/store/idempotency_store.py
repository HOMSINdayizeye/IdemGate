import asyncio
from datetime import datetime, timedelta

TTL_HOURS = 24


class IdempotencyStore:
    def __init__(self):
        self._store: dict = {}
        self._in_flight: dict[str, asyncio.Event] = {}

    def get(self, key: str):
        entry = self._store.get(key)
        if not entry:
            return None
        if datetime.utcnow() > entry["expires_at"]:
            del self._store[key]
            return None
        return entry

    def set(self, key: str, body_hash: str, status_code: int, response_body: dict):
        self._store[key] = {
            "body_hash": body_hash,
            "status_code": status_code,
            "response_body": response_body,
            "expires_at": datetime.utcnow() + timedelta(hours=TTL_HOURS),
        }

    def is_in_flight(self, key: str) -> bool:
        return key in self._in_flight

    def mark_in_flight(self, key: str) -> asyncio.Event:
        event = asyncio.Event()
        self._in_flight[key] = event
        return event

    async def wait_for_in_flight(self, key: str):
        event = self._in_flight.get(key)
        if event:
            await event.wait()
        return self.get(key)

    def complete_in_flight(self, key: str):
        event = self._in_flight.pop(key, None)
        if event:
            event.set()

    def cleanup(self):
        now = datetime.utcnow()
        expired = [k for k, v in self._store.items() if now > v["expires_at"]]
        for k in expired:
            del self._store[k]

    def clear(self):
        self._store.clear()
        self._in_flight.clear()


store = IdempotencyStore()
