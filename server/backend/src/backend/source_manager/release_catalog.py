"""Signed release discovery for operator-trusted, independently updated Sources.

The catalogue key is provisioned by the operator. A digest alone does not
authenticate a remote publisher, so no network release is accepted without a
valid signature from that key. Every HTTPS connection pins a checked public IP
while TLS still verifies the original hostname.
"""

import base64
import hashlib
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import tempfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.version import Version

from .runtime import registry, runtime_root

_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_VERSION = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}\Z")


class _PinnedHTTPS(http.client.HTTPSConnection):
    def connect(self):
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(result[4][0]).is_global
                                for result in addresses):
            raise ValueError("A Source update destination is not public")
        last_error = None
        for family, socktype, protocol, _, address in addresses:
            sock = socket.socket(family, socktype, protocol)
            try:
                sock.settimeout(self.timeout)
                sock.connect(address)
                self.sock = ssl.create_default_context().wrap_socket(sock, server_hostname=self.host)
                return
            except OSError as exc:
                last_error = exc
                sock.close()
        raise OSError("Could not reach the Source update host") from last_error


def _fetch_https(url: str, max_bytes: int) -> bytes:
    for _ in range(4):
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.port not in (None, 443)):
            raise ValueError("Source update URLs must use public HTTPS without credentials")
        connection = _PinnedHTTPS(parsed.hostname, timeout=20)
        try:
            connection.request("GET", (parsed.path or "/") + ("?" + parsed.query if parsed.query else ""),
                               headers={"Accept": "application/octet-stream", "Connection": "close"})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Source update redirect has no destination")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError("Source release endpoint is unavailable")
            if int(response.getheader("Content-Length") or "0") > max_bytes:
                raise ValueError("Source release exceeds the allowed size")
            content = response.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ValueError("Source release exceeds the allowed size")
            return content
        finally:
            connection.close()
    raise ValueError("Source update redirected too many times")


def configured_catalogs() -> dict:
    path = os.environ.get("VODLOFT_SOURCE_RELEASE_CATALOGS")
    if not path:
        return {}
    catalogs = json.loads(Path(path).read_text())
    if not isinstance(catalogs, dict) or set(catalogs) - set(registry()):
        raise ValueError("Release catalogue includes an untrusted Source")
    for source_id, config in catalogs.items():
        if not isinstance(config, dict) or set(config) != {"url", "public_key"}:
            raise ValueError(f"Invalid release catalogue configuration for {source_id}")
        try:
            Ed25519PublicKey.from_public_bytes(base64.b64decode(config["public_key"], validate=True))
        except (ValueError, TypeError) as exc:
            raise ValueError("Invalid Source release signing key") from exc
    return catalogs


def _verified_releases(source_id: str, config: dict) -> list[dict]:
    document = json.loads(_fetch_https(config["url"], 256 * 1024))
    if not isinstance(document, dict) or set(document) != {"source_id", "releases", "signature"}:
        raise ValueError("Invalid signed Source release catalogue")
    signature = document.pop("signature")
    if document["source_id"] != source_id or not isinstance(document["releases"], list):
        raise ValueError("Source release catalogue identity mismatch")
    message = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(config["public_key"], validate=True))
        key.verify(base64.b64decode(signature, validate=True), message)
    except (InvalidSignature, TypeError, ValueError) as exc:
        raise ValueError("Source release catalogue signature is invalid") from exc
    if len(document["releases"]) > 100:
        raise ValueError("Source release catalogue is too large")
    for release in document["releases"]:
        if (not isinstance(release, dict) or not {"version", "channel", "wheels"} <= set(release) or
            set(release) - {"version", "channel", "wheels", "adapter_version", "upstream_versions",
                "protocol_version", "metadata_schema_version", "packages", "configuration_version",
                "catalogue_revision", "python_requirement", "native_helpers"} or
            not isinstance(release["version"], str) or not _VERSION.fullmatch(release["version"]) or
            release["channel"] not in ("stable", "beta") or
            not isinstance(release["wheels"], dict) or not 1 <= len(release["wheels"]) <= 40):
            raise ValueError("Invalid signed Source release")
        for filename, wheel in release["wheels"].items():
            if (not isinstance(filename, str) or Path(filename).name != filename or
                not filename.endswith(".whl") or not isinstance(wheel, dict) or
                set(wheel) != {"url", "sha256"} or not isinstance(wheel["sha256"], str) or
                not _DIGEST.fullmatch(wheel["sha256"])):
                raise ValueError("Invalid signed Source wheel")
    return document["releases"]


def _version(value: str) -> tuple:
    return Version(value)


def install_remote_updates() -> list[dict]:
    """Stage verified wheelhouses, health-check, then switch new jobs atomically."""
    from .runtime import install_bundle, status

    results = []
    for source_id, config in configured_catalogs().items():
        try:
            policy = status()["policy"].get(source_id, {"automatic": True,
                "pinned_version": None, "channel": "stable"})
            releases = _verified_releases(source_id, config)
            eligible = [release for release in releases
                if release["channel"] == policy["channel"] and
                (not policy["pinned_version"] or policy["pinned_version"] == release["version"])]
            if not eligible:
                continue
            selected = max(eligible, key=lambda release: _version(release["version"]))
            version = selected["version"]
            if version in status()["installed"][source_id]:
                if policy["automatic"] and status()["active"].get(source_id) != version:
                    from .runtime import activate
                    activate(source_id, version)
                continue
            runtime_root().mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="vodloft-release-", dir=runtime_root()) as folder:
                bundle = Path(folder)
                wheels = {}
                for filename, descriptor in selected["wheels"].items():
                    content = _fetch_https(descriptor["url"], 128 * 1024 * 1024)
                    if hashlib.sha256(content).hexdigest() != descriptor["sha256"]:
                        raise ValueError("Source wheel digest mismatch")
                    (bundle / filename).write_bytes(content)
                    wheels[filename] = descriptor["sha256"]
                (bundle / "release.json").write_text(json.dumps({**selected,
                    "source_id": source_id, "wheels": wheels}))
                results.append(install_bundle(source_id, bundle, activate=policy["automatic"]))
        except Exception as error:
            from .runtime import record_failure
            record_failure(source_id, "remote_update", error)
            results.append({"source_id": source_id, "state": "failed", "reason": type(error).__name__})
    return results
