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
from contextlib import contextmanager
from pathlib import Path

from source_contracts import PROTOCOL_VERSION, SourceManifest

MODULES = {"yt-dlp": "vodloft_source_ytdlp.worker",
           "dailywire": "vodloft_source_dailywire.worker"}
PACKAGES = {"yt-dlp": "vodloft-source-ytdlp",
            "dailywire": "vodloft-source-dailywire"}


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
    return [sys.executable, "-m", module], "bundled"


def status() -> dict:
    root = runtime_root()
    state = _read_state(root)
    return {"active": state.get("active", {}), "history": state.get("history", [])[-30:],
            "policy": state.get("policy", {}),
            "installed": {source: sorted(p.name for p in (root / source).iterdir() if p.is_dir())
                          if (root / source).is_dir() else [] for source in registry()}}


def _probe(command: list[str], source_id: str) -> SourceManifest:
    result = subprocess.run(command, input='{"operation":"manifest"}', text=True,
        capture_output=True, timeout=20, check=True)
    manifest = SourceManifest.model_validate_json(result.stdout)
    if manifest.source_id != source_id or manifest.protocol_version != PROTOCOL_VERSION:
        raise ValueError("Source runtime failed contract compatibility")
    return manifest


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
    if release.get("protocol_version", PROTOCOL_VERSION) != PROTOCOL_VERSION:
        raise ValueError("Source release requires a different protocol version")
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
                subprocess.run([sys.executable, "-m", "venv", str(staging)], timeout=60, check=True,
                    capture_output=True)
                python = staging / "bin" / "python"
                subprocess.run([str(python), "-m", "pip", "install", "--no-index",
                    "--find-links", str(bundle), f"{package}=={version}"],
                    timeout=240, check=True, capture_output=True)
                _probe([str(python), "-m", module], source_id)
                os.replace(staging, target)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        # A previously installed bundle is still probed before a new activation.
        manifest = _probe([str(target / "bin" / "python"), "-m", module], source_id)
        state = _read_state(root)
        if activate and state["active"].get(source_id) != version:
            previous = state["active"].get(source_id)
            state["active"][source_id] = version
            state["history"].append({"source_id": source_id, "from": previous,
                "to": version, "action": "activate"})
            _write_state(root, state)
    return {"source_id": source_id, "version": version, "active": activate,
            "manifest": manifest.model_dump()}


def activate(source_id: str, version: str) -> dict:
    root = runtime_root()
    sources = registry()
    if source_id not in sources or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}", version):
        raise ValueError("Unknown Source runtime")
    with _locked(root):
        command = [str(root / source_id / version / "bin" / "python"), "-m", sources[source_id]["module"]]
        manifest = _probe(command, source_id)
        state = _read_state(root)
        previous = state["active"].get(source_id)
        state["active"][source_id] = version
        state["history"].append({"source_id": source_id, "from": previous,
            "to": version, "action": "activate"})
        _write_state(root, state)
    return manifest.model_dump()


def rollback(source_id: str) -> dict:
    state = _read_state(runtime_root())
    previous = next((entry["from"] for entry in reversed(state.get("history", []))
                     if entry["source_id"] == source_id and entry["to"] == state["active"].get(source_id)
                     and entry["from"]), None)
    if not previous:
        raise ValueError("No retained prior runtime is available")
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
            version = max(candidates, key=lambda value: tuple(int(part) for part in re.findall(r"\d+", value)))
            if status()["active"].get(source_id) != version:
                activate(source_id, version)
    return results
