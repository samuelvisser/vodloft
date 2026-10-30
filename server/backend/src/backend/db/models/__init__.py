# Ensure base and referenced tables are imported before dependents
from .local_media_profile import (
    LocalMediaProfileBase,
    MovieLocalMediaProfile,
    ShowLocalMediaProfile,
    VideoLocalMediaProfile,
)

# Existing code and third-party integrations historically constructed
# ``LocalMediaProfile`` directly for shows. Keep that import compatible while
# production code that needs all types queries ``LocalMediaProfileBase``.
LocalMediaProfile = ShowLocalMediaProfile
from .Season import Season
from .Settings import Settings
from .SourceDomainPreference import SourceDomainPreference
from .QuickDownloadHistory import QuickDownloadHistory
from .Show import Show
from .ShowLocalAsset import ShowLocalAsset
from .Metadata import Metadata
from .CustomIndexState import CustomIndexState

from .download_profile import DownloadProfile
from .media_download import MediaDownloadBase
from .media_download import MediaDownloadHistory
from .media_item import MediaItemBase
from .stream_profile import StreamProfileBase

from .media_download import EpisodeMediaDownload
from .media_download import MovieMediaDownload
from .media_download import MovieExtraMediaDownload
from .media_download import VideoMediaDownload
from .media_item import Episode
from .media_item import Movie
from .media_item import MovieExtraSource
from .media_item import MovieExtra
from .media_item import Video
from .stream_profile import RssStreamProfile
