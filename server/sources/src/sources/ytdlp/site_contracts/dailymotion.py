from .other_sites import OtherSites


class Dailymotion(OtherSites):
    key, name = "dailymotion", "Dailymotion"
    initials = "DM"
    domains = ("dailymotion.com", "dai.ly")
    icon = "fab:dailymotion"
    # Dailymotion's public API finds channels and videos by name, for free and without a key. It only searches
    # playlists for a signed-in user.
    searchable = True
    search_note = "Dailymotion's search finds channels and videos, not playlists. To add a playlist, paste its link on Add media."
