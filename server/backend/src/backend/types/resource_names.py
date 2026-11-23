"""VODLoft's own words for the kinds of things its tasks run for, such as a collection or a Download Profile."""
from sources import Names

RESOURCE_NAMES = {
    "collection": Names("collection", "collections"),
    "season": Names("season", "seasons"),
    "episode": Names("episode", "episodes"),
    "movie": Names("movie", "movies"),
    "creator": Names("creator", "creators"),
    "video": Names("video", "videos"),
    "download_profile": Names("Download Profile", "Download Profiles"),
    "local_media_profile": Names("Local Media Profile", "Local Media Profiles"),
    "media_download": Names("download", "downloads"),
    "system": Names("system", "system"),
}
"""What a task's resource type is called, by the type a task run stores."""

LINKS_COLLECTION_NAMES = Names("custom collection", "custom collections")
"""What a collection without a link of its own is, when its link seasons are on more than one Site."""
