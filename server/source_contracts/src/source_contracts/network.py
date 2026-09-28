"""Restrict built-in Source workers to public IP destinations at connect time.

This covers Python socket clients, including urllib and yt-dlp's native HTTP
handlers. Native networking in externally installed helpers needs container
egress policy as an additional deployment boundary.
"""

import ipaddress
import socket


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
