from sqlalchemy.orm import Mapped, mapped_column

from backend.db import Base


class SourceDomainPreference(Base):
    """The Source the user prefers for links on a domain that several Sources claim."""

    __tablename__ = "source_domain_preferences"

    domain: Mapped[str] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(comment="Id of the preferred Source, as registered in sources")
