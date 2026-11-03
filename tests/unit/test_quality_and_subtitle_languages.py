"""Quality goals and subtitle languages on Local Media Profiles."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from downloader.models import SubtitleRendition
from downloader.plan import YtdlpSubtitles


TEMPLATE = "/downloads/{{ collection }}/{{ episode }}.ext"


def _create(**values):
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPICreate

    return CollectionLocalMediaProfileAPICreate.model_validate({
        "name": "Shows", "type": "collection", "outputTemplate": TEMPLATE, "preferredFormat": "format_1080p", **values,
    })


def test_a_goal_stands_for_its_codecs_container_and_audio_codec():
    body = _create(qualityGoal="quality", container="mp4", audioCodec="aac",
                   videoCodecs=[{"codec": "h264", "allowed": True}, {"codec": "av1", "allowed": False},
                                {"codec": "vp9", "allowed": False}, {"codec": "h265", "allowed": False}])
    assert [choice.codec for choice in body.video_codecs if choice.allowed] == ["av1", "vp9", "h264"]
    assert (body.container, body.audio_codec) == ("mkv", "opus")

    own = _create(qualityGoal="custom", container="mkv",
                  videoCodecs=[{"codec": "av1", "allowed": True}, {"codec": "h264", "allowed": True},
                               {"codec": "vp9", "allowed": False}, {"codec": "h265", "allowed": False}])
    assert [choice.codec for choice in own.video_codecs] == ["av1", "h264", "vp9", "h265"]
    assert own.container == "mkv"


@pytest.mark.parametrize("values", [
    {"videoCodecs": [{"codec": "h264", "allowed": False}, {"codec": "av1", "allowed": False},
                     {"codec": "vp9", "allowed": False}, {"codec": "h265", "allowed": False}], "qualityGoal": "custom"},
    {"videoCodecs": [{"codec": "h264", "allowed": True}], "qualityGoal": "custom"},
    {"subtitleLanguages": ["en", "en"]},
    {"subtitleLanguages": ["English"]},
    {"subtitleLanguages": [], "subtitleLanguageMode": "listed"},
    {"audioLanguage": "nl; rm"},
])
def test_invalid_quality_and_language_choices_are_refused(values):
    with pytest.raises(ValidationError):
        _create(**values)


def test_an_update_that_leaves_out_a_choice_keeps_it():
    from backend.api.models.collection_local_media_profile import CollectionLocalMediaProfileAPIUpdate

    body = CollectionLocalMediaProfileAPIUpdate.model_validate({
        "id": 1, "slug": "shows", "name": "Shows", "type": "collection", "outputTemplate": TEMPLATE,
        "preferredFormat": "format_1080p", "container": "mkv",
    })
    kept = body.fields_kept_on_update()
    assert "container" not in kept
    assert {"quality_goal", "video_codecs", "subtitle_languages", "audio_language", "subtitle_mode"} <= kept


def test_a_stream_keeps_only_the_subtitle_tracks_on_the_list_in_its_order():
    from backend.services.download_quality import chosen_subtitle_tracks

    tracks = [
        SubtitleRendition("https://a/en", "en", "English"),
        SubtitleRendition("https://a/en-f", "en", "English", forced=True),
        SubtitleRendition("https://a/es", "es", "Spanish"),
        SubtitleRendition("https://a/nl", "nl-NL", "Dutch"),
    ]
    assert [track.url for track in chosen_subtitle_tracks(YtdlpSubtitles(languages=("nl", "en")), tracks)] == [
        "https://a/nl", "https://a/en", "https://a/en-f",
    ]
    assert [track.url for track in chosen_subtitle_tracks(YtdlpSubtitles(languages=("fr", "es", "en"), first_only=True), tracks)] == ["https://a/es"]
    assert chosen_subtitle_tracks(YtdlpSubtitles(), tracks) == tracks


def test_the_first_embedded_subtitle_is_the_default_track_and_auto_generated_ones_are_named(tmp_path, monkeypatch):
    from downloader import ffmpeg

    commands = []

    class Done:
        returncode = 0
        stdout = ""

    def run(command, **_kwargs):
        commands.append(command)
        open(command[-1], "wb").close()
        return Done()

    monkeypatch.setattr(ffmpeg, "ffmpeg_available", lambda _path: True)
    monkeypatch.setattr(ffmpeg.subprocess, "run", run)
    media = tmp_path / "a.mkv"
    media.write_bytes(b"x")
    ffmpeg.embed_media(
        str(media), subtitles=(("nl", "nl.srt", False, None), ("nl", "nl.auto.srt", False, "Auto-generated")),
        first_subtitle_default=True,
    )
    command = commands[0]
    assert command[command.index("-disposition:s:0") + 1] == "default"
    assert command[command.index("-disposition:s:1") + 1] == "0"
    assert "title=Auto-generated" in command
