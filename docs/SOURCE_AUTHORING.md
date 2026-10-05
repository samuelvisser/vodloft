# Sources and independent releases

A Source is an operator-trusted adapter process. Core sends one JSON request on stdin and reads one JSON result on stdout. A fresh worker handles each operation. Normalized contracts live in `server/source_contracts`; adapters must not import backend database, configuration, HTTP models, or integration modules.

The built-in packages are `vodloft-source-ytdlp` and `vodloft-source-dailywire`. They share `vodloft-source-media` for acquisition/FFmpeg processing while remaining outside the core process. Source wheels and dependencies are installed in separate immutable environments; updating them does not replace core's dependencies.

## Contract

Implement `manifest` and the advertised operations. The manifest declares a stable Source ID, adapter version, protocol and metadata schema versions, upstream dependency versions, Python requirement, native helpers, capability flags, and a versioned configuration schema.

Current protocol/schema versions are both **1**. Supported contracts include:

- URL matching and resolution into Collection, Video, Movie, or Movie Extra snapshots.
- Bounded Collection pages with opaque cursors and completion status.
- Paginated Domain catalogues and optional Source-owned search/browse previews, categories and connection verification. A non-exhaustive catalogue does not forbid resolving another public Domain.
- Acquisition requests with Source/account identity, a representation policy, metadata, and a staging directory.
- Typed failure envelopes. Core exposes protocol-defined public messages rather than upstream exceptions containing secrets.
- Optional progress events on stderr as `{"event":{"stage":"downloading","percent":25}}`. Keep stdout exclusively for the operation result.
- Private renewable stream leases and Source-mediated HLS child fetching.
- Optional authentication start/poll/refresh operations. Public responses contain status/challenges; tokens and private state remain encrypted in the selected Source connection.

See the typed models in `server/source_contracts/src/source_contracts/__init__.py` and the built-in worker implementations. Do not advertise a capability the worker cannot fulfill.

The separately released `source-contracts` package is version **1.0.1**; the compatible protocol and metadata schema remain version **1**. Media responses use the `NormalizedSnapshot` discriminated union for Collections, Videos, Movies and Movie Extras. Collection entries can reference any of these types.

Keep omitted metadata distinct from an explicit `null` or empty list. Core stores only fields supplied in a snapshot, keeps upstream history separate from user overrides, and omits unset fields in public snapshot responses. A lightweight snapshot must not erase previously hydrated metadata. `enumeration_complete` defaults to **false**: a Source must explicitly declare exhaustive enumeration before missing members can be retired. A paginated Collection result likewise needs `complete=true` and no next cursor to prove completion. Honor the requested page limit and keep cursors opaque; repeated continuations and invalid provenance are rejected.

Capabilities narrow through **Source → Domain → Connection → Media item**. An omitted capability set inherits the broader declaration; an explicit empty set grants no operations. A `DomainDescriptor` supplies normalized canonical hostnames, Source-owned aliases, support status and optional capabilities. `SourceConnectionStatus` can narrow capabilities for an account and individual Domains. Core returns effective capabilities and explanations; neither core policy nor the frontend interprets provider-specific extension data.

Browse replies contain `SourceBrowseCategory` labels/IDs and normalized result previews. They are data, never executable UI components. An unsupported optional operation returns the typed `unsupported_operation` error. Configuration fields support constrained text, number, select, secret, and credential-file inputs. Field names must remain within the generic contract. Activation validates enabled saved connections against the new schema before switching versions.

## Public Source API

The standard routes and the product's `/api/vodloft/sources` aliases share the same typed handlers, authorization and transport. Reading a preview does not import media, create acquisition demand or modify the local media library. Import requires a separate reviewed confirmation at `POST /api/library/import` (also `/api/vodloft/import/confirm`). Discovery may cache Source-provided Domain declarations.

| Route | Purpose |
| --- | --- |
| `GET /api/sources` | Installed Sources, including unavailable runtimes, with manifest declarations when available. |
| `GET /api/source/{source}/manifest` | Version, capabilities and configuration schema. |
| `GET /api/source/{source}/domains` | Bounded Domain catalogue, with cursor and limit. |
| `POST /api/source/{source}/match` | Cheap URL assessment. |
| `POST /api/source/{source}/resolve` | URL preview; body supplies `url` and optional `connection_id`. |
| `POST /api/source/{source}/media` | Inspect an unimported `SourceMediaReference`, with optional `connection_id`. |
| `GET /api/source/{source}/media/{kind}/{reference_id}` | Inspect a stored VodLoft Source-reference handle without updating the library. |
| `GET /api/source/{source}/media/collections/{reference_id}/entries` | Preview Collection membership, with cursor and limit. |
| `POST /api/source/{source}/entries` | Preview membership for an unimported URL. |
| `GET /api/source/{source}/search` | Optional upstream search with explicit Source/account/Domain scope. |
| `POST /api/source/{source}/browse` | Optional Domain/category browsing. |
| `GET /api/source/{source}/capabilities` | Effective Source/Domain/account capability policy. |
| `POST /api/source/{source}/downloads` | Start durable acquisition of a library item/reference and selected profile. |
| `GET /api/source/{source}/downloads/{job_id}` | Download state and history; `/progress` uses the same state. |
| `POST /api/source/{source}/downloads/{job_id}/cancel` | Cancel actual Source work. |
| `POST /api/source/{source}/streams/resolve` | Owned opaque playback session; private Source leases remain in core. |

Authentication routes use the same generic challenge/status contract. The connection verification route is `POST /api/sources/connections/{connection_id}/capabilities`. Unsupported Source operations return a public typed error envelope alongside the normal form error message.

Discovery continuation tokens are encrypted and bound to operation, Source/runtime manifest, account revision, Domain/category/query and page limit. Changing credentials or settings invalidates the old scope; renewal of tokens for the same authorized account preserves it. Collection synchronization stores a durable checkpoint under the same runtime/account ownership rules and restarts a bounded scan after an incompatible change.

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
  --source yt-dlp --release-version 1.0.1+extractor.20260819 --channel stable
```

The builder creates adapter/contract/helper wheels, downloads dependency wheels using locked hashes, reads the installed adapter's manifest in a disposable environment, and writes `release.json` with the adapter version, release version, channel, protocol/schema versions, configuration-schema version, Domain-catalogue revision, native-helper requirements, Python minor compatibility, package inventory, upstream versions, and SHA-256 artifact digests. These declarations are checked again before runtime activation. It refuses to overwrite an existing release directory.

Third-party publishers can use `create_manifest` in `tools/create_source_bundle_manifests.py` after preparing their complete wheelhouse. Native wheels must match the target platform and Python version. Helper lookup prefers the pinned Source runtime's `native/bin`, then its wheel-installed `bin` entry points, then the host's `PATH`. Manifest probes, helper-version checks, health checks, and real operations all use this same environment. Host executables remain available as a fallback; a Source can supply its own helper version independently of the core application. Wheel console scripts are relocated when a runtime is atomically published.

To bundle an independent native helper, place a regular executable file at `native/bin/<helper-name>` **before** creating the release manifest. The manifest builder records its SHA-256 digest under `native_executables`. Helper names contain letters, numbers, underscores, or hyphens; symlinks and undeclared files are rejected. Supply executables compatible with the target platform and any required libraries, for example a self-contained FFmpeg build. The installer verifies the exact helper inventory, copies it into the runtime, sets executable permissions, and runs the declared helper/health checks before activation. Do not modify an installed runtime; publish a new release version instead.

The built-in builder accepts `--native-bin /path/to/helpers --source <source-id>` to copy such helpers into a new release before its manifest is generated. Third-party builders can pass their typed `SourceManifest` to `create_manifest` to record the same release declarations.

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
  dist/source-bundles/yt-dlp/1.0.1+extractor.20260819 \
  --url-base https://releases.example.com/yt-dlp/1.0.1+extractor.20260819/ \
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

An acquisition pins its Source command/runtime, selected reference and account scope when queued. At its first dispatch, core resolves the current applicable Local Media Profile into an immutable execution specification, records its revision, representation, metadata and output template, and retains it for running work and retries. Profile edits can affect work that has not started. Changing the selected account's credentials requires a new acquisition request instead of silently using a different account. Upstream playback similarly retains its selected runtime and representation. Bundled native helpers follow this same pinned runtime. Installing/activating a newer Source affects new operations; old environments remain available while pinned work drains and for rollback.

Private credentials, upstream signed URLs, and Source diagnostics must not be emitted in public responses or logs. Built-in Python network guards are defense in depth, not an operating-system sandbox. Apply deployment egress restrictions if native-helper network access must be constrained.
