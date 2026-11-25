"""Merging an import's profiles that differ only by a folder or name."""
from importer.contract import CollectionPlan, ImportPlan, ProfilePlan
from importer.profile_merge import merge_profiles

SETTINGS = {"preferred_format": "format_1080p", "subtitle_mode": "sidecar"}
BASE = "/downloads/V/{{ collection_title | as_typed }}/{{ title }}.ext"
LIST = "/downloads/V/{folder}/Season 01/{{{{ episode_uploader or 'NA' }}}} - {{{{ title }}}}.ext"


def _profile(external_id, name, template, base_name=None, **settings):
    return ProfilePlan(external_id, name, template, settings={**SETTINGS, **settings}, base_name=base_name)


def _collection(external_id, profile, kind="channel"):
    return CollectionPlan(external_id, f"https://example.com/{external_id}", external_id.title(), profile,
                          settings={"collection_type": kind})


def _plan():
    return ImportPlan(
        importer="test",
        profiles=(
            _profile("p:3", "Video to Plex - no shorts", BASE),
            _profile("p:4", "Video to Plex - no livestreams", BASE),
            _profile("p:3:s:9", "Video to Plex - no shorts (Fireside)", LIST.format(folder="Fireside Chat"), "Video to Plex - no shorts"),
            _profile("p:3:s:13", "Video to Plex - no shorts (War)", LIST.format(folder="Eighty Years War"), "Video to Plex - no shorts"),
            _profile("p:3:s:15", "Video to Plex - no shorts (Subs)", LIST.format(folder="Subbed"), "Video to Plex - no shorts",
                     subtitle_mode="embed"),
            _profile("p:3:s:16", "Video to Plex - no shorts (Spaced)", "/downloads/V/ Odd/{{ title }}.ext", "Video to Plex - no shorts"),
        ),
        collections=(
            _collection("a", "p:3"), _collection("b", "p:4"),
            _collection("fireside", "p:3:s:9", "playlist"), _collection("war", "p:3:s:13", "playlist"),
            _collection("subs", "p:3:s:15", "playlist"), _collection("odd", "p:3:s:16"),
        ),
    )


def test_profiles_with_the_same_settings_and_template_become_one_named_after_what_they_share():
    merged = merge_profiles(_plan())
    profiles = {profile.external_id: profile for profile in merged.profiles}
    assert profiles["p:3:family"].name == "Video to Plex"
    assert profiles["p:3:family"].merged_from == ("Video to Plex - no shorts", "Video to Plex - no livestreams")
    assert profiles["p:3:family"].output_template == BASE and profiles["p:3:family"].fields == ()
    assert {collection.external_id: collection.profile_external_id for collection in merged.collections}["b"] == "p:3:family"


def test_variants_that_differ_only_by_a_folder_share_a_profile_with_a_folder_field():
    merged = merge_profiles(_plan())
    profiles = {profile.external_id: profile for profile in merged.profiles}
    shared = profiles["p:3:s:9:family"]
    assert shared.name == "Video to Plex (folder per collection)"
    assert shared.fields == ("folder",)
    # Only profile names Pinchflat has: the variants count as the profile whose template they override.
    assert shared.merged_from == ("Video to Plex - no shorts",) and shared.template_overrides
    # The shared profile says why its collections are not on the profile they override.
    assert shared.kept_separate == "The paths have a different number of folders"
    assert shared.output_template == (
        "/downloads/V/{{ (meta_collection_folder | as_typed) if meta_collection_folder else (collection_title | as_typed) }}"
        "/Season 01/{{ episode_uploader or 'NA' }} - {{ title }}.ext"
    )
    values = {collection.external_id: collection.settings.get("custom_metadata") for collection in merged.collections}
    assert values["fireside"] == {"folder": "Fireside Chat"} and values["war"] == {"folder": "Eighty Years War"}


def test_other_settings_or_a_stray_space_keep_a_variant_apart_and_say_why():
    merged = merge_profiles(_plan())
    profiles = {profile.external_id: profile for profile in merged.profiles}
    assert profiles["p:3:s:15"].kept_separate == "Its settings differ"
    assert "space" in profiles["p:3:s:16"].kept_separate
    assert len(merged.profiles) == 4


def test_only_the_collections_being_imported_decide_the_families():
    merged = merge_profiles(_plan(), selected={"a", "fireside", "subs", "odd"})
    ids = {profile.external_id for profile in merged.profiles}
    assert {"p:3", "p:4", "p:3:s:9", "p:3:s:13"} <= ids
    assert not any(external_id.endswith(":family") for external_id in ids)


CHANNEL = "/downloads/A/{folder}/{{{{ date }}}} - {{{{ title }}}}.ext"


def _channel(external_id, profile, author):
    return CollectionPlan(external_id, f"https://example.com/{external_id}", f"{external_id.title()} title", profile,
                          settings={"collection_type": "channel", "author": author})


def test_a_collection_whose_folder_is_what_the_fallback_gives_it_keeps_no_text_of_its_own():
    plan = ImportPlan(
        importer="test",
        profiles=(
            _profile("p:1", "Audio", CHANNEL.format(folder="{{ collection_author or 'NA' }}")),
            _profile("p:1:s:2", "Audio (Same)", CHANNEL.format(folder="Same Channel"), "Audio"),
            _profile("p:1:s:3", "Audio (Other)", CHANNEL.format(folder="Own Folder"), "Audio"),
        ),
        collections=(
            _channel("plain", "p:1", "Plain Channel"),
            _channel("same", "p:1:s:2", "Same Channel"),
            _channel("other", "p:1:s:3", "Other Channel"),
        ),
    )
    merged = merge_profiles(plan)
    assert merged.profiles[0].output_template == (
        "/downloads/A/{{ (meta_collection_folder | as_typed) if meta_collection_folder else (collection_author or 'NA') }}"
        "/{{ date }} - {{ title }}.ext"
    )
    values = {collection.external_id: collection.settings.get("custom_metadata") for collection in merged.collections}
    assert values == {"plain": None, "same": None, "other": {"folder": "Own Folder"}}


def test_a_folder_that_is_the_collection_title_falls_back_to_the_title():
    plan = ImportPlan(
        importer="test",
        profiles=(
            _profile("p:1", "Audio", CHANNEL.format(folder="Plain title")),
            _profile("p:2", "Audio 2", CHANNEL.format(folder="Elsewhere")),
        ),
        collections=(_channel("plain", "p:1", "Plain Channel"), _channel("moved", "p:2", "Moved Channel")),
    )
    values = {collection.external_id: collection.settings.get("custom_metadata")
              for collection in merge_profiles(plan).collections}
    assert values == {"plain": None, "moved": {"folder": "Elsewhere"}}


def test_any_collection_value_of_the_template_counts_and_episode_values_never_do():
    plan = ImportPlan(
        importer="test",
        profiles=(
            _profile("p:1", "Music", CHANNEL.format(folder="{{ artist | upper }}")),
            _profile("p:1:s:2", "Music (Same)", CHANNEL.format(folder="SAME ARTIST"), "Music"),
            _profile("p:3", "Uploads", CHANNEL.format(folder="{{ episode_uploader }}")),
            _profile("p:3:s:4", "Uploads (Named)", CHANNEL.format(folder="Uploader"), "Uploads"),
        ),
        collections=(
            CollectionPlan("plain", "https://example.com/plain", "Plain", "p:1", artist="Plain Artist"),
            CollectionPlan("same", "https://example.com/same", "Same", "p:1:s:2", artist="Same Artist"),
            CollectionPlan("up", "https://example.com/up", "Up", "p:3"),
            CollectionPlan("named", "https://example.com/named", "Uploader", "p:3:s:4", settings={"author": "Uploader"}),
        ),
    )
    values = {collection.external_id: collection.settings.get("custom_metadata")
              for collection in merge_profiles(plan).collections}
    assert values == {"plain": None, "same": None, "up": None, "named": {"folder": "Uploader"}}
