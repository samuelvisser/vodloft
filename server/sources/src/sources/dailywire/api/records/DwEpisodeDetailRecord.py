from typing import Optional

from sources.dailywire.api.records.DwEpisodeRecord import DwEpisodeRecord


class DwEpisodeDetailRecord(DwEpisodeRecord):
    audio_url: str
    video_url: str
    delivery_mode: str
    progress: float
    next_episode_url: Optional[str]
    playback_status: Optional[str] = None