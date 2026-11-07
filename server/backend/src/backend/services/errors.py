from __future__ import annotations


class ServiceError(ValueError):
    """A request a service refuses, and why.

    ``field`` names the form field the refusal is about, as the UI calls it
    (``outputTemplate``), so the API shows it under that field. ``kind`` says
    what kind of refusal it is, such as ``unique_violation``. The API answers
    with ``status_code``; other callers, such as the importer, report the message.
    """

    def __init__(
        self, message: str, *, field: str | None = None, status_code: int = 422, kind: str = "value_error",
    ) -> None:
        super().__init__(message)
        self.field = field
        self.status_code = status_code
        self.kind = kind


class NotFoundError(ServiceError):
    def __init__(self, what: str) -> None:
        super().__init__(f"{what} not found", status_code=404)
