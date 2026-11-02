# Ensure base and referenced tables are imported before dependents
from .local_media_profile import (
    LocalMediaProfileBase,
    MovieLocalMediaProfile,
    CollectionLocalMediaProfile,
    VideoLocalMediaProfile,
)

# Existing code and third-party integrations historically constructed
# ``LocalMediaProfile`` directly for collections. Keep that import compatible while
# production code that needs all types queries ``LocalMediaProfileBase``.
LocalMediaProfile = CollectionLocalMediaProfile
from .Season import Season
from .Settings import Settings
from .SourceDomainPreference import SourceDomainPreference
from .QuickDownloadHistory import QuickDownloadHistory
from .user import User, UserAccess, UserSourceAccess
from .Collection import Collection
from .CollectionLocalAsset import CollectionLocalAsset
from .Metadata import Metadata
from .CustomIndexState import CustomIndexState
from .ExistingFileScan import ExistingFileScan

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
