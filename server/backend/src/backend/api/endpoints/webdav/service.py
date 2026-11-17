"""The WebDAV answers a share gives: the properties of its folders and files, in a PROPFIND multistatus."""
from __future__ import annotations

from email.utils import format_datetime
from typing import Union
from urllib.parse import quote
from xml.etree.ElementTree import Element, SubElement, register_namespace, tostring

from backend.services.webdav import ShareFile, ShareFolder, artwork_file

_DAV = "DAV:"
register_namespace("D", _DAV)


def _tag(name: str) -> str:
    return f"{{{_DAV}}}{name}"


def href(base: str, parts: list[str], *, folder: bool) -> str:
    path = "/".join(quote(part) for part in parts)
    return f"{base}/{path}{'/' if folder and path else ''}" if path else f"{base}/"


def file_size(node: ShareFile) -> int | None:
    """The file's size, where it is known without fetching it: a picture not fetched yet has none."""
    if node.content is not None:
        return len(node.content)
    path = node.path if node.artwork is None else artwork_file(node.artwork, fetch=False)
    try:
        return path.stat().st_size if path is not None else None
    except OSError:
        return None


def _append_response(multistatus: Element, href_: str, node: Union[ShareFolder, ShareFile]) -> None:
    response = SubElement(multistatus, _tag("response"))
    SubElement(response, _tag("href")).text = href_
    propstat = SubElement(response, _tag("propstat"))
    prop = SubElement(propstat, _tag("prop"))
    SubElement(prop, _tag("displayname")).text = node.name
    SubElement(prop, _tag("getlastmodified")).text = format_datetime(node.modified, usegmt=True)
    SubElement(prop, _tag("creationdate")).text = node.modified.strftime("%Y-%m-%dT%H:%M:%SZ")
    resourcetype = SubElement(prop, _tag("resourcetype"))
    if isinstance(node, ShareFolder):
        SubElement(resourcetype, _tag("collection"))
    else:
        SubElement(prop, _tag("getcontenttype")).text = node.content_type
        size = file_size(node)
        if size is not None:
            SubElement(prop, _tag("getcontentlength")).text = str(size)
        SubElement(prop, _tag("getetag")).text = f'"{int(node.modified.timestamp())}-{size or 0}"'
    SubElement(propstat, _tag("status")).text = "HTTP/1.1 200 OK"


def render_propfind(base: str, parts: list[str], node: Union[ShareFolder, ShareFile], *, depth: int) -> bytes:
    """The properties of ``node``, and with ``depth`` 1 those of what a folder holds."""
    multistatus = Element(_tag("multistatus"))
    folder = isinstance(node, ShareFolder)
    _append_response(multistatus, href(base, parts, folder=folder), node)
    if folder and depth > 0:
        for name, child in sorted(node.children.items(), key=lambda item: item[0].lower()):
            _append_response(multistatus, href(base, [*parts, name], folder=isinstance(child, ShareFolder)), child)
    return tostring(multistatus, encoding="utf-8", xml_declaration=True)
