from __future__ import annotations


class ServiceError(ValueError):
    """A request a service refuses, and why.

    ``field`` names the form field the refusal is about, as the UI calls it
    (``outputTemplate``), so the API shows it under that field. ``kind`` says
    what kind of refusal it is, such as ``unique_violation``. The API answers
    with ``status_code``; other callers, such as the importer, report the message.

    A refusal that more than one field can fix also names those in
    ``other_fields``, each with what to say under it, so the form marks every
    field the user may change.
    """

    def __init__(
        self, message: str, *, field: str | None = None, status_code: int = 422, kind: str = "value_error",
        other_fields: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.field = field
        self.status_code = status_code
        self.kind = kind
        self.other_fields = other_fields or {}


class FieldValueError(ValueError):
    """A model validator's refusal that one field can fix.

    Pydantic places the error of a model validator on the whole model; the API
    moves it under ``field`` (the Python field name), so the form shows it there.
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


class NotFoundError(ServiceError):
    def __init__(self, what: str) -> None:
        super().__init__(f"{what} not found", status_code=404)
