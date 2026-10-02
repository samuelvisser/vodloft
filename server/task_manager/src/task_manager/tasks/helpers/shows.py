from backend.db.models import Show
from backend.source_manager.dailywire_legacy import MiddlewareClient
from dailywire_api.records import DwSeasonRecord


def get_latest_dw_season(client: MiddlewareClient, show: Show) -> DwSeasonRecord:
    """Get the latest DailyWire season for a show

    Args:
        client (MiddlewareClient): The middleware client
        show (Show): The show to get the latest season for

    Returns:
        DwSeasonRecord: The latest DailyWire season for the show
    """
    dwShow = client.get_show_page(show.slug, membership_plan=show.membership_level)
    return dwShow.latest_season