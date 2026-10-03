"""Verified, separately installed Source runtimes with atomic activation."""

import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from packaging.specifiers import SpecifierSet
from packaging.version import Version
from contextlib import contextmanager
from pathlib import Path

from source_contracts import PROTOCOL_VERSION, METADATA_SCHEMA_VERSION, DomainCatalogue, SourceManifest

MODULES = {"yt-dlp": "vodloft_source_ytdlp.worker",
           "dailywire": "vodloft_source_dailywire.worker"}
PACKAGES = {"yt-dlp": "vodloft-source-ytdlp",
            "dailywire": "vodloft-source-dailywire"}
_last_remote_check = 0.0


def registry() -> dict[str, dict[str, str]]:
    """Only explicitly configured, operator-trusted adapters can be installed."""
    sources = {source_id: {"module": module, "package": PACKAGES[source_id]}
               for source_id, module in MODULES.items()}
    path = os.environ.get("VODLOFT_SOURCE_REGISTRY")
    if not path:
        return sources
    configured = json.loads(Path(path).read_text()).get("sources", {})
    if not isinstance(configured, dict):
        raise ValueError("Source registry must contain a sources object")
    for source_id, value in configured.items():
        if source_id in sources or not isinstance(value, dict) or not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", source_id):
            raise ValueError("Invalid or duplicate trusted Source ID")
        module, package = value.get("module"), value.get("package")
        if (not isinstance(module, str) or not re.fullmatch(r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*)+", module) or
            not isinstance(package, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}", package)):
            raise ValueError("Invalid trusted Source package or module")
        sources[source_id] = {"module": module, "package": package}
    return sources


def runtime_root() -> Path:
    return Path(os.environ.get("VODLOFT_SOURCE_RUNTIME_ROOT", "config/source-runtimes")).resolve()


@contextmanager
def _locked(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read_state(root: Path) -> dict:
    path = root / "state.json"
    return json.loads(path.read_text()) if path.is_file() else {"active": {}, "history": [], "policy": {}}


def _write_state(root: Path, state: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", dir=root, prefix=".state-", delete=False) as output:
        json.dump(state, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
        temporary = Path(output.name)
    os.replace(temporary, root / "state.json")


def command_for(source_id: str) -> tuple[list[str], str]:
    sources = registry()
    if source_id not in sources:
        raise ValueError("Untrusted Source ID")
    module = sources[source_id]["module"]
    root = runtime_root()
    state = _read_state(root)
    version = state.get("active", {}).get(source_id)
    if version:
        command = [str(root / source_id / version / "bin" / "python"), "-m", module]
        if not Path(command[0]).is_file():
            raise RuntimeError("Active Source runtime is missing")
        return command, version
    if os.environ.get("VODLOFT_REQUIRE_ISOLATED_SOURCES") == "1":
        raise RuntimeError("The selected Source has no active isolated runtime")
    return [sys.executable, "-m", module], "bundled"


def status() -> dict:
    root = runtime_root()
    state = _read_state(root)
    return {"active": state.get("active", {}), "history": state.get("history", [])[-30:],
            "policy": state.get("policy", {}),
            "installed": {source: sorted(p.name for p in (root / source).iterdir()
                          if p.is_dir() and not p.name.startswith("."))
                          if (root / source).is_dir() else [] for source in registry()}}


def _probe(command: list[str], source_id: str) -> SourceManifest:
    result = subprocess.run(command, input='{"operation":"manifest"}', text=True,
        capture_output=True, timeout=20, check=True)
    manifest = SourceManifest.model_validate_json(result.stdout)
    if (manifest.source_id != source_id or manifest.protocol_version != PROTOCOL_VERSION or
            manifest.metadata_schema_version != METADATA_SCHEMA_VERSION):
        raise ValueError("Source runtime failed contract compatibility")
    if "domain_catalogue" in manifest.capabilities:
        _catalogue(command, source_id)
    python_version = subprocess.run([command[0], "-c", "import platform; print(platform.python_version())"],
        text=True, capture_output=True, timeout=10, check=True).stdout.strip()
    if Version(python_version) not in SpecifierSet(manifest.python_requirement):
        raise ValueError("The Source requires a different Python interpreter")
    helper_versions = {}
    for helper in manifest.native_helpers:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", helper) or not shutil.which(helper):
            raise ValueError("A required Source native helper is unavailable")
        version_result = subprocess.run([helper, '-version' if helper in {'ffmpeg', 'ffprobe'} else '--version'],
            text=True, capture_output=True, timeout=10, check=True)
        output = (version_result.stdout or version_result.stderr).splitlines()
        helper_versions[helper] = output[0][:300] if output else 'available'

    # Every operation is private and non-networked. Sources declaring health
    # checks must prove their dependencies before receiving real jobs.
    if "health" in manifest.capabilities:
        health = subprocess.run(command, input='{"operation":"health"}', text=True,
            capture_output=True, timeout=20, check=True)
        if json.loads(health.stdout).get("healthy") is not True:
            raise ValueError("The Source runtime health check failed")
    return manifest.model_copy(update={'python_version': python_version, 'helper_versions': helper_versions})


def _catalogue(command: list[str], source_id: str) -> DomainCatalogue:
    result = subprocess.run(command, input='{"operation":"domains"}', text=True,
        capture_output=True, timeout=20, check=True)
    catalogue = DomainCatalogue.model_validate_json(result.stdout)
    if any(domain.source_id != source_id for domain in catalogue.items):
        raise ValueError("Domain catalogue returned another Source's identity")
    return catalogue


def _reconcile_domains(command: list[str], manifest: SourceManifest) -> None:
    if "domain_catalogue" not in manifest.capabilities:
        return
    catalogue = _catalogue(command, manifest.source_id)
    from backend.db import get_session
    from backend.db.models.vodloft import Domain, SourceDomain
    from backend.db.models.local_media_profile import DomainLocalMediaProfile
    from sqlalchemy import select
    with get_session() as session:
        advertised = {domain.hostname.rstrip('.').lower().encode('idna').decode('ascii')
                      for domain in catalogue.items}
        for support in session.scalars(select(SourceDomain).where(SourceDomain.source_id == manifest.source_id)).all():
            domain = session.get(Domain, support.domain_id)
            if catalogue.exhaustive and domain.hostname not in advertised:
                support.support = "failing"
            elif domain.hostname in advertised:
                support.support = "advertised"
            other = session.scalar(select(SourceDomain.source_id).where(
                SourceDomain.domain_id == domain.id, SourceDomain.source_id != manifest.source_id,
                SourceDomain.support.in_(["advertised", "verified", "authentication_required"])))
            for profile in session.scalars(select(DomainLocalMediaProfile).where(
                    DomainLocalMediaProfile.domain_id == domain.id)).all():
                if support.support == "failing" and not other:
                    profile.impairment = "Installed Sources no longer advertise support for this Domain"
                elif profile.impairment == "Installed Sources no longer advertise support for this Domain":
                    profile.impairment = None
        session.commit()


def _interpreter(source_id: str, release: dict) -> str:
    configured = os.environ.get("VODLOFT_SOURCE_PYTHONS")
    interpreters = json.loads(Path(configured).read_text()) if configured else {}
    python = str(interpreters.get(source_id, sys.executable))
    if not Path(python).is_absolute() or not Path(python).is_file():
        raise ValueError("Configure an existing absolute Source Python interpreter")
    version = subprocess.run([python, "-c", "import platform; print(platform.python_version())"],
        text=True, capture_output=True, timeout=10, check=True).stdout.strip()
    if Version(version) not in SpecifierSet(release.get("python_requirement", ">=3.12")):
        raise ValueError("The release is incompatible with the selected Source Python interpreter")
    return python


def _validate_saved_configuration(manifest: SourceManifest) -> None:
    from backend.db import get_session
    from backend.db.models.vodloft import SourceConnection
    from sqlalchemy import select
    fields = {field.name: field for field in manifest.configuration_schema}
    with get_session() as session:
        connections = session.scalars(select(SourceConnection).where(
            SourceConnection.source_id == manifest.source_id, SourceConnection.enabled.is_(True))).all()
        for connection in connections:
            values = dict(connection.settings or {})
            if connection.authentication_reference:
                from .secrets import load
                authentication = json.loads(load(connection.authentication_reference))
                values.update(authentication.get("configuration", {}))
            saved = set(values) | set(connection.secret_references or {})
            if saved - set(fields):
                raise ValueError("The Source configuration changed; review saved connections before activation")
            for name, value in values.items():
                field = fields[name]
                if (field.kind == "number" and (isinstance(value, bool) or not isinstance(value, (int, float))) or
                    field.kind == "select" and value not in field.options or
                    field.kind in {"text", "secret", "credential_file"} and not isinstance(value, str)):
                    raise ValueError("A saved connection is incompatible with the new Source schema")
            if any(field.required and field.name not in saved for field in fields.values()):
                raise ValueError("The new Source schema requires additional connection configuration")


def record_failure(source_id: str, action: str, error: Exception) -> None:
    root = runtime_root()
    with _locked(root):
        state = _read_state(root)
        state["history"].append({"source_id": source_id, "action": action, "state": "failed",
            "at": datetime.now(timezone.utc).isoformat(), "reason": type(error).__name__,
            "message": "Release verification, installation or compatibility check failed"})
        state["history"] = state["history"][-200:]
        _write_state(root, state)


def install_bundle(source_id: str, bundle: Path, *, activate: bool = True) -> dict:
    """Install a trusted, digest-pinned wheelhouse without network or app-env writes."""
    sources = registry()
    if source_id not in sources:
        raise ValueError("Untrusted Source ID")
    module, package = sources[source_id]["module"], sources[source_id]["package"]
    release = json.loads((bundle / "release.json").read_text())
    version = release.get("version", "")
    if (release.get("source_id") != source_id or
        not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}", version)):
        raise ValueError("Invalid Source release manifest")
    wheels = release.get("wheels")
    if not isinstance(wheels, dict) or not wheels:
        raise ValueError("Release has no pinned wheels")
    if {p.name for p in bundle.glob("*.whl")} != set(wheels):
        raise ValueError("Source bundle contains undeclared or missing wheels")
    if release.get("channel", "stable") not in {"stable", "beta"}:
        raise ValueError("Invalid Source release channel")
    if (release.get("protocol_version", PROTOCOL_VERSION) != PROTOCOL_VERSION or
            release.get("metadata_schema_version", METADATA_SCHEMA_VERSION) != METADATA_SCHEMA_VERSION):
        raise ValueError("Source release requires a different protocol or metadata schema version")
    for filename, digest in wheels.items():
        if Path(filename).name != filename or not filename.endswith(".whl") or not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid wheel entry")
        if hashlib.sha256((bundle / filename).read_bytes()).hexdigest() != digest:
            raise ValueError("Source wheel digest mismatch")
    root = runtime_root()
    target = root / source_id / version
    with _locked(root):
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".install-", dir=target.parent))
            try:
                subprocess.run([_interpreter(source_id, release), "-m", "venv", str(staging)], timeout=60, check=True,
                    capture_output=True)
                python = staging / "bin" / "python"
                subprocess.run([str(python), "-m", "pip", "install", "--no-index",
                    "--find-links", str(bundle), f"{package}=={release.get('adapter_version', version)}"],
                    timeout=240, check=True, capture_output=True)
                _probe([str(python), "-m", module], source_id)
                (staging / "release.json").write_text(json.dumps(release, sort_keys=True))
                os.replace(staging, target)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        saved_release = target / "release.json"
        if saved_release.is_file() and json.loads(saved_release.read_text()) != release:
            raise ValueError("An installed Source runtime is immutable; publish a new bundle version")
        # A previously installed bundle is still probed before a new activation.
        manifest = _probe([str(target / "bin" / "python"), "-m", module], source_id)
        if manifest.version != release.get("adapter_version", version):
            raise ValueError("The installed adapter version does not match the release")
        if any(manifest.upstream_versions.get(name) != expected
               for name, expected in release.get("upstream_versions", {}).items()):
            raise ValueError("The installed upstream dependencies do not match the release")
        if activate:
            _validate_saved_configuration(manifest)
        state = _read_state(root)
        if activate and state["active"].get(source_id) != version:
            _reconcile_domains([str(target / "bin" / "python"), "-m", module], manifest)
            previous = state["active"].get(source_id)
            state["active"][source_id] = version
            state["history"].append({"source_id": source_id, "from": previous,
                "to": version, "action": "activate", "state": "available",
                "at": datetime.now(timezone.utc).isoformat(), "manifest": manifest.model_dump(mode="json")})
            _write_state(root, state)
    return {"source_id": source_id, "version": version, "active": activate,
            "manifest": manifest.model_dump(mode="json")}


def activate(source_id: str, version: str) -> dict:
    root = runtime_root()
    sources = registry()
    if source_id not in sources or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}", version):
        raise ValueError("Unknown Source runtime")
    with _locked(root):
        command = [str(root / source_id / version / "bin" / "python"), "-m", sources[source_id]["module"]]
        manifest = _probe(command, source_id)
        _validate_saved_configuration(manifest)
        _reconcile_domains(command, manifest)
        state = _read_state(root)
        previous = state["active"].get(source_id)
        state["active"][source_id] = version
        state["history"].append({"source_id": source_id, "from": previous,
            "to": version, "action": "activate", "state": "available",
            "at": datetime.now(timezone.utc).isoformat(), "manifest": manifest.model_dump(mode="json")})
        _write_state(root, state)
    return manifest.model_dump(mode="json")


def rollback(source_id: str) -> dict:
    state = _read_state(runtime_root())
    activations = [entry for entry in reversed(state.get("history", []))
        if entry.get("action") == "activate" and entry["source_id"] == source_id
        and entry.get("to") == state["active"].get(source_id)]
    if not activations:
        raise ValueError("No retained prior runtime is available")
    previous = activations[0].get("from")
    if previous is None:
        sources = registry()
        manifest = _probe([sys.executable, "-m", sources[source_id]["module"]], source_id)
        _validate_saved_configuration(manifest)
        _reconcile_domains([sys.executable, "-m", sources[source_id]["module"]], manifest)
        with _locked(runtime_root()):
            state = _read_state(runtime_root())
            current = state["active"].pop(source_id, None)
            state["history"].append({"source_id": source_id, "from": current,
                "to": None, "action": "rollback", "state": "available",
                "at": datetime.now(timezone.utc).isoformat(), "manifest": manifest.model_dump(mode="json")})
            _write_state(runtime_root(), state)
        return manifest.model_dump(mode="json")
    return activate(source_id, previous)


def set_policy(source_id: str, automatic: bool, pinned_version: str | None,
               channel: str = "stable") -> dict:
    if source_id not in registry() or pinned_version and not re.fullmatch(
            r"[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}", pinned_version) or channel not in {"stable", "beta"}:
        raise ValueError("Invalid Source update policy")
    root = runtime_root()
    with _locked(root):
        state = _read_state(root)
        state.setdefault("policy", {})[source_id] = {"automatic": automatic,
            "pinned_version": pinned_version, "channel": channel}
        _write_state(root, state)
    return state["policy"][source_id]


def install_bundled_updates() -> list[dict]:
    """Trusted release bundles can be supplied on a persistent mounted directory."""
    catalog = Path(os.environ.get("VODLOFT_SOURCE_BUNDLE_DIR", "config/source-bundles"))
    if not catalog.is_dir():
        return []
    results = []
    for source_id in registry():
        try:
            directory = catalog / source_id
            if not directory.is_dir():
                continue
            candidates = []
            policy = status()["policy"].get(source_id, {"automatic": True,
                "pinned_version": None, "channel": "stable"})
            for bundle in sorted(directory.iterdir()):
                if bundle.is_dir() and (bundle / "release.json").is_file():
                    release = json.loads((bundle / "release.json").read_text())
                    if release.get("version") not in status()["installed"][source_id]:
                        results.append(install_bundle(source_id, bundle, activate=False))
                    if (release.get("channel", "stable") == policy.get("channel", "stable") and
                        (not policy["pinned_version"] or policy["pinned_version"] == release.get("version"))):
                        candidates.append(release["version"])
            if candidates and policy["automatic"]:
                version = max(candidates, key=Version)
                if status()["active"].get(source_id) != version:
                    activate(source_id, version)
        except Exception as error:
            from .runtime import record_failure
            record_failure(source_id, "mounted_update", error)
            results.append({"source_id": source_id, "state": "failed", "reason": type(error).__name__})
    return results


def check_updates(*, force: bool = False) -> list[dict]:
    """Check mounted bundles and periodically discover signed remote releases."""
    global _last_remote_check
    results = install_bundled_updates()
    now = time.monotonic()
    if force or not _last_remote_check or now - _last_remote_check >= 6 * 60 * 60:
        from .release_catalog import install_remote_updates
        results.extend(install_remote_updates())
        _last_remote_check = now
    return results
