"""Keep The Daily Wire on the refresh schedule the user set.

Until now one schedule, from the config file, applied to every episode, and only
The Daily Wire's were refreshed. That setting is now the system schedule, which
Sites without a schedule of their own follow, and The Daily Wire has its own. A
schedule the user set in the config file therefore moves to The Daily Wire, so its
episodes are refreshed as before. Reading the config file is why this is not part
of the database migration.

Revision ID: 5df6a8811f86
Revises: 7ffa406cf785
"""

from __future__ import annotations

from backend.db.core import get_session
from backend.db.models import Site
from backend.types.site_types import SiteRefreshMode
from config import get_settings


revision = "5df6a8811f86"
down_revision = "7ffa406cf785"
title = "Keep The Daily Wire on its refresh schedule"

# The system schedule VODLoft ships, and the schedule every episode had before, which The Daily Wire starts with.
_SYSTEM_DEFAULT = "1h,6h,24h,3d"
_DAILY_WIRE_DEFAULT = "15m,30m,1h,3h,6h,24h,3d"


async def migrate(context) -> None:
    configured = get_settings().new_episode_schedule.metadata_refresh_intervals
    session = get_session()
    try:
        site = session.get(Site, "dailywire")
        if (
            site is not None and configured != _SYSTEM_DEFAULT
            and site.refresh_mode == SiteRefreshMode.OWN.value and site.refresh_intervals == _DAILY_WIRE_DEFAULT
        ):
            site.refresh_intervals = configured
            session.commit()
        context.update_progress(1, 1, "Keeping The Daily Wire on its refresh schedule")
    finally:
        session.close()
