from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional

import keyring
from keyring.errors import PasswordDeleteError

from sources.dailywire.auth.config import OAuthTokens
from sources.dailywire.membership import forget_level


class TokenStore:
    """
    Keyring-only token storage. No file fallback by design.
    Fails fast if the system keyring is unusable.
    """

    def __init__(self, service_name: str = "vodloft-dailywire-auth"):
        self.service_name = service_name
        # Basic sanity check: some keyring backends return None silently.
        try:
            backend = keyring.get_keyring()
            if backend is None:
                raise RuntimeError("No usable keyring backend found.")
        except Exception as e:
            raise RuntimeError("Failed to initialize keyring backend.") from e

    def _get(self, key: str) -> Optional[str]:
        try:
            return keyring.get_password(self.service_name, key)
        except Exception as e:
            raise RuntimeError("Failed to read from OS keyring.") from e

    def _set(self, key: str, value: str) -> None:
        try:
            keyring.set_password(self.service_name, key, value)
        except Exception as e:
            raise RuntimeError("Failed to write to OS keyring.") from e
        finally:
            # The account signed in may be another one now.
            forget_level()

    def store_record(self, key: str, record: str) -> None:
        """Store a record that is already in this store's JSON form, such as one another program kept."""
        self._set(key, record)

    def _delete(self, key: str) -> None:
        forget_level()
        try:
            keyring.delete_password(self.service_name, key)
        except PasswordDeleteError:
            # ignore if already gone
            return
        except Exception as e:
            raise RuntimeError("Failed to delete from OS keyring.") from e

    def load(self, key: str) -> Optional[OAuthTokens]:
        raw = self._get(key)
        if not raw:
            return None
        d = json.loads(raw)
        return OAuthTokens(**d)

    def save(self, key: str, record: OAuthTokens) -> None:
        payload = json.dumps(asdict(record))
        self._set(key, payload)

    def delete(self, key: str) -> None:
        self._delete(key)
