"""A read-only WebDAV share of a WebDAV stream profile's show, or of all of a user's shows.

Like an RSS feed, it answers without signing in: the secret token in the address is the key. It answers
OPTIONS, PROPFIND (depth 0 and 1), GET and HEAD, the last two with byte ranges, and refuses every change.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse

from backend.app import db_session
from backend.services.webdav import ShareFile, ShareFolder, artwork_file, find, shows_for_token
from .service import render_propfind

router = APIRouter(prefix="/webdav", tags=["WebDAV"])

_READ_METHODS = "OPTIONS, PROPFIND, GET, HEAD"
_WRITE_METHODS = ["PUT", "DELETE", "MKCOL", "COPY", "MOVE", "PROPPATCH", "LOCK", "UNLOCK", "POST", "PATCH"]
_DAV_HEADERS = {"DAV": "1", "Allow": _READ_METHODS, "MS-Author-Via": "DAV"}


def _parts(path: str) -> list[str]:
    return [part for part in path.split("/") if part]


def _node(token: str, parts: list[str]) -> ShareFolder | ShareFile:
    with db_session() as s:
        node = find(s, shows_for_token(s, token), parts)
    if node is None:
        raise HTTPException(status_code=404, detail="Not in this share")
    return node


def _options() -> Response:
    return Response(status_code=200, headers=_DAV_HEADERS)


def _propfind(token: str, path: str, request: Request) -> Response:
    parts = _parts(path)
    node = _node(token, parts)
    # A client that asks for the whole tree gets one level at a time, as most servers answer.
    depth = 0 if request.headers.get("depth", "1").strip() == "0" else 1
    body = render_propfind(f"/webdav/{token}", parts, node, depth=depth)
    return Response(content=body, status_code=207, media_type="application/xml; charset=utf-8", headers={"DAV": "1"})


def _get(token: str, path: str, request: Request) -> Response:
    node = _node(token, _parts(path))
    if isinstance(node, ShareFolder):
        # A browser that opens the share sees what WebDAV apps are for, instead of an empty page.
        names = "\n".join(f"{name}/" if isinstance(child, ShareFolder) else name for name, child in node.children.items())
        return Response(content=names + "\n", media_type="text/plain; charset=utf-8")
    if node.content is not None:
        content = b"" if request.method == "HEAD" else node.content
        return Response(content=content, media_type=node.content_type, headers={"Content-Length": str(len(node.content))})
    try:
        file_path = node.path if node.artwork is None else artwork_file(node.artwork, fetch=True)
    except (OSError, ValueError) as error:
        raise HTTPException(status_code=502, detail="Could not fetch this picture") from error
    if file_path is None or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Not in this share")
    return FileResponse(file_path, media_type=node.content_type, filename=node.name, content_disposition_type="inline")


@router.api_route("/{token}", methods=["OPTIONS", "PROPFIND", "GET", "HEAD"], include_in_schema=False)
@router.api_route("/{token}/{path:path}", methods=["OPTIONS", "PROPFIND", "GET", "HEAD"])
def webdav_read(token: str, request: Request, path: str = ""):
    if request.method == "OPTIONS":
        return _options()
    if request.method == "PROPFIND":
        return _propfind(token, path, request)
    return _get(token, path, request)


@router.api_route("/{token}/{path:path}", methods=_WRITE_METHODS, include_in_schema=False)
def webdav_refuse_changes(token: str, path: str = ""):
    return Response(status_code=405, headers={"Allow": _READ_METHODS})
