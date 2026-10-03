"""Digest and dependency manifests for independently released Source wheelhouses."""
import hashlib
import json
import sys
import zipfile
from email.parser import Parser
from pathlib import Path

from source_contracts import PROTOCOL_VERSION, METADATA_SCHEMA_VERSION


def create_manifest(bundle: Path, source_id: str, release_version: str, adapter_package: str,
                    python_requirement: str = '>=3.12', channel: str = 'stable'):
    wheels, packages = {}, {}
    for path in sorted(bundle.glob('*.whl')):
        wheels[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        with zipfile.ZipFile(path) as archive:
            metadata_file = next(name for name in archive.namelist() if name.endswith('.dist-info/METADATA'))
            metadata = Parser().parsestr(archive.read(metadata_file).decode('utf-8'))
            packages[metadata['Name'].lower().replace('_', '-')] = metadata['Version']
    if adapter_package not in packages:
        raise ValueError('The Source adapter wheel is missing')
    release = {'source_id': source_id, 'version': release_version, 'adapter_version': packages[adapter_package],
        'channel': channel, 'protocol_version': PROTOCOL_VERSION, 'metadata_schema_version': METADATA_SCHEMA_VERSION,
        'python_requirement': python_requirement, 'packages': packages, 'wheels': wheels,
        'upstream_versions': {name: packages[name] for name in ('yt-dlp', 'dailywire-api') if name in packages}}
    (bundle / 'release.json').write_text(json.dumps(release, indent=2, sort_keys=True) + '\n')
    return release


if __name__ == '__main__':
    root = Path(sys.argv[1])
    for source_id, package in [('yt-dlp', 'vodloft-source-ytdlp'), ('dailywire', 'vodloft-source-dailywire')]:
        for bundle in sorted((root / source_id).iterdir()):
            if bundle.is_dir():
                create_manifest(bundle, source_id, bundle.name, package)
