from __future__ import annotations

from datetime import datetime, timezone

from config import get_settings
from sqlalchemy.orm import Session
from ytdlp_client import DownloadOptions, YtDlpClient

from backend.db.models import DownloadProfile, Video


def download_video(
    session: Session,
    client: YtDlpClient,
    video_id: int,
    profile_id: int,
    progress_hook=None,
) -> dict[str, str | None]:
    video = session.get(Video, video_id)
    profile = session.get(DownloadProfile, profile_id)
    if video is None:
        raise LookupError("Video not found")
    if profile is None:
        raise LookupError("Download profile not found")

    local = profile.local_media_profile
    template = local.output_template
    settings = get_settings()
    if template.startswith("/downloads/") and settings.download_root != "/downloads":
        template = settings.download_root.rstrip("/") + template[len("/downloads"):]

    result = client.download(
        video.source_url,
        DownloadOptions(
            output_template=template,
            format_selector=profile.format_selector,
            merge_output_format=profile.merge_output_format,
            audio_format=profile.audio_format,
            write_subtitles=profile.write_subtitles,
            embed_metadata=profile.embed_metadata,
            embed_thumbnail=profile.embed_thumbnail,
        ),
        progress_hook=progress_hook,
    )
    video.downloaded_path = result.filepath
    video.downloaded_format = result.format_id or result.ext
    video.downloaded_at = datetime.now(timezone.utc)
    session.commit()
    return {"path": result.filepath, "format": video.downloaded_format}
