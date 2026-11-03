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
