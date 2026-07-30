"""GitHub webhook signature verification."""

import hashlib
import hmac


def verify_signature(body: bytes, signature: str | None, secret: str) -> bool:
    """Verify the exact body using GitHub's SHA-256 signature format."""
    if not signature or not signature.startswith("sha256="):
        return False
    supplied = signature.removeprefix("sha256=")
    if len(supplied) != 64:
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, supplied)
