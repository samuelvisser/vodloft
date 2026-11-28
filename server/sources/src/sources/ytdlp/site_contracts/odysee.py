from .other_sites import OtherSites


class Odysee(OtherSites):
    # Its links go to yt-dlp's lbry extractors, which name it.
    key, name = "lbry", "Odysee"
    initials = "OD"
    domains = ("odysee.com",)
    icon = "fab:odysee"
    # Odysee's own search finds channels and videos by name; their details take a second request.
    searchable = True
    search_note = "Odysee's search finds channels and videos, not playlists. To add a playlist, paste its link on Add media."
