"""Your own yt-dlp options that VODLoft now refuses are turned into comments.

VODLoft now refuses options that break a download (such as --test or --no-warnings) and options it has a setting
of its own for (such as --limit-rate or --remove-chapters). A line with one of them would make every download of
its collection fail, so the line becomes a comment: it stays visible in the options, and does nothing.

Revision ID: ee7b43f4d6a1
Revises: ac034d79c796
Create Date: 2026-11-21
"""
from __future__ import annotations

import shlex

import sqlalchemy as sa
from alembic import op
from yt_dlp.options import create_parser


revision = "ee7b43f4d6a1"
down_revision = "ac034d79c796"
branch_labels = None
depends_on = None

# yt-dlp's names of the options VODLoft started refusing in this change.
_REFUSED = frozenset({
    "test", "no_warnings", "hls_split_discontinuity", "ignore_no_formats_error", "download_ranges", "print_json",
    "matchtitle", "rejecttitle", "break_on_reject", "max_downloads", "remove_chapters", "updatetime", "ratelimit",
})
_NOTE = "# Turned off by VODLoft, which no longer takes this option here: "


def _refused(parser, line: str) -> bool:
    try:
        tokens = shlex.split(line, comments=True)
    except ValueError:
        return False
    for token in tokens:
        if token.startswith("--"):
            try:
                option = parser._long_opt[parser._match_long_opt(token.partition("=")[0])]
            except Exception:
                continue
        elif token.startswith("-") and len(token) > 1:
            option = parser._short_opt.get(token[:2])
            if option is None:
                continue
        else:
            continue
        if option.dest in _REFUSED:
            return True
    return False


def _turned_off(parser, text: str) -> str:
    return "\n".join(
        f"{_NOTE}{line}" if not line.lstrip().startswith("#") and _refused(parser, line) else line
        for line in text.split("\n")
    )


def upgrade() -> None:
    bind = op.get_bind()
    parser = create_parser()
    for table in ("settings", "collections"):
        rows = bind.execute(sa.text(f"SELECT id, ytdlp_options FROM {table} WHERE ytdlp_options <> ''")).all()
        for row_id, text in rows:
            changed = _turned_off(parser, text or "")
            if changed != text:
                bind.execute(sa.text(f"UPDATE {table} SET ytdlp_options = :text WHERE id = :id"),
                             {"text": changed, "id": row_id})


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("settings", "collections"):
        rows = bind.execute(sa.text(f"SELECT id, ytdlp_options FROM {table} WHERE ytdlp_options LIKE :note"),
                            {"note": f"%{_NOTE}%"}).all()
        for row_id, text in rows:
            restored = "\n".join(line.removeprefix(_NOTE) for line in text.split("\n"))
            bind.execute(sa.text(f"UPDATE {table} SET ytdlp_options = :text WHERE id = :id"),
                         {"text": restored, "id": row_id})
