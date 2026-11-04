"""Check and test a regular expression the way Which episodes runs it."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from backend.api.models.regex import RegexCheckRead, RegexCheckRequest, RegexSampleField
from backend.db import get_session
from backend.db.models import Collection
from backend.db.models.media_item import Episode
from backend.security.access import Area, Level
from backend.security import deps
from backend.security.deps import requires
from backend.services.example_episodes import example_session
from backend.services.regex_check import check_pattern


router = APIRouter(prefix="/regex", tags=["Regex"])

# The newest episodes are enough to see what a pattern does.
_COLLECTION_SAMPLES = 2000


@router.post("/check", dependencies=[requires(Area.DOWNLOAD_PROFILES, Level.VIEW)], response_model=RegexCheckRead)
def check(body: RegexCheckRequest, request: Request):
    """Whether the pattern is valid, and what it matches in your texts and the Collection's episodes."""
    episodes: list[tuple[str, object]] = []
    if body.collection_id is not None:
        with get_session() as session:
            collection = session.get(Collection, body.collection_id)
            if collection is None or not deps.request_access(request).allows_source(collection.source_key):
                raise HTTPException(status_code=404, detail="Collection not found")
            column = Episode.title if body.field == RegexSampleField.TITLE else Episode.description
            episodes = [
                (text or "", published)
                for text, published in session.execute(
                    select(column, Episode.published_date)
                    .where(Episode.collection_id == collection.id)
                    .order_by(Episode.published_date.desc().nulls_last(), Episode.id.desc())
                    .limit(_COLLECTION_SAMPLES)
                )
            ]
    elif body.example_collection is not None:
        if not deps.request_access(request).allows_source(body.example_collection.source_key):
            raise HTTPException(status_code=404, detail="Source not found")
        try:
            with example_session(body.example_collection.example()) as (_session, _collection, examples):
                episodes = [
                    ((example.episode.title if body.field == RegexSampleField.TITLE else example.episode.description) or "",
                     example.episode.published_date)
                    for example in examples
                ]
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Could not look up the newest episodes: {exc}") from exc
    own = [text for text in body.samples if text.strip()]
    result = check_pattern(body.pattern, body.ignore_case, own + [text for text, _ in episodes])
    samples = [
        {**vars(sample), "own": index < len(own), "published_at": None if index < len(own) else episodes[index - len(own)][1]}
        for index, sample in enumerate(result.samples)
    ]
    collection_samples = samples[len(own):]
    return RegexCheckRead(
        pattern=result.pattern,
        ignore_case=result.ignore_case,
        valid=result.valid,
        error=result.error,
        error_position=result.error_position,
        samples=samples,
        collection_total=len(episodes),
        collection_matches=sum(sample["matched"] for sample in collection_samples),
    )
