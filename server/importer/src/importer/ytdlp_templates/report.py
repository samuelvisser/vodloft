"""What became of each part of a converted template, and of the template as a whole."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..contract import CustomIndexPlan, Support

_ORDER = {"exact": 0, "close": 1, "unsupported": 2}


@dataclass(frozen=True)
class PartReport:
    source: str
    """The part as written in the original template."""
    result: str
    """What it became in the VODLoft template; empty when it was left out."""
    support: Support
    reason: str | None = None
    """Why it is close or unsupported, and what the import did instead."""


@dataclass(frozen=True)
class ConversionReport:
    original: str
    """The template as the other program had it."""
    ytdlp_template: str
    """The template as yt-dlp saw it, after Pinchflat's expansion."""
    output_template: str | None
    """The VODLoft template, or None when no valid one could be made."""
    parts: tuple[PartReport, ...] = ()
    custom_indexes: tuple[CustomIndexPlan, ...] = ()
    errors: tuple[str, ...] = ()
    actions: tuple[PartReport, ...] = ()
    """What became of each metadata action of the option files."""

    @property
    def support(self) -> Support:
        """The weakest support of any part: the template is only as exact as its least exact part."""
        if self.output_template is None:
            return "unsupported"
        return max((part.support for part in (*self.parts, *self.actions)), key=_ORDER.__getitem__, default="exact")

    def lines(self) -> list[str]:
        """The report as text, one line per part that changed: renamed, nearly the same or not converted."""
        lines = [f"{self.original!r} becomes {self.output_template!r}" if self.output_template
                 else f"{self.original!r} could not be converted"]
        lines.extend(self.errors)
        for part in (*self.actions, *self.parts):
            if part.support == "exact" and part.source == part.result:
                continue
            result = f"{part.result!r}" if part.result else "nothing"
            how = {"exact": "exact", "close": "nearly the same"}.get(part.support, "not converted")
            line = f"{part.source!r} becomes {result} ({how}). {part.reason or ''}".rstrip()
            if line not in lines:
                lines.append(line)
        return lines


@dataclass
class ReportBuilder:
    parts: list[PartReport] = field(default_factory=list)

    def add(self, source: str, result: str, support: Support = "exact", reason: str | None = None) -> None:
        self.parts.append(PartReport(source, result, support, reason))
