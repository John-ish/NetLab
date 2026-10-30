import base64
import hashlib
import hmac
import os
import secrets
from functools import lru_cache

from .config import SECRET_PATH, ensure_private_dir, secure_path
from .errors import SecretError


SECRET_PREFIX = "enc1:"


@lru_cache(maxsize=1)
def secret_key() -> bytes:
    try:
        data = SECRET_PATH.read_bytes()
    except FileNotFoundError:
        data = None
    except OSError as error:
        raise SecretError(f"Cannot read {SECRET_PATH}: {error.strerror or error}") from error
    if data is not None:
        if len(data) != 32:
            raise SecretError(f"{SECRET_PATH} is damaged. Restore it from a backup")
        return data
    ensure_private_dir(SECRET_PATH.parent)
    key = secrets.token_bytes(32)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(SECRET_PATH, flags, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(key)
    except OSError as error:
        raise SecretError(f"Cannot create {SECRET_PATH}: {error.strerror or error}") from error
    secure_path(SECRET_PATH)
    return key


def _secret_keys() -> tuple[bytes, bytes]:
    master = secret_key()
    return (hmac.new(master, b"netlabdb-enc", hashlib.sha256).digest(),
            hmac.new(master, b"netlabdb-mac", hashlib.sha256).digest())


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    blocks, counter = [], 0
    while sum(len(b) for b in blocks) < length:
        blocks.append(hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest())
        counter += 1
    return b"".join(blocks)[:length]


def is_encrypted(token: str) -> bool:
    return token.startswith(SECRET_PREFIX)


def encrypt_secret(text: str) -> str:
    enc_key, mac_key = _secret_keys()
    nonce = secrets.token_bytes(16)
    data = text.encode("utf-8")
    cipher = bytes(a ^ b for a, b in zip(data, _keystream(enc_key, nonce, len(data))))
    tag = hmac.new(mac_key, nonce + cipher, hashlib.sha256).digest()
    return SECRET_PREFIX + base64.urlsafe_b64encode(nonce + cipher + tag).decode("ascii")


def decrypt_secret(token: str) -> str:
    if not is_encrypted(token):
        return token
    try:
        raw = base64.urlsafe_b64decode(token[len(SECRET_PREFIX):].encode("ascii"))
    except ValueError as error:
        raise SecretError("Stored password is corrupted") from error
    if len(raw) < 48:
        raise SecretError("Stored password is corrupted")
    nonce, cipher, tag = raw[:16], raw[16:-32], raw[-32:]
    enc_key, mac_key = _secret_keys()
    if not hmac.compare_digest(tag, hmac.new(mac_key, nonce + cipher, hashlib.sha256).digest()):
        raise SecretError("Stored password cannot be decrypted. Is secret.key the original?")
    return bytes(a ^ b for a, b in zip(cipher, _keystream(enc_key, nonce, len(cipher)))).decode("utf-8")
