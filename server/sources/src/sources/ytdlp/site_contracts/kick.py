from .other_sites import OtherSites


class Kick(OtherSites):
    key, name = "kick", "Kick"
    initials = "KI"
    domains = ("kick.com",)
    # Kick's own search finds channels by name, and says which are live.
    searchable = True
    search_note = "Kick's search only finds channels. To add a single video or clip, paste its link on Add media."
