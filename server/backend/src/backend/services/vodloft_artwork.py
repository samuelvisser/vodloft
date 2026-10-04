"""Source-owned image retrieval with generic role selection and a bounded local cache."""
import base64
import hashlib
import io
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy import select
from source_contracts import ArtworkCandidate
from backend.db import get_session
from backend.db.models.vodloft import MediaItem, SourceReference
from backend.source_manager.gateway import SourceGateway, validate_public_url
from backend.source_manager.runtime import runtime_root


def artwork(item_id: int, shape: str = 'landscape') -> Path:
    with get_session() as session:
        item = session.get(MediaItem, item_id)
        if not item:
            raise ValueError('Media item is unavailable')
        candidates = [ArtworkCandidate.model_validate(value) for value in (item.normalized_metadata or {}).get('artwork', [])]
        if item.artwork_url and not any(value.url == item.artwork_url for value in candidates):
            candidates.append(ArtworkCandidate(url=item.artwork_url))
        references = session.scalars(select(SourceReference).where(SourceReference.item_id == item_id)).all()
        source_ids = list(dict.fromkeys(reference.source_id for reference in references))
    ratios = {'square': 1.0, 'portrait': 2 / 3, 'landscape': 16 / 9}
    ratio = ratios[shape]
    def rank(candidate):
        role = candidate.role
        preferred = {'square': {'square', 'cover'}, 'portrait': {'portrait', 'poster'}, 'landscape': {'landscape', 'thumbnail', 'backdrop'}}[shape]
        distance = abs(candidate.width / candidate.height - ratio) if candidate.width and candidate.height else 10
        return (0 if role in preferred else 1, distance, -(candidate.width or 0))
    root = runtime_root().parent / 'artwork-cache'
    root.mkdir(parents=True, exist_ok=True)
    for candidate in sorted(candidates, key=rank):
        key = hashlib.sha256(candidate.url.encode()).hexdigest()
        destination = root / f'{key}.jpg'
        if destination.is_file():
            return destination
        for source_id in source_ids:
            temporary = None
            try:
                validate_public_url(candidate.url)
                result = SourceGateway().call(source_id, 'stream_fetch', timeout=35, url=candidate.url, headers={})
                body = base64.b64decode(result['data'], validate=True)
                if len(body) > 4 * 1024 * 1024:
                    raise ValueError('Artwork exceeds the supported size')
                with Image.open(io.BytesIO(body)) as image:
                    if image.format not in {'JPEG', 'PNG', 'WEBP'} or image.width * image.height > 20000000:
                        raise ValueError('Unsupported artwork')
                    rendered = ImageOps.exif_transpose(image).convert('RGB')
                    rendered.thumbnail((1600, 1600))
                    with tempfile.NamedTemporaryFile(dir=root, prefix='.artwork-', delete=False) as output:
                        temporary = Path(output.name)
                        rendered.save(output, 'JPEG', quality=88)
                os.replace(temporary, destination)
                return destination
            except Exception:
                # A stale or protected image must not break its media item.
                continue
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
    raise ValueError('No usable artwork is available')
