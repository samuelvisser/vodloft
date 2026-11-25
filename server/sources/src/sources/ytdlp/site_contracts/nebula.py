from .other_sites import OtherSites


class Nebula(OtherSites):
    key, name = "nebula", "Nebula"
    initials = "NB"
    domains = ("nebula.tv",)
    # Nebula's public API finds its channels and videos by name, without signing in.
    searchable = True
