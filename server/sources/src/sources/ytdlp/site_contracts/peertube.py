from .other_sites import OtherSites


class PeerTube(OtherSites):
    # Every PeerTube server has a domain of its own, so PeerTube has none.
    key, name = "peertube", "PeerTube"
    initials = "PT"
    # SepiaSearch, made by PeerTube's makers, finds channels, playlists and videos on many PeerTube servers at once.
    # Only those on servers yt-dlp knows as PeerTube's are shown, because VODLoft can only add those.
    searchable = True
    search_note = (
        "PeerTube is searched through SepiaSearch, which knows many PeerTube servers but not all of them. For a video "
        "or channel on another server, paste its link on Add media."
    )
