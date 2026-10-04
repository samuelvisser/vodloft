# Sources and independent releases

A Source is an operator-trusted adapter process. Core sends one JSON request on stdin and reads one JSON result on stdout. A fresh worker handles each operation. Normalized contracts live in `server/source_contracts`; adapters must not import backend database, configuration, HTTP models, or integration modules.

The built-in packages are `vodloft-source-ytdlp` and `vodloft-source-dailywire`. They share `vodloft-source-media` for acquisition/FFmpeg processing while remaining outside the core process. Source wheels and dependencies are installed in separate immutable environments; updating them does not replace core's dependencies.

## Contract

Implement `manifest` and the advertised operations. The manifest declares a stable Source ID, adapter version, protocol and metadata schema versions, upstream dependency versions, Python requirement, native helpers, capability flags, and a versioned configuration schema.

Current protocol/schema versions are both **1**. Supported contracts include:

- URL matching and resolution into Collection, Video, Movie, or Movie Extra snapshots.
- Bounded Collection pages with opaque cursors and completion status.
- Optional search previews and Domain catalogues. A non-exhaustive catalogue does not forbid resolving another public Domain.
- Acquisition requests with Source/account identity, a representation policy, metadata, and a staging directory.
- Typed failure envelopes. Core exposes protocol-defined public messages rather than upstream exceptions containing secrets.
- Optional progress events on stderr as `{"event":{"stage":"downloading","percent":25}}`. Keep stdout exclusively for the operation result.
- Private renewable stream leases and Source-mediated HLS child fetching.
- Optional authentication start/poll/refresh operations. Public responses contain status/challenges; tokens and private state remain encrypted in the selected Source connection.

See the typed models in `server/source_contracts/src/source_contracts/__init__.py` and the built-in worker implementations. Do not advertise a capability the worker cannot fulfill.

Configuration fields support constrained text, number, select, secret, and credential-file inputs. Field names must remain within the generic contract. Activation validates enabled saved connections against the new schema before switching versions.

## Register another Source

Set `VODLOFT_SOURCE_REGISTRY` to an operator-owned JSON file:

```json
{
  "sources": {
    "example": {
      "module": "example_source.worker",
      "package": "example-source"
    }
  }
}
```

The registry adds trusted adapter entry points; it does not install arbitrary packages from a URL. Supply a verified wheelhouse and activate it. The generic discovery, accounts, Domain support, preview, acquisition, and management UI discover its manifest without core code changes.

Production uses `VODLOFT_REQUIRE_ISOLATED_SOURCES=1`. An unavailable adapter does not hide another healthy Source.

## Build the built-in wheelhouses

Use the locked workspace and build tools:

```sh
uv sync --frozen
uv run --frozen python tools/build_source_bundles.py dist/source-bundles
```

For an independent extractor refresh, first update and lock the selected Source dependency, then give the wheelhouse a new immutable release identity:

```sh
uv run --frozen python tools/build_source_bundles.py dist/source-bundles \
  --source yt-dlp --release-version 1.0.0+extractor.20260819 --channel stable
```

The builder creates adapter/contract/helper wheels, downloads dependency wheels using locked hashes, and writes `release.json` with the adapter version, release version, channel, protocol/schema versions, Python minor compatibility, package inventory, upstream versions, and SHA-256 wheel digests. It refuses to overwrite an existing release directory.

Third-party publishers can use `create_manifest` in `tools/create_source_bundle_manifests.py` after preparing their complete wheelhouse. Native wheels must match the target platform and Python version. Helper lookup prefers the pinned Source runtime's `native/bin`, then its wheel-installed `bin` entry points, then the host's `PATH`. Manifest probes, helper-version checks, health checks, and real operations all use this same environment. Host executables remain available as a fallback; a Source can supply its own helper version independently of the core application. Wheel console scripts are relocated when a runtime is atomically published.

To bundle an independent native helper, place a regular executable file at `native/bin/<helper-name>` **before** creating the release manifest. The manifest builder records its SHA-256 digest under `native_executables`. Helper names contain letters, numbers, underscores, or hyphens; symlinks and undeclared files are rejected. Supply executables compatible with the target platform and any required libraries, for example a self-contained FFmpeg build. The installer verifies the exact helper inventory, copies it into the runtime, sets executable permissions, and runs the declared helper/health checks before activation. Do not modify an installed runtime; publish a new release version instead.

## Mounted installation

Copy a trusted immutable wheelhouse to:

```text
/config/source-bundles/<source-id>/<release-version>/
  release.json
  *.whl
  native/bin/<helper-name>  # optional digest-pinned helpers
```

Use **Management → Check Source bundles**. Automatic policy activates the newest eligible stable/beta release, respecting a pin. Manual activation and rollback select installed versions. A failed digest, install, health, protocol/schema, interpreter, helper, or saved-configuration check retains the previous active runtime.

The runtime verifies exact wheel and native-helper membership as well as digests, installs without package-index access, probes the adapter, and atomically publishes the runtime. Native helper digests are checked again during activation and rollback. Digest checks do not authenticate an untrusted mounted publisher: the mount and registry must be controlled by the operator.

Runtime state is persisted under `VODLOFT_SOURCE_RUNTIME_ROOT`, normally `/config/source-runtimes`; bundles use `VODLOFT_SOURCE_BUNDLE_DIR`, normally `/config/source-bundles`.

For a Source requiring another Python version, set `VODLOFT_SOURCE_PYTHONS` to a JSON **file path**. The file maps Source IDs to existing absolute interpreter paths, for example:

```json
{"example": "/opt/python3.14/bin/python3.14"}
```

## Sign an HTTPS release catalogue

Generate an Ed25519 private key outside the web root, for example with OpenSSL:

```sh
openssl genpkey -algorithm ED25519 -out /secure/source-signing.pem
chmod 600 /secure/source-signing.pem
uv run --frozen python tools/publish_source_catalogue.py \
  dist/source-bundles/yt-dlp/1.0.0+extractor.20260819 \
  --url-base https://releases.example.com/yt-dlp/1.0.0+extractor.20260819/ \
  --private-key-file /secure/source-signing.pem \
  --output dist/yt-dlp-catalogue.json
```

The command verifies local wheel and native-helper digests and emits a signed catalogue plus the public trust key. It does not upload files. Publish the wheels at the specified HTTPS base, optional executables under its `native/bin/` directory, and the catalogue at an HTTPS URL. Use `--existing` when appending a release; the prior catalogue's signature is checked.

Set `VODLOFT_SOURCE_RELEASE_CATALOGS` to a JSON **file path** whose contents are:

```json
{
  "yt-dlp": {
    "url": "https://releases.example.com/yt-dlp-catalogue.json",
    "public_key": "<base64-encoded raw Ed25519 public key>"
  }
}
```

Catalogue HTTPS requests reject private addresses and embedded credentials, pin the resolved public address, limit redirects and response sizes, verify the signature, and then verify each downloaded wheel and native executable's digest. No public publisher or trust key is configured automatically. Operators explicitly choose their publishers.

## Jobs, playback, and trust

An acquisition freezes its command, runtime version, Source/account reference, profile policy, and output specification when queued. Upstream playback similarly retains its selected runtime and representation. Bundled native helpers follow this same pinned runtime. Installing/activating a newer Source affects new operations; old environments remain available while pinned work drains and for rollback.

Private credentials, upstream signed URLs, and Source diagnostics must not be emitted in public responses or logs. Built-in Python network guards are defense in depth, not an operating-system sandbox. Apply deployment egress restrictions if native-helper network access must be constrained.
