"""Restrict built-in Source workers to public IP destinations at connect time.

This covers Python socket clients, including urllib and yt-dlp's native HTTP
handlers. Native networking in externally installed helpers needs container
egress policy as an additional deployment boundary.
"""

import ipaddress
import base64
import socket
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def install_public_network_guard() -> None:
    original_getaddrinfo = socket.getaddrinfo
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def public_addresses(host, port, *args, **kwargs):
        if not host:
            raise OSError("Source network destination is missing")
        results = original_getaddrinfo(host, port, *args, **kwargs)
        if not results or any(not ipaddress.ip_address(result[4][0]).is_global for result in results):
            raise OSError("Source network destination is private or local")
        return results

    def pinned_address(sock, address):
        if sock.family not in (socket.AF_INET, socket.AF_INET6):
            return address
        host, port = address[:2]
        results = public_addresses(host, port, sock.family, sock.type, sock.proto)
        return results[0][4]

    def connect(sock, address):
        return original_connect(sock, pinned_address(sock, address))

    def connect_ex(sock, address):
        return original_connect_ex(sock, pinned_address(sock, address))

    socket.getaddrinfo = public_addresses
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex


def fetch_stream(url: str, headers: dict[str, str] | None = None,
                 byte_range: str | None = None) -> dict:
    """Bounded private worker fetch for a lease's media or HLS child URL."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid upstream stream URL")
    safe_headers = {key: value for key, value in (headers or {}).items()
        if key.lower() in {"user-agent", "referer", "origin", "cookie", "authorization"}
        and isinstance(value, str) and len(value) <= 8192}
    if byte_range is not None:
        if not isinstance(byte_range, str) or len(byte_range) > 60 or not byte_range.startswith("bytes="):
            raise ValueError("Invalid upstream byte range")
        safe_headers["Range"] = byte_range
    with urlopen(Request(url, headers=safe_headers), timeout=25) as response:
        # A whole HLS segment must fit in one response; the gateway imposes a
        # separate 32 MiB limit on the encoded worker message.
        limit = 16 * 1024 * 1024
        body = response.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Upstream response exceeds the streaming chunk limit")
        return {"data": base64.b64encode(body).decode("ascii"),
            "content_type": response.headers.get("Content-Type", "application/octet-stream"),
            "content_range": response.headers.get("Content-Range"),
            "content_length": response.headers.get("Content-Length"),
            "status": response.status, "url": response.url}
