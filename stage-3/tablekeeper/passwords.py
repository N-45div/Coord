"""Password hashing with scrypt (§6). Only the encoded hash is ever stored or exported."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading

# Cost chosen so 50 simultaneous signups finish well inside the 5 s budget on 2 vCPU;
# at most 4 hashes run at once, which bounds their memory (8 MiB each).
_N, _R, _P, _LEN = 2**13, 8, 1, 32
_SLOTS = threading.BoundedSemaphore(4)


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    with _SLOTS:
        return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _scrypt(password, salt, _N, _R, _P, _LEN)
    return f"scrypt${_N}${_R}${_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected_raw = base64.b64decode(expected)
        digest = _scrypt(password, base64.b64decode(salt), int(n), int(r), int(p),
                         len(expected_raw))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected_raw)


def is_valid_hash(encoded) -> bool:
    """Shape check used when importing state."""
    if not isinstance(encoded, str):
        return False
    parts = encoded.split("$")
    if len(parts) != 6 or parts[0] != "scrypt" or not all(p.isdigit() for p in parts[1:4]):
        return False
    n, r, p = (int(x) for x in parts[1:4])
    return 2 <= n <= 2**16 and 1 <= r <= 16 and 1 <= p <= 4


# Verified against when a login names an unknown email, so both failures cost the same.
DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
