import re
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



def name_in_text(name: str) -> str:
    """A name as it reads inside a sentence: in quotes when it starts with "for", such as "for KING & COUNTRY", which
    would otherwise read as part of the sentence; otherwise as it is."""
    return f'"{name}"' if re.match(r"for\s", name, re.IGNORECASE) else name


def year_range(first: int | None, last: int | None) -> str:
    """The years something spans, short enough for one line on a card: 2025 for one year, 2016–26 within one century,
    and 1998–2026 across two."""
    if first is None or last is None:
        return ""
    if first == last:
        return str(first)
    if first // 100 == last // 100:
        return f"{first}–{last % 100:02d}"
    return f"{first}–{last}"
