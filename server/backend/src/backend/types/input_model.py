from __future__ import annotations

from pydantic import AliasGenerator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel, to_snake


class InputModel(BaseModel):
    """Validated input to a service.

    It takes field names in camelCase, as the UI sends them, or in snake_case, as
    Python callers such as the importer write them, and dumps them in snake_case.
    """

    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            serialization_alias=to_snake,
            validation_alias=to_camel,
        ),
        populate_by_name=True,
        from_attributes=True,
        extra="ignore",
        use_enum_values=True,
    )
