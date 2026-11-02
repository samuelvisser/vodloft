from backend.db.models import Collection
from sources.dailywire.api.dw_api.client import MiddlewareClient
from sources.dailywire.api.records import DwSeasonRecord


def get_latest_dw_season(client: MiddlewareClient, collection: Collection) -> DwSeasonRecord:
    """Get the latest DailyWire season for a collection

    Args:
        client (MiddlewareClient): The middleware client
        collection (Collection): The collection to get the latest season for

    Returns:
        DwSeasonRecord: The latest DailyWire season for the show
    """
    dw_show = client.get_show_page(collection.slug, membership_plan=collection.membership_level)
    return dw_show.latest_season