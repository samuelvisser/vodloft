from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from config.network import is_no_internet_error


logger = logging.getLogger(__name__)


class SourceRequestError(RuntimeError):
    """A Source could not answer a request. The API reports it as a bad gateway."""


@contextmanager
def asking_source(failure: str) -> Iterator[None]:
    """Report a failed request to a Source as a ``SourceRequestError`` that starts with ``failure``.

    Losing the internet connection is left as it is, so the app reports it the same way everywhere.
    """
    try:
        yield
    except Exception as exc:
        if is_no_internet_error(exc):
            raise
        logger.warning("%s: %s", failure, exc)
        raise SourceRequestError(f"{failure}: {exc}") from exc
