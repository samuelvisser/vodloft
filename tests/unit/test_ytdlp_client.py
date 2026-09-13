from ytdlp_client.client import YtDlpClient
import ytdlp_client.client as client_module


def test_collection_metadata_can_limit_playlist_enumeration(monkeypatch) -> None:
    captured: dict = {}

    class FakeYDL:
        def __init__(self, options):
            captured.update(options)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def extract_info(self, _url, download=False):
            assert download is False
            return {
                "extractor_key": "YoutubeTab",
                "id": "channel-id",
                "title": "Example Channel",
                "webpage_url": "https://example.invalid/channel",
                "entries": [],
            }

        def sanitize_info(self, info):
            return info

    monkeypatch.setattr(client_module, "YoutubeDL", FakeYDL)
    result = YtDlpClient().extract_collection("https://example.invalid/channel", max_entries=1)
    assert result.title == "Example Channel"
    assert captured["playlistend"] == 1
    assert captured["extract_flat"] == "in_playlist"
