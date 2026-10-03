"""Build reproducible, immutable Source releases from the workspace lock.

Usage: uv run python tools/build_source_bundles.py dist/source-bundles
       uv run python tools/build_source_bundles.py dist/source-bundles --source yt-dlp --release-version 1.0.0+extractor.20260819
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
import venv
from pathlib import Path

from create_source_bundle_manifests import create_manifest

SOURCES = {
    'yt-dlp': ('source_ytdlp', ['source_contracts', 'source_media', 'source_ytdlp']),
    'dailywire': ('source_dailywire', ['source_contracts', 'source_media', 'dailywire_api', 'source_dailywire']),
}


def build(output: Path, source_id: str, release_version: str | None, channel: str):
    project_dir, members = SOURCES[source_id]
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / 'server' / project_dir / 'pyproject.toml').read_text())['project']
    version = release_version or project['version']
    import re
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._+-]{0,79}', version):
        raise ValueError('Invalid immutable release version')
    target = output.resolve() / source_id / version
    if target.exists():
        raise ValueError('A Source bundle version already exists; publish a new version')
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.build-', dir=target.parent))
    try:
        for member in members:
            subprocess.run(['uv', 'build', '--wheel', str(root / 'server' / member),
                '--out-dir', str(staging)], cwd=root, check=True)
        requirements = staging / 'requirements.txt'
        subprocess.run(['uv', 'export', '--frozen', '--no-dev', '--package', project['name'],
            '--no-emit-workspace', '--output-file', str(requirements)], cwd=root, check=True,
            stdout=subprocess.DEVNULL)
        # uv environments omit pip. Use a disposable stdlib-created tool
        # environment; it never becomes part of the Source wheel payload.
        tool_env = staging / '.build-tools'
        venv.EnvBuilder(with_pip=True).create(tool_env)
        tool_python = tool_env / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
        subprocess.run([str(tool_python), '-m', 'pip', 'download', '--only-binary=:all:',
            '--dest', str(staging), '--require-hashes', '-r', str(requirements)], cwd=root, check=True)
        shutil.rmtree(tool_env)
        requirements.unlink()
        create_manifest(staging, source_id, version, project['name'], project['requires-python'], channel)
        os.replace(staging, target)
        print(f'Built {source_id} release {version}: {target}')
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--source', choices=sorted(SOURCES))
    parser.add_argument('--release-version')
    parser.add_argument('--channel', choices=['stable', 'beta'], default='stable')
    args = parser.parse_args()
    if args.release_version and not args.source:
        parser.error('--release-version requires one --source')
    for source in [args.source] if args.source else SOURCES:
        build(args.output, source, args.release_version, args.channel)
