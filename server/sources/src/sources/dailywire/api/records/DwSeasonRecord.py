from pydantic import Field

from sources.dailywire.api.records.BaseRecord import BaseRecord

class DwSeasonRecord(BaseRecord):
    dw_id: str = Field(validation_alias="id")
    name: str
    slug: str