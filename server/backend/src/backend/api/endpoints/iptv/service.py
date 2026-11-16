"""The M3U playlists, XMLTV guide and off-air stream IPTV apps read."""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring

from sqlalchemy.orm import Session

from backend.db.models import Collection, Episode
from backend.db.models.stream_profile import IptvStreamProfile
from backend.services.iptv import Programme, channel_group, channel_name, channel_programmes, media_name
from backend.services.stream_episodes import get_stream_items
from backend.services.thumbnails import is_own_thumbnail

# A still "Off air" screen with silent audio, for a channel that is off air. Made with:
#   ffmpeg -f lavfi -i color=c=0x111827:s=1280x720:r=25:d=6 -i ui/public/logo-wide-vodloft.png
#     -f lavfi -i anullsrc=channel_layout=stereo:sample_rate=48000 -filter_complex "[1:v]scale=360:-1[logo];
#     [0:v][logo]overlay=(W-w)/2:180,drawtext=text='Off air':fontcolor=white:fontsize=56:x=(w-text_w)/2:y=440,
#     drawtext=text='Nothing is on right now':fontcolor=0x9ca3af:fontsize=30:x=(w-text_w)/2:y=515,format=yuv420p[v]"
#     -map [v] -map 2:a -t 6 -c:v libx264 -tune stillimage -crf 30 -bf 0 -g 150 -c:a aac -b:a 32k -f mpegts off-air.ts
OFF_AIR_SEGMENT = Path(__file__).resolve().parents[3] / "assets" / "off-air.ts"
_OFF_AIR_SECONDS = 6
# How many plays of the off-air segment its live playlist lists at a time.
_OFF_AIR_WINDOW = 3


def _channel_id(profile: IptvStreamProfile) -> str:
    return f"vodloft-{profile.id}"


def _picture(*candidates: Optional[str]) -> Optional[str]:
    # A thumbnail VODLoft made needs a signed-in browser, which a TV app is not.
    return next((url for url in candidates if url and not is_own_thumbnail(url)), None)


def _logo(collection: Collection) -> Optional[str]:
    return _picture(collection.thumbnail_square_path, collection.thumbnail_landscape_path, collection.logo_image_path)


def _attribute(value: str) -> str:
    """A value inside an #EXTINF attribute, which ends at the next double quote."""
    return value.replace('"', "'").replace("\n", " ")


def _entry(duration: int, attributes: dict[str, Optional[str]], name: str, url: str) -> list[str]:
    listed = " ".join(f'{key}="{_attribute(value)}"' for key, value in attributes.items() if value)
    return [f"#EXTINF:{duration} {listed},{name.replace(chr(10), ' ')}", url]


def render_playlist(channels: list[IptvStreamProfile], *, base_url: str, guide_url: str) -> str:
    """The channels, each with the address apps play an older episode from by the time of its guide slot."""
    lines = [f'#EXTM3U url-tvg="{guide_url}" x-tvg-url="{guide_url}"']
    for profile in channels:
        name = channel_name(profile)
        channel_url = f"{base_url}/iptv/{profile.token}"
        lines += _entry(-1, {
            "tvg-id": _channel_id(profile),
            "tvg-name": name,
            "tvg-logo": _logo(profile.collection),
            "tvg-chno": str(profile.channel_number),
            "group-title": channel_group(profile),
            "catchup": "default",
            "catchup-days": str(profile.catch_up_days),
            "catchup-source": f"{channel_url}/catchup.m3u8?utc={{utc}}&lutc={{lutc}}",
        }, name, f"{channel_url}/channel.m3u8")
    return "\n".join(lines) + "\n"


def _episode_picture(episode: Episode) -> Optional[str]:
    return _picture(episode.thumbnail_landscape_path, episode.thumbnail_square_path, episode.thumbnail_portrait_path)


def render_episode_playlist(s: Session, channels: list[IptvStreamProfile], *, base_url: str) -> str:
    """Every episode of the channels as an entry of its own, newest first and grouped by channel, for apps
    without a guide."""
    lines = ["#EXTM3U"]
    for profile in channels:
        for episode, _download in get_stream_items(s, profile):
            lines += _entry(round(episode.duration) if episode.duration else -1, {
                "tvg-logo": _episode_picture(episode),
                "group-title": channel_name(profile),
            }, episode.title, (
                f"{base_url}/feeds/iptv/{profile.token}/episodes/{episode.slug}/{media_name(s, profile, episode)}"
            ))
    return "\n".join(lines) + "\n"


def render_off_air(now: datetime, *, segment_url: str, ended: bool) -> str:
    """A live HLS playlist that plays the off-air screen over and over, until ``ended``: then it ends, and the
    app opens the channel again to play what is on."""
    sequence = math.floor(now.timestamp() / _OFF_AIR_SECONDS)
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{_OFF_AIR_SECONDS}",
        f"#EXT-X-MEDIA-SEQUENCE:{sequence}",
        # Each play starts the segment's clock again, so each one is a discontinuity.
        f"#EXT-X-DISCONTINUITY-SEQUENCE:{sequence}",
    ]
    for _play in range(_OFF_AIR_WINDOW):
        lines += ["#EXT-X-DISCONTINUITY", f"#EXTINF:{_OFF_AIR_SECONDS}.0,", segment_url]
    if ended:
        lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def _xmltv_time(moment: datetime) -> str:
    return moment.strftime("%Y%m%d%H%M%S +0000")


def _sub_text(parent: Element, tag: str, text: Optional[str], **attributes: str) -> None:
    if text:
        SubElement(parent, tag, attributes).text = text


def _append_programme(tv: Element, profile: IptvStreamProfile, programme: Programme) -> None:
    episode = programme.episode
    element = SubElement(tv, "programme", {
        "start": _xmltv_time(programme.start),
        "stop": _xmltv_time(programme.stop),
        "channel": _channel_id(profile),
    })
    if episode is None:
        _sub_text(element, "title", "Off air", lang="en")
        return
    _sub_text(element, "title", episode.title, lang="en")
    _sub_text(element, "desc", episode.description, lang="en")
    aired = episode.published_date or episode.went_live_date
    if aired is not None:
        _sub_text(element, "date", aired.strftime("%Y%m%d"))
    picture = _episode_picture(episode)
    if picture:
        SubElement(element, "icon", {"src": picture})
    if (episode.episode_number or "").isdigit():
        _sub_text(element, "episode-num", f"Episode {episode.episode_number}", system="onscreen")
    if programme.repeat:
        SubElement(element, "previously-shown")
    if programme.live:
        SubElement(element, "live")
    if programme.upcoming:
        SubElement(element, "new")


def render_guide(s: Session, channels: list[IptvStreamProfile], now: datetime) -> bytes:
    tv = Element("tv", {"generator-info-name": "VODLoft"})
    for profile in channels:
        channel = SubElement(tv, "channel", {"id": _channel_id(profile)})
        _sub_text(channel, "display-name", channel_name(profile))
        _sub_text(channel, "display-name", str(profile.channel_number))
        logo = _logo(profile.collection)
        if logo:
            SubElement(channel, "icon", {"src": logo})
    for profile in channels:
        for programme in channel_programmes(s, profile, now):
            _append_programme(tv, profile, programme)
    return tostring(tv, encoding="UTF-8", xml_declaration=True)
