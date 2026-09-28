import ipaddress
import json
import os
import socket
import subprocess
import signal
import threading
from urllib.parse import urlsplit

from source_contracts import DownloadResult, MediaSnapshot, SourceManifest
from .runtime import MODULES, command_for

_running: dict[int, subprocess.Popen] = {}
_canceled: set[int] = set()
_running_lock = threading.Lock()


def cancel_running_job(job_id: int) -> None:
    with _running_lock:
        _canceled.add(job_id)
        process = _running.get(job_id)
    if process and process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def clear_canceled_job(job_id: int) -> None:
    with _running_lock:
        _canceled.discard(job_id)


def validate_public_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Enter a public HTTP or HTTPS media URL without embedded credentials")
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise ValueError("Private or local network media URLs are not allowed")
        return url
    try:
        addresses = socket.getaddrinfo(parsed.hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("The media hostname could not be resolved") from exc
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise ValueError("Private or local network media URLs are not allowed")
    return url


class SourceGateway:
    """A fresh worker per operation keeps Source implementation imports out of core."""

    def __init__(self, commands: dict[str, list[str]] | None = None):
        if commands is not None:
            self.commands = commands
        elif os.environ.get("VODLOFT_SOURCE_COMMANDS"):
            self.commands = json.loads(os.environ["VODLOFT_SOURCE_COMMANDS"])
        else:
            self.commands = {source_id: command_for(source_id)[0] for source_id in MODULES}

    def call(self, source_id: str, operation: str, *, timeout: int = 90,
             job_id: int | None = None, **options):
        command = self.commands.get(source_id)
        if not command or not isinstance(command, list) or not all(isinstance(arg, str) for arg in command):
            raise ValueError("The selected Source is not installed")
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, start_new_session=True)
        if job_id is not None:
            with _running_lock:
                _running[job_id] = process
                if job_id in _canceled and process.poll() is None:
                    os.killpg(process.pid, signal.SIGTERM)
        try:
            try:
                stdout, _stderr = process.communicate(
                    input=json.dumps({"operation": operation, **options}), timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                raise
        finally:
            if job_id is not None:
                with _running_lock:
                    _running.pop(job_id, None)
                    _canceled.discard(job_id)
        if process.returncode:
            # The worker's stderr may contain upstream URLs or credentials.
            raise RuntimeError(f"{source_id} could not {operation} this media (exit {process.returncode})")
        return json.loads(stdout)

    def manifests(self) -> list[SourceManifest]:
        manifests = []
        for source_id in self.commands:
            try:
                manifest = SourceManifest.model_validate(self.call(source_id, "manifest", timeout=15))
                if manifest.protocol_version == 1 and manifest.source_id == source_id:
                    manifests.append(manifest)
            except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                continue
        return manifests

    def resolve(self, source_id: str, url: str, max_entries: int = 100,
                access_token: str | None = None) -> MediaSnapshot:
        validate_public_url(url)
        return MediaSnapshot.model_validate(self.call(source_id, "resolve", url=url,
            max_entries=max_entries, access_token=access_token))

    def catalogue(self, source_id: str) -> dict:
        return self.call(source_id, "domains", timeout=20)

    def download(self, source_id: str, url: str, staging: str,
                 preferred_format: str = "format_1080p", access_token: str | None = None,
                 job_id: int | None = None) -> DownloadResult:
        validate_public_url(url)
        return DownloadResult.model_validate(self.call(source_id, "download", url=url, staging=staging,
                                                      preferred_format=preferred_format,
                                                      access_token=access_token, timeout=3600,
                                                      job_id=job_id))
