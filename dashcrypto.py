#!/usr/bin/env python3
"""
dashcrypto.py — password-based encryption for the dashboard, compatible with the
browser's Web Crypto API (so Python encrypts, the browser decrypts).

Scheme (must stay in lock-step with the JS in dashboard.py's login shell):
  * key  = PBKDF2-HMAC-SHA256(password, salt, iterations) -> 32 bytes
  * ct   = AES-256-GCM(key, iv, plaintext)   (ct already carries the 16-byte tag
           at the end, which is exactly what Web Crypto's decrypt expects)

The published files hold only {salt, iv, ct} as base64 — never the password and
never the plaintext. Guest data therefore stays ciphertext at rest in a public
repo and on a public URL; it is readable only in the browser, after the correct
password is typed.
"""
import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ITERATIONS = 200_000  # PBKDF2 rounds; the JS side reads this from the blob


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def encrypt(plaintext: str, password: str, iterations: int = ITERATIONS) -> dict:
    """Encrypt a UTF-8 string; return a JSON-serialisable blob for the browser."""
    salt = os.urandom(16)
    iv = os.urandom(12)
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations,
                              dklen=32)
    ct = AESGCM(key).encrypt(iv, plaintext.encode("utf-8"), None)
    return {"v": 1, "iter": iterations, "salt": _b64(salt), "iv": _b64(iv),
            "ct": _b64(ct)}


def decrypt(blob: dict, password: str) -> str:
    """Inverse of encrypt() — used only by tests/CLI; the browser is the real client."""
    d = base64.b64decode
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                              d(blob["salt"]), blob["iter"], dklen=32)
    pt = AESGCM(key).decrypt(d(blob["iv"]), d(blob["ct"]), None)
    return pt.decode("utf-8")
