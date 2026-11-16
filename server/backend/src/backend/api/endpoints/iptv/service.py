"""The M3U playlist and XMLTV guide IPTV apps read."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from xml.etree.ElementTree import Element, SubElement, tostring

from sqlalchemy.orm import Session

from backend.db.models import Collection
from backend.db.models.stream_profile import IptvStreamProfile
from backend.services.iptv import Programme, channel_group, channel_name, channel_programmes
from backend.services.thumbnails import is_own_thumbnail


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


def render_playlist(channels: list[IptvStreamProfile], *, base_url: str, guide_url: str) -> str:
    lines = [f'#EXTM3U url-tvg="{guide_url}" x-tvg-url="{guide_url}"']
    for profile in channels:
        name = channel_name(profile)
        attributes = {
            "tvg-id": _channel_id(profile),
            "tvg-name": name,
            "tvg-logo": _logo(profile.collection),
            "tvg-chno": str(profile.channel_number),
            "group-title": channel_group(profile),
        }
        listed = " ".join(f'{key}="{_attribute(value)}"' for key, value in attributes.items() if value)
        lines.append(f"#EXTINF:-1 {listed},{name.replace(chr(10), ' ')}")
        lines.append(f"{base_url}/iptv/{profile.token}/channel.m3u8")
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
    _sub_text(element, "title", episode.title, lang="en")
    _sub_text(element, "desc", episode.description, lang="en")
    aired = episode.published_date or episode.went_live_date
    if aired is not None:
        _sub_text(element, "date", aired.strftime("%Y%m%d"))
    picture = _picture(episode.thumbnail_landscape_path, episode.thumbnail_square_path, episode.thumbnail_portrait_path)
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
