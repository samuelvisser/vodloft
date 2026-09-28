"""Encrypted per-connection secrets, never returned by normal API reads."""

import os
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

from .runtime import runtime_root


def _root() -> Path:
    root = runtime_root().parent / "source-secrets"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _cipher() -> Fernet:
    path = _root() / "key"
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(descriptor, "wb") as output:
            output.write(Fernet.generate_key())
    return Fernet(path.read_bytes())


def save(value: str, previous: str | None = None) -> str:
    reference = previous or secrets.token_hex(32)
    if not reference.isalnum():
        raise ValueError("Invalid secret reference")
    directory = _root()
    temporary = directory / f".{secrets.token_hex(16)}"
    temporary.write_bytes(_cipher().encrypt(value.encode()))
    temporary.chmod(0o600)
    os.replace(temporary, directory / reference)
    return reference


def read(reference: str | None) -> str | None:
    if not reference:
        return None
    if not reference.isalnum():
        raise ValueError("Invalid secret reference")
    return _cipher().decrypt((_root() / reference).read_bytes()).decode()


def remove(reference: str | None) -> None:
    if reference:
        if not reference.isalnum():
            raise ValueError("Invalid secret reference")
        (_root() / reference).unlink(missing_ok=True)
