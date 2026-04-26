import hashlib
import json


def hash_body(body: dict) -> str:
    normalized = json.dumps(body, sort_keys=True)
    return hashlib.sha256(normalized.encode()).hexdigest()
