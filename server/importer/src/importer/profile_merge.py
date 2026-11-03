"""Fewer Local Media Profiles: merge the profiles of a plan that name files the same way.

An importer makes one profile per variant, such as each Pinchflat source with
its own template. Profiles with the same settings whose templates differ only
in a folder or part of a file name become one profile: each difference is a
custom collection field (``meta_collection_folder``), and each Collection stores
its own text in it. :func:`jinja_analysis.align_templates` proves, for every
member, that its own text in the field gives its own template again, so no
path changes. Anything it can't prove stays a profile of its own.
"""
from __future__ import annotations

import json
import re
from collections.abc import Collection as Some, Sequence
from dataclasses import dataclass, field, replace

from jinja2 import Environment
from jinja_analysis import Alignment, AlignmentFailure, align_templates

from .contract import CollectionPlan, ImportPlan, ImportWarning, ProfilePlan

MAX_FIELDS = 2
"""At most this many fields per merged profile; more is a different template wearing a shared name."""
_ENVIRONMENT = Environment()
_SUPPORT = {"exact": 0, "close": 1, "unsupported": 2}


def _field_variable(key: str) -> str:
    return f"meta_collection_{key}"


@dataclass
class _Family:
    members: list[ProfilePlan]
    alignment: Alignment
    signature: str
    collections: dict[str, list[CollectionPlan]] = field(default_factory=dict)


def _signature(profile: ProfilePlan) -> str:
    """Everything that must match for two profiles to be one, apart from the template.

    The collection type needs no place here: each template was converted for
    its own Collections' type, and the alignment compares the converted ones.
    """
    return json.dumps({
        "settings": profile.settings,
        "custom_indexes": [repr(index) for index in profile.custom_indexes],
    }, sort_keys=True, default=str)


def _align(profiles: Sequence[ProfilePlan], max_fields: int) -> Alignment | AlignmentFailure:
    return align_templates(
        [profile.output_template or "" for profile in profiles], _ENVIRONMENT,
        variable=_field_variable, typed=lambda source: f"{source} | as_typed",
        default_fallback="collection_title | as_typed", max_slots=max_fields,
    )


def _common_name(names: Sequence[str]) -> str:
    """What ``names`` share at the start: whole " - " parts, else whole words; the first name if that is short."""
    for separator in (" - ", " "):
        split = [name.split(separator) for name in names]
        shared: list[str] = []
        for parts in zip(*split):
            if len(set(parts)) != 1:
                break
            shared.append(parts[0])
        common = separator.join(shared).strip(" -")
        if len(common.split()) >= 3:
            return common
    return names[0]


def _family_name(family: _Family, base_names: dict[str, str]) -> str:
    bases = [member.name for member in family.members if member.base_name is None]
    if len(bases) == 1:
        return bases[0]
    if bases:
        return _common_name(bases)
    slots = family.alignment.slots
    if not slots:
        return family.members[0].name
    what = "folder" if slots[0].key.startswith("folder") else "name"
    base = family.members[0].base_name or ""
    return f"{base_names.get(base, base)} ({what} per collection)"


def _merged(family: _Family, base_names: dict[str, str]) -> ProfilePlan:
    founder = family.members[0]
    warnings: list[ImportWarning] = []
    for member in family.members:
        warnings.extend(warning for warning in member.warnings if warning not in warnings)
    support = max((member.support for member in family.members), key=lambda value: _SUPPORT[value])
    fields = tuple(slot.key for slot in family.alignment.slots)
    total = sum(len(collections) for collections in family.collections.values())
    proof = f"its template gives the same paths for all {total} collections"
    line = f"Kept together: {', '.join(member.name for member in family.members)}, as {proof}"
    if fields:
        line += f"; each collection keeps its own {', '.join(fields)} as a custom collection field"
    return replace(
        founder,
        external_id=f"{founder.external_id}:family",
        name=_family_name(family, base_names),
        output_template=family.alignment.template,
        warnings=tuple(warnings),
        report=(*founder.report, line),
        support=support,
        base_name=None,
        merged_from=tuple(member.name for member in family.members),
        fields=fields,
    )


def merge_profiles(plan: ImportPlan, *, selected: Some[str] | None = None, max_fields: int = MAX_FIELDS) -> ImportPlan:
    """The plan with every family of matching profiles merged into one.

    ``selected`` holds the external ids of the Collections being imported; a
    profile none of them uses is left as it is. Profiles are tried in order,
    the other program's own profiles before their variants, and each joins
    the first family it fits; one that fits none starts its own.
    """
    by_profile: dict[str, list[CollectionPlan]] = {}
    for collection in plan.collections:
        if collection.profile_external_id and (selected is None or collection.external_id in selected):
            by_profile.setdefault(collection.profile_external_id, []).append(collection)
    candidates = [profile for profile in plan.profiles
                  if profile.output_template is not None and by_profile.get(profile.external_id)]
    ordered = [profile for profile in candidates if profile.base_name is None] + \
              [profile for profile in candidates if profile.base_name is not None]

    families: list[_Family] = []
    reasons: dict[str, str] = {}
    for profile in ordered:
        collections = by_profile[profile.external_id]
        signature = _signature(profile)
        joined = False
        for family in families:
            if family.signature != signature:
                continue
            attempt = _align([*family.members, profile], max_fields)
            if isinstance(attempt, Alignment):
                family.members.append(profile)
                family.alignment = attempt
                family.collections[profile.external_id] = collections
                joined = True
                break
        if joined:
            continue
        if profile.base_name is not None:
            base = next((family for family in families
                         if any(member.name == profile.base_name for member in family.members)), None)
            if base is not None and base.signature != signature:
                reasons[profile.external_id] = "Its settings differ"
            elif base is not None:
                attempt = _align([*base.members, profile], max_fields)
                if isinstance(attempt, AlignmentFailure):
                    reasons[profile.external_id] = attempt.reason
        alone = _align([profile], max_fields)
        if isinstance(alone, Alignment):
            families.append(_Family([profile], alone, signature, {profile.external_id: collections}))

    merged: dict[str, ProfilePlan] = {}
    values: dict[str, dict[str, str]] = {}
    renamed: dict[str, str] = {}
    # A variant family is named after its base profile, as that profile is named after the merge.
    base_names: dict[str, str] = {}
    for family in sorted(families, key=lambda family: family.members[0].base_name is not None):
        name = _family_name(family, base_names) if len(family.members) > 1 else family.members[0].name
        for member in family.members:
            if member.base_name is None:
                base_names[member.name] = name
    for family in families:
        if len(family.members) < 2:
            continue
        plan_ = _merged(family, base_names)
        merged[family.members[0].external_id] = plan_
        for member, member_values in zip(family.members, family.alignment.values, strict=True):
            renamed[member.external_id] = plan_.external_id
            values[member.external_id] = member_values

    profiles: list[ProfilePlan] = []
    for profile in plan.profiles:
        if profile.external_id in merged:
            profiles.append(merged[profile.external_id])
        elif profile.external_id not in renamed:
            reason = reasons.get(profile.external_id)
            profiles.append(replace(profile, kept_separate=reason) if reason else profile)
    collections = []
    for collection in plan.collections:
        member = collection.profile_external_id or ""
        target = renamed.get(member)
        if target is None:
            collections.append(collection)
            continue
        settings = dict(collection.settings)
        if values[member]:
            settings["custom_metadata"] = {**dict(settings.get("custom_metadata") or {}), **values[member]}
        collections.append(replace(collection, profile_external_id=target, settings=settings))
    return replace(plan, profiles=tuple(profiles), collections=tuple(collections))
