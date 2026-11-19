import secrets
import uuid

def slugify(text: str | None) -> str:
    if not text:
        return ""
    s = str(text).strip().lower()
    out = []
    for ch in s:
        if ch.isalnum() or ch in "-_.":
            out.append(ch)
        elif ch.isspace() or ch in "/\\":
            out.append("-")
    slug = "".join(out)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")

def generate_uuid() -> str:
    """
    Generate a new random UUID (v4) as a string.
    """
    return str(uuid.uuid4())

def generate_stream_profile_token() -> str:
    """An unguessable secret used to serve a stream profile's feed without authentication."""
    return secrets.token_urlsafe(24)

def with_article(word: str) -> str:
    """A word with its indefinite article, such as "an album" or "a playlist"."""
    return f"{'an' if word[:1].lower() in 'aeiou' else 'a'} {word}"
