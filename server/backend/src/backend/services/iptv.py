"""What an IPTV stream profile's channel shows: its programme guide, what it plays now and what it played before.

A channel's episodes are the ones its stream profile offers (``stream_episodes``). Each sits in the guide
from the moment it went live, or else was published, for its length rounded up to whole slots. Between
episodes the channel loops the newest one it has aired, is off air, or is not listed at all, as its
profile chooses. A scheduled episode shows as upcoming. The guide reaches back as far as apps may play
an episode again from it (catch-up).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from backend.db.datetime_types import utc_datetime
from backend.db.models import Episode, Settings
from backend.db.models.stream_profile import IptvStreamProfile
from backend.db.models.user import User
from backend.services import users
from backend.services.errors import NotFoundError
from backend.services.sites import collection_site
from backend.services.stream_episodes import get_local_download_for_episode, get_stream_items, owner_may_stream
from backend.types.episode_types import EpisodePublishStatus
from backend.types.stream_profile_types import IptvBetweenLiveEpisodes
from backend.utils.episode import episode_identifier_type_predicate
from sources import StreamMethod

SLOT = timedelta(minutes=5)
# A loop of a short episode shows in the guide as blocks of at least this long, of whole plays.
_MIN_REPEAT = timedelta(minutes=30)
GUIDE_AHEAD = timedelta(days=1)
# How long the guide gives a live episode beyond now, while it has no length yet.
_LIVE_AHEAD = timedelta(minutes=30)


@dataclass(frozen=True)
class Programme:
    """One slot of a channel's guide. A slot without an episode is off air."""

    episode: Optional[Episode]
    start: datetime
    stop: datetime
    live: bool = False
    repeat: bool = False
    upcoming: bool = False


def channels_for_token(s: Session, token: str) -> list[IptvStreamProfile]:
    """The enabled channels a playlist or guide address opens, in channel number order.

    The token is a channel's own, a user's stream token (their own channels) or, in an install without
    user accounts, the install's stream token (every channel).
    """
    query = (
        s.query(IptvStreamProfile)
        .options(joinedload(IptvStreamProfile.collection))
        .filter(IptvStreamProfile.enable_profile.is_(True))
        .order_by(IptvStreamProfile.channel_number, IptvStreamProfile.id)
    )
    own = query.filter(IptvStreamProfile.token == token).one_or_none()
    if own is not None:
        if not owner_may_stream(s, own):
            raise NotFoundError("Playlist")
        return [own]

    user = s.scalars(select(User).where(User.stream_token == token)).one_or_none()
    if user is not None:
        if not user.is_enabled:
            raise NotFoundError("Playlist")
        return query.filter(IptvStreamProfile.owner_user_id == user.id).all()

    install = s.scalars(select(Settings).where(Settings.stream_token == token)).first()
    if install is not None and not install.user_accounts_enabled:
        return [channel for channel in query.all() if owner_may_stream(s, channel)]
    raise NotFoundError("Playlist")


def stream_token_holder(s: Session, user_id: Optional[int]) -> User | Settings:
    """Where the stream token of whoever is signed in is kept: their account, or the install without accounts."""
    if user_id is not None:
        user = s.get(User, user_id)
        if user is None:
            raise NotFoundError("User")
        return user
    return users.settings_row(s)


def channel_name(profile: IptvStreamProfile) -> str:
    return profile.overwrite_collection_title or profile.collection.title


def channel_group(profile: IptvStreamProfile) -> str:
    return profile.channel_group or collection_site(profile.collection).name


def next_channel_number(s: Session, owner_user_id: Optional[int]) -> int:
    """The number after the highest one the owner's channels use."""
    numbers = s.scalars(
        select(IptvStreamProfile.channel_number)
        .where(IptvStreamProfile.owner_user_id.is_not_distinct_from(owner_user_id))
    ).all()
    return max(numbers, default=0) + 1


def _slot_length(episode: Episode) -> timedelta:
    """The episode's length, rounded up to whole slots."""
    slots = max(1, math.ceil((episode.duration or 0) / SLOT.total_seconds()))
    return slots * SLOT


def _aired_at(episode: Episode) -> Optional[datetime]:
    moment = episode.went_live_date or episode.published_date
    return utc_datetime(moment) if moment is not None else None


def _round_up(moment: datetime) -> datetime:
    seconds = SLOT.total_seconds()
    return datetime.fromtimestamp(math.ceil(moment.timestamp() / seconds) * seconds, tz=moment.tzinfo)


def _upcoming_episodes(s: Session, profile: IptvStreamProfile, now: datetime) -> list[tuple[datetime, Episode]]:
    allowed_types = set(profile.ep_id_type_list or [])
    if not allowed_types:
        return []
    episodes = s.scalars(
        select(Episode).where(
            Episode.collection_id == profile.collection_id,
            Episode.publish_status == EpisodePublishStatus.SCHEDULED.value,
            Episode.scheduled_date.is_not(None),
            episode_identifier_type_predicate(Episode.episode_identifier, allowed_types),
        )
    ).all()
    upcoming = [(utc_datetime(episode.scheduled_date), episode) for episode in episodes]
    return sorted(
        ((start, episode) for start, episode in upcoming if now - SLOT < start < now + GUIDE_AHEAD),
        key=lambda item: item[0],
    )


def _repeats(episode: Episode, start: datetime, until: datetime, *, after: datetime) -> list[Programme]:
    """The episode on a loop from ``start`` until ``until``, leaving out the slots that end before ``after``."""
    plays = _slot_length(episode)
    length = plays * math.ceil(_MIN_REPEAT / plays)
    if start < after:
        start += length * max(0, math.floor((after - start) / length))
    repeats: list[Programme] = []
    while start < until:
        stop = min(start + length, until)
        repeats.append(Programme(episode, start, stop, repeat=True))
        start = stop
    return repeats


def _between(
    profile: IptvStreamProfile, previous: Optional[Episode], start: datetime, until: datetime, *, after: datetime,
) -> list[Programme]:
    """What fills the guide from ``start`` until ``until``, after ``previous`` aired or before any episode did."""
    if start >= until:
        return []
    between = IptvBetweenLiveEpisodes(profile.between_live_episodes)
    if between is IptvBetweenLiveEpisodes.OFF_AIR:
        return [Programme(None, max(start, after), until)] if until > after else []
    if between is IptvBetweenLiveEpisodes.NEWEST_EPISODE and previous is not None:
        return _repeats(previous, start, until, after=after)
    return []


def channel_programmes(s: Session, profile: IptvStreamProfile, now: datetime) -> list[Programme]:
    """The channel's guide from the start of its catch-up window until a day ahead, in time order and without
    overlaps."""
    window_start = _round_up(now - timedelta(days=profile.catch_up_days))
    window_end = _round_up(now + GUIDE_AHEAD)
    aired = sorted(
        (
            (start, episode)
            for episode, _download in get_stream_items(s, profile)
            if (start := _aired_at(episode)) is not None
        ),
        key=lambda item: item[0],
    )
    upcoming = _upcoming_episodes(s, profile, now)
    loop_until = upcoming[0][0] if upcoming else window_end

    programmes = _between(profile, None, window_start, aired[0][0] if aired else loop_until, after=window_start)
    for index, (start, episode) in enumerate(aired):
        live = episode.publish_status == EpisodePublishStatus.LIVE.value
        next_start = aired[index + 1][0] if index + 1 < len(aired) else loop_until
        stop = start + _slot_length(episode)
        if live:
            stop = max(stop, _round_up(now) + _LIVE_AHEAD)
        stop = min(stop, next_start)
        if stop <= start or next_start <= window_start:
            continue
        programmes.append(Programme(episode, start, stop, live=live))
        if not live:
            programmes.extend(_between(profile, episode, stop, next_start, after=window_start))

    for index, (start, episode) in enumerate(upcoming):
        next_start = upcoming[index + 1][0] if index + 1 < len(upcoming) else window_end
        stop = min(start + _slot_length(episode), next_start)
        if programmes and programmes[-1].stop > start:
            # A live episode that runs on; the guide shows the scheduled one after it.
            start = programmes[-1].stop
        if stop > start:
            programmes.append(Programme(episode, start, stop, upcoming=True))

    return [programme for programme in programmes if programme.stop > window_start and programme.start < window_end]


def playing_now(s: Session, profile: IptvStreamProfile, now: datetime) -> Optional[Programme]:
    """What the channel plays now, or None while it is not on at all.

    That is the guide's current slot. While that is an episode that has not started yet, a looping channel
    plays the newest episode it aired and another is off air. A channel that is only on while live plays
    nothing else.
    """
    programmes = [programme for programme in channel_programmes(s, profile, now) if not programme.upcoming]
    current = next((programme for programme in programmes if programme.start <= now < programme.stop), None)
    between = IptvBetweenLiveEpisodes(profile.between_live_episodes)
    if between is IptvBetweenLiveEpisodes.HIDE_CHANNEL:
        return current if current is not None and current.live else None
    if current is not None:
        return current
    if between is IptvBetweenLiveEpisodes.OFF_AIR:
        return Programme(None, now, now)
    started = [programme for programme in programmes if programme.start <= now]
    return started[-1] if started else None


def listed_channels(s: Session, channels: list[IptvStreamProfile], now: datetime) -> list[IptvStreamProfile]:
    """The channels a playlist and guide list now: all but those only on while live, while they are not."""
    return [
        channel for channel in channels
        if channel.between_live_episodes != IptvBetweenLiveEpisodes.HIDE_CHANNEL.value
        or playing_now(s, channel, now) is not None
    ]


def catch_up_programme(s: Session, profile: IptvStreamProfile, moment: datetime, now: datetime) -> Optional[Programme]:
    """The episode the guide has on at ``moment``, for an app that plays it again; None outside the guide's
    catch-up window, while the channel was off air or for a slot that has not started yet.

    An app asks by the start of a guide slot, sometimes a little early, so a slot that starts shortly after
    ``moment`` counts too.
    """
    if moment > now:
        return None
    programmes = [
        programme for programme in channel_programmes(s, profile, now)
        if programme.episode is not None and not programme.upcoming
    ]
    return next(
        (programme for programme in programmes if programme.start <= moment < programme.stop),
        next((programme for programme in programmes if moment < programme.start <= moment + SLOT), None),
    )


def media_name(s: Session, profile: IptvStreamProfile, episode: Episode) -> str:
    """Which of the episode's media addresses an IPTV app plays: HLS where it can, as IPTV apps expect, and
    otherwise a downloaded MP4."""
    if "audio" in profile.media_kinds:
        return "audio.m4a"
    if (
        episode.publish_status == EpisodePublishStatus.LIVE.value
        or get_local_download_for_episode(s, profile, episode, kind="hls") is not None
    ):
        return "video.m3u8"
    if get_local_download_for_episode(s, profile, episode, kind="mp4") is not None:
        return "video.mp4"
    return "video.m3u8" if StreamMethod.HLS in collection_site(profile.collection).stream_methods else "video.mp4"
