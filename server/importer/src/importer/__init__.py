"""Importers read another media manager's data into a neutral ImportPlan.

Like Sources, the package never imports the application: it knows nothing of
VODLoft's database or settings. The backend applies the plans it describes.
"""
from .contract import (
    CollectionPlan,
    CustomIndexPlan,
    FilePlan,
    ImportLocation,
    ImportPlan,
    ImportWarning,
    Importer,
    ProfilePlan,
    SettingPlan,
)
from .registry import all_importers, get_importer, register

__all__ = [
    "CollectionPlan",
    "CustomIndexPlan",
    "FilePlan",
    "ImportLocation",
    "ImportPlan",
    "ImportWarning",
    "Importer",
    "ProfilePlan",
    "SettingPlan",
    "all_importers",
    "get_importer",
    "register",
]
