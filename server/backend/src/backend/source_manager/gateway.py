import ipaddress
import json
import os
import socket
import subprocess
import signal
import shutil
import tempfile
import threading
from urllib.parse import urlsplit
from pydantic import TypeAdapter

from source_contracts import CollectionPage, DomainCatalogue, DownloadEvent, DownloadResult, MediaSnapshot, NormalizedSnapshot, SourceError, SourceManifest, SourceMatch, SourceSearchPage, StreamLease
from .runtime import command_environment, command_for, registry

_running: dict[int, subprocess.Popen] = {}
_canceled: set[int] = set()
_running_lock = threading.Lock()


class SourceInvocationError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


_PUBLIC_ERRORS = {
    "unsupported_operation": "This Source does not support the requested operation",
    "unavailable": "Source media is currently unavailable",
    "authentication_required": "Authorization is required",
    "rate_limited": "The Source is rate limited; retry later",
    "invalid_url": "Source URL or media reference is invalid",
    "unsupported_format": "The requested media format is unavailable",
    "insufficient_disk": "Insufficient staging disk space",
    "runtime_error": "The Source runtime failed",
}
_SNAPSHOT = TypeAdapter(NormalizedSnapshot)


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
            self.commands = {}
            for source_id in registry():
                try:
                    self.commands[source_id] = command_for(source_id)[0]
                except RuntimeError:
                    # One unavailable isolated runtime must not hide healthy Sources.
                    continue

    def call(self, source_id: str, operation: str, *, timeout: int = 90,
             job_id: int | None = None, on_progress=None, on_stage=None, **options):
        command = self.commands.get(source_id)
        if not command or not isinstance(command, list) or not all(isinstance(arg, str) for arg in command):
            raise ValueError("The selected Source is not installed")
        scratch = tempfile.mkdtemp(prefix="vodloft-source-")
        events_requested = on_progress is not None or on_stage is not None
        output_file = tempfile.TemporaryFile(mode="w+t", encoding="utf-8") if not events_requested else None
        try:
            process = subprocess.Popen(command, stdin=subprocess.PIPE,
                stdout=output_file if output_file is not None else subprocess.PIPE,
                stderr=subprocess.DEVNULL if output_file is not None else subprocess.PIPE,
                text=True, start_new_session=True, env=command_environment(command))
        except BaseException:
            if output_file is not None:
                output_file.close()
            shutil.rmtree(scratch, ignore_errors=True)
            raise
        try:
            if job_id is not None:
                with _running_lock:
                    _running[job_id] = process
                    if job_id in _canceled and process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGTERM)
                        except ProcessLookupError:
                            pass
            if not events_requested:
                try:
                    process.communicate(
                        input=json.dumps({"operation": operation, **options, "scratch": scratch}), timeout=timeout)
                    output_file.seek(0)
                    stdout = output_file.read(32 * 1024 * 1024 + 1)
                    if len(stdout) > 32 * 1024 * 1024:
                        raise SourceInvocationError("runtime_error", "Source response is too large")
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    raise
            else:
                timed_out = threading.Event()
                def kill_timeout():
                    if process.poll() is None:
                        timed_out.set()
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                def read_events():
                    for line in iter(lambda: process.stderr.readline(4096), ""):
                        try:
                            packet = json.loads(line)
                            if isinstance(packet, dict) and "event" in packet:
                                event = DownloadEvent.model_validate(packet["event"])
                                if on_stage:
                                    on_stage(event.stage)
                                if event.stage == "downloading" and on_progress:
                                    on_progress(event.percent)
                        except (ValueError, TypeError, KeyError):
                            continue
                        except Exception:
                            # A UI progress update must not abort the Source transfer.
                            continue
                reader = threading.Thread(target=read_events, daemon=True)
                timer = threading.Timer(timeout, kill_timeout)
                reader.start()
                timer.start()
                try:
                    process.stdin.write(json.dumps({"operation": operation, **options, "scratch": scratch}))
                    process.stdin.close()
                    stdout = process.stdout.read(32 * 1024 * 1024 + 1)
                    if len(stdout) > 32 * 1024 * 1024:
                        raise SourceInvocationError("runtime_error", "Source response is too large")
                    process.wait()
                    reader.join(timeout=1)
                    if timed_out.is_set():
                        raise subprocess.TimeoutExpired(command, timeout)
                except BaseException:
                    if process.poll() is None:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    process.wait()
                    raise
                finally:
                    timer.cancel()
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
            if job_id is not None:
                with _running_lock:
                    _running.pop(job_id, None)
                    _canceled.discard(job_id)
            if output_file is not None:
                output_file.close()
            shutil.rmtree(scratch, ignore_errors=True)
        if process.returncode:
            # The worker's stderr may contain upstream URLs or credentials.
            raise SourceInvocationError("runtime_error",
                f"{source_id} could not {operation} this media (exit {process.returncode})")
        result = json.loads(stdout)
        if isinstance(result, dict) and "error" in result:
            error = SourceError.model_validate(result["error"])
            # Source output is untrusted and can include access tokens in an
            # exception string. Expose only protocol-defined public wording.
            raise SourceInvocationError(error.code, _PUBLIC_ERRORS[error.code])
        return result

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
                **source_options) -> MediaSnapshot:
        validate_public_url(url)
        return _SNAPSHOT.validate_python(self.call(source_id, "resolve", url=url,
            max_entries=max_entries, **source_options))

    def match(self, source_id: str, url: str) -> SourceMatch:
        validate_public_url(url)
        result = SourceMatch.model_validate(self.call(source_id, "match", url=url, timeout=15))
        if result.source_id != source_id:
            raise ValueError("Source returned a mismatched identity")
        return result

    def catalogue(self, source_id: str) -> dict:
        return DomainCatalogue.model_validate(self.call(source_id, "domains", timeout=20)).model_dump()

    def entries(self, source_id: str, url: str, *, cursor: str | None = None,
                limit: int = 50, **source_options) -> CollectionPage:
        validate_public_url(url)
        if not 1 <= limit <= 100:
            raise ValueError("Collection page size must be between 1 and 100")
        return CollectionPage.model_validate(self.call(source_id, "entries", url=url,
            cursor=cursor, limit=limit, timeout=120, **source_options))

    def search(self, source_id: str, query: str, *, cursor: str | None = None,
               limit: int = 30, **source_options) -> SourceSearchPage:
        if not 1 <= len(query.strip()) <= 200 or not 1 <= limit <= 50:
            raise ValueError("Enter a search phrase and choose up to 50 results")
        return SourceSearchPage.model_validate(self.call(source_id, "search", query=query.strip(),
            cursor=cursor, limit=limit, timeout=120, **source_options))

    def download(self, source_id: str, url: str, staging: str,
                 preferred_format: str = "format_1080p", job_id: int | None = None,
                 on_progress=None, on_stage=None, timeout: int = 3600,
                 representation: dict | None = None, metadata: dict | None = None,
                 reference: dict | None = None,
                 **source_options) -> DownloadResult:
        validate_public_url(url)
        return DownloadResult.model_validate(self.call(source_id, "download", url=url, staging=staging,
                                                      preferred_format=preferred_format,
                                                      representation=representation or {}, metadata=metadata or {},
                                                      reference=reference,
                                                      timeout=timeout, job_id=job_id,
                                                      on_progress=on_progress,
                                                      on_stage=on_stage,
                                                      **source_options))

    def stream_lease(self, source_id: str, url: str, **source_options) -> StreamLease:
        validate_public_url(url)
        lease = StreamLease.model_validate(self.call(source_id, "stream_lease", url=url,
            timeout=90, **source_options))
        validate_public_url(lease.url)
        return lease
