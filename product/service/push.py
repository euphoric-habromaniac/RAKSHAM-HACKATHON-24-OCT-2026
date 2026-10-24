"""
L5: Out-of-band mobile banking app push confirmation.
Generates cryptographically signed tokens with a 30-second TTL to display on a real smartphone.
Enforces tamper-evident token validation.
"""

from typing import Dict, Any, Optional
import hmac
import hashlib
import time
import json
import base64
import logging
import os

_DEMO_SECRET = "asli-awaaz-demo-secret-key-32bytes!"
_env_secret = os.environ.get("ASLI_APP_SECRET")
if not _env_secret:
    logging.getLogger(__name__).warning(
        "ASLI_APP_SECRET is not set: signing push-prompt tokens with the public DEMO secret. "
        "Set ASLI_APP_SECRET before any real use.")
SECRET_KEY = (_env_secret or _DEMO_SECRET).encode("utf-8")
DEFAULT_PROMPT_TTL_SECONDS = 30.0


def generate_prompt_token(
    call_id: str,
    customer_id: str,
    request_type: str,
    amount: Optional[float] = None,
    payee: Optional[str] = None,
    ttl_seconds: float = DEFAULT_PROMPT_TTL_SECONDS,
) -> str:
    """Generates a base64url signed token encoding the push prompt."""
    payload = {
        "call_id": call_id,
        "customer_id": customer_id,
        "request_type": request_type,
        "amount": amount,
        "payee": payee,
        "expires_at": time.time() + ttl_seconds,
        "nonce": os.urandom(8).hex(),
    }
    raw_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    b64_payload = base64.urlsafe_b64encode(raw_payload).decode("ascii").rstrip("=")
    
    sig = hmac.new(SECRET_KEY, b64_payload.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{b64_payload}.{sig}"


def verify_prompt_token(token: str, current_time: Optional[float] = None) -> Dict[str, Any]:
    """
    Verifies token signature and expiration.
    Raises ValueError on tampering, bad signature, or expiration.
    """
    now = current_time if current_time is not None else time.time()
    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("Malformed prompt token format.")
    
    b64_payload, sig = parts
    expected_sig = hmac.new(SECRET_KEY, b64_payload.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError("Cryptographic signature verification failed: prompt token tampered.")
    
    # Pad base64 if needed
    padded = b64_payload + "=" * ((4 - len(b64_payload) % 4) % 4)
    data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    
    if data.get("expires_at", 0) < now:
        raise ValueError("Prompt token has expired.")
    
    return data
