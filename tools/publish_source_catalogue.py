"""Build a signed Source release catalogue from a verified wheelhouse.

The publisher supplies an Ed25519 PEM key and public HTTPS wheel URLs. This
tool writes files only; uploading or rotating an operator's trust key is explicit.
"""
import argparse
import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import quote, urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def sign_bundle(bundle: Path, url_base: str, private_key_file: Path, output: Path, existing: Path | None = None):
    parsed = urlsplit(url_base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use a public HTTPS directory URL without credentials')
    manifest = json.loads((bundle / 'release.json').read_text())
    source_id = manifest['source_id']
    declared = manifest['wheels']
    if {path.name for path in bundle.glob('*.whl')} != set(declared):
        raise ValueError('The wheelhouse differs from its declared release')
    wheels = {}
    for filename, expected in declared.items():
        if Path(filename).name != filename or not filename.endswith('.whl'):
            raise ValueError('Invalid wheel filename')
        actual = hashlib.sha256((bundle / filename).read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError('A wheel digest changed after the release was built')
        wheels[filename] = {'sha256': actual, 'url': url_base.rstrip('/') + '/' + quote(filename)}
    native_executables = {}
    native_directory = bundle / 'native' / 'bin'
    declared_native = manifest.get('native_executables', {})
    if (not isinstance(declared_native, dict) or len(declared_native) > 16 or
            (bundle / 'native').is_symlink() or native_directory.is_symlink() or
            native_directory.exists() and not native_directory.is_dir()):
        raise ValueError('Invalid native helper inventory')
    actual_native = {path.name for path in native_directory.iterdir()} if native_directory.is_dir() else set()
    if actual_native != set(declared_native):
        raise ValueError('The native helper files differ from their declared release')
    for filename, expected in declared_native.items():
        if not isinstance(filename, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', filename):
            raise ValueError('Invalid native helper filename')
        path = native_directory / filename
        if path.is_symlink() or not path.is_file():
            raise ValueError('Native helpers must be regular bundled files')
        with path.open('rb') as handle:
            actual = hashlib.file_digest(handle, 'sha256').hexdigest()
        if actual != expected:
            raise ValueError('A native helper digest changed after the release was built')
        native_executables[filename] = {'sha256': actual,
            'url': url_base.rstrip('/') + '/native/bin/' + quote(filename)}
    allowed = {'version', 'adapter_version', 'channel', 'upstream_versions', 'protocol_version',
        'metadata_schema_version', 'packages', 'python_requirement', 'native_helpers',
        'configuration_version', 'catalogue_revision'}
    release = {key: value for key, value in manifest.items() if key in allowed}
    release['wheels'] = wheels
    if 'native_executables' in manifest:
        release['native_executables'] = native_executables
    key = serialization.load_pem_private_key(private_key_file.read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Use an Ed25519 private signing key')
    releases = []
    if existing:
        document = json.loads(existing.read_text())
        if document['source_id'] != source_id:
            raise ValueError('The existing catalogue belongs to a different Source')
        signature = base64.b64decode(document.pop('signature'), validate=True)
        key.public_key().verify(signature, json.dumps(document, sort_keys=True,
            separators=(',', ':'), ensure_ascii=False).encode())
        releases = [entry for entry in document['releases'] if entry['version'] != release['version']]
    document = {'source_id': source_id, 'releases': [*releases, release]}
    if len(document['releases']) > 100:
        raise ValueError('Retire old catalogue entries before adding another release')
    message = json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    document['signature'] = base64.b64encode(key.sign(message)).decode()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, indent=2, ensure_ascii=False) + '\n')
    public_key = base64.b64encode(key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    return {'source_id': source_id, 'public_key': public_key, 'catalogue': str(output)}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    parser.add_argument('--url-base', required=True)
    parser.add_argument('--private-key-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--existing', type=Path)
    args = parser.parse_args()
    print(json.dumps(sign_bundle(args.bundle, args.url_base, args.private_key_file, args.output, args.existing), indent=2))
