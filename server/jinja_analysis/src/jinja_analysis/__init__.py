"""Reusable, side-effect-free Jinja analysis, printing and source-preserving edits.

The package only depends on jinja2. It knows nothing about VODLoft's variables
or database; callers pass in the environment and the values they care about.
"""
from .align import Alignment, AlignmentFailure, Slot, align_templates
from .custom_indexes import (
    CustomIndexReachabilityComparison,
    CustomIndexReachabilityStatus,
    CustomIndexUsage,
    CustomIndexUsageAnalysis,
    analyze_custom_index_usage,
    compare_custom_index_reachability,
)
from .expressions import expression_dependencies
from .filters import FILTERS, PURE_FILTERS, STRING_FILTERS, VOLATILE_FILTERS, FilterRule, filter_result
from .paths import OutputVariant, TemplateAnalysis, UnknownOutput, analyze_template
from .source import TemplateEdit, TemplateEdits, UnsafeEdit, expression_source

__all__ = [
    "Alignment",
    "AlignmentFailure",
    "Slot",
    "align_templates",
    "CustomIndexReachabilityComparison",
    "CustomIndexReachabilityStatus",
    "CustomIndexUsage",
    "CustomIndexUsageAnalysis",
    "analyze_custom_index_usage",
    "compare_custom_index_reachability",
    "expression_dependencies",
    "expression_source",
    "FILTERS",
    "FilterRule",
    "filter_result",
    "PURE_FILTERS",
    "STRING_FILTERS",
    "TemplateEdit",
    "TemplateEdits",
    "UnsafeEdit",
    "VOLATILE_FILTERS",
    "OutputVariant",
    "TemplateAnalysis",
    "UnknownOutput",
    "analyze_template",
]
