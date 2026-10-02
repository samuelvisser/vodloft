# VodLoft 1.0

VodLoft is a WireLoft-derived local web media manager. Its generic library has separately packaged yt-dlp and Daily Wire Sources; the FastAPI and React layers use a versioned Source contract, Domain-based profiles, durable acquisition jobs and downstream delivery records. This 1.0 release is an administrator-operated prototype.

## Baseline and migration

The implementation was built from WireLoft `develop` commit `7853ee7bdf1137111193932fe9da7e8243442bd5` (27 September 2026), retaining its application structure. The GitHub branch contains a snapshot of that derived tree because the available GitHub Actions token could not push WireLoft's workflow files/history. The former VodLoft main branch is preserved at `archive/pre-wireloft-rebuild-2026-09-27`.

Alembic migrations add the normalized library alongside inherited WireLoft tables. A background migration maps existing Shows, Episodes, Movies and shared Movie Extras into that library. It also copies available legacy files into VodLoft-owned playback paths while preserving the originals. Existing Daily Wire pages remain available during the transition.

## Run locally

Python 3.13, uv, Node.js and FFmpeg are required. From the repository root:

```sh
uv sync
npm install
uv run backend-api db upgrade
uv run backend-api run --host 127.0.0.1 --port 5001
```

In a second terminal run `npm run dev`. Open the Vite URL, sign in if an admin password is configured, and select **Web media library**. The Source subprocesses use the current Python interpreter in this development setup. The Docker image installs them into separate, digest-checked Python environments on first start.

For Docker deployment, set `WL_ADMIN_AUTH__PASSWORD` and run `docker compose up --build`. Configuration, database, Source runtimes, encrypted secrets and trusted update bundles persist under `/config`; media and feed enclosures persist under `/downloads`.

## Library workflow

1. Add a public URL or search a Source that advertises search, then review its normalized preview. Import is explicit. Domain, Source, account connection, canonical media identity, Collection membership and local artifacts are stored separately. If an item has multiple Source or account references, select the one to use; Collection Download Profiles retain that selection. Source history records changed upstream metadata and its runtime version so an administrator can restore an earlier snapshot without losing their own title or description edits.
2. Create a Local Media Profile for the item's Domain, choose video or MP3 audio, an output path template and optional delivery targets. A profile remains valid if the selected Source implementation changes.
3. Download a playable item directly, or create a Collection Download Profile with selected Local Media Profiles, a backfill rule, date/title filters and refresh interval. Newest-N backfill uses publication dates, falling back to Collection position for undated entries. Mixed-domain Collections report members without an applicable profile. Paged Source enumeration records an incomplete checkpoint when upstream scanning stops, and resumes it only with the same Source runtime and connection. Nested Collections can be explicitly expanded up to two levels and 20 children from the library view, with cycle detection and a bounded API limit of three levels and 25 children. Refresh an individual item separately to hydrate its details.
4. Watch or listen through the web player. A high-entropy playback session binds to a local artifact or a private upstream Stream Lease and pins its Source runtime. HLS manifests and child requests are proxied through opaque VodLoft URLs; upstream credentials never appear in the page. Progress appears on Home. Home, Discover, Library and Management are separate views of the web media workspace.
5. Create an audio or video Collection Stream Profile with optional publication-date and title filters. Its revocable feed publishes only compatible local renditions and preserves bytes behind each enclosure URL until the subscription is revoked; revocation removes its published copies.
6. Connect a Jellyfin, Plex or Audiobookshelf podcast library. VodLoft maps its visible file path to the server path, requests a scan after publication and records the server item identity when discovered. Verification searches a bounded set of result pages in the chosen library. Jellyfin receives an `.nfo` and optional artwork sidecar; Plex detects its scanner, agent and machine identity before choosing an NFO, personal-media or local-assets presentation; Audiobookshelf records the episode ID and supports an explicit, non-rewinding progress import.

Artifacts keep a Source/account/format representation key. Compatible Local Media Profiles can share one canonical artifact and have separate presentation copies. Direct downloads and Collection policies create independent demand records. Retention can release a presentation and eventually its canonical file when no demand remains, while preserving active local playback and published feed copies. Intentional removal suppresses automatic re-creation until resumed.

Collection Stream Profiles can admit live items. A local-only live policy needs a compatible enabled Download Profile. Admission persists through the upstream live-to-archive transition; web playback can use the upstream lease while a local archive is being obtained. Podcast feed enclosures continue to require a compatible local copy.

The Source manager accepts versioned wheelhouse bundles from `/config/source-bundles/<source-id>/<version>/`. It rejects undeclared wheels, verifies each digest, installs in an independent environment, checks protocol compatibility and health, then activates the newest eligible release according to the automatic update channel and pin. A previous runtime remains available for rollback. A queued acquisition freezes its Source command and profile specification, claims a database lease, and reports stages and bounded byte-transfer progress through TaskOperations. Source manifests declare constrained text, number, choice, secret and credential-file connection fields; secrets are stored as scoped encrypted references and passed only to the selected Source process. The yt-dlp Source accepts an optional Netscape `cookies.txt` file for sites requiring an account. The worker uses a temporary credential file in an operation scratch directory that the gateway removes even if the worker fails or is canceled. Trusted administrators control the mounted bundle directory; a digest in a manifest does not authenticate an untrusted publisher. An additional adapter can be registered by an operator-owned JSON file in `VODLOFT_SOURCE_REGISTRY`, for example `{"sources":{"example":{"module":"example_source.worker","package":"example-source"}}}`; it still requires a trusted installed package or verified wheelhouse.

## Prototype scope and integration notes

The inherited Daily Wire screens and task metadata calls use a Source-worker compatibility adapter. The inherited downloader and device authorization flow still operate through their WireLoft packages. The generic Download Profile supports declared audio/video format choices; language, subtitle, chapter and codec policy are not exposed as complete controls yet. Auth challenges are typed in the Source contract, but the initial Sources use their existing connection fields and Daily Wire device sign-in. Public-network guarding covers Python socket clients in bundled Sources; native helpers need a deployment egress policy. Upstream HLS is best-effort if signed child URLs expire during a long session; the player can start a new session.

Media-server matching uses the chosen library, mapped paths and bounded scans. The three integration flows have fixture coverage but were not exercised against live Plex, Jellyfin and Audiobookshelf instances in this workspace. Plex may need a compatible library scanner and local-asset setting; inspect the connection test before exporting. Audiobookshelf uses shared-folder podcast delivery and an explicit progress pull for the administrator. RSS-pull ownership and general bidirectional multiuser progress synchronization are not part of this prototype. Automatic Source installation accepts trusted, digest-checked mounted wheelhouse bundles; it does not fetch untrusted releases from the internet. Multiuser requests, quotas and role permissions are outside this single-administrator release.

## Verification

`uv run pytest -q tests/unit/test_vodloft_prototype.py tests/unit/test_vodloft_architecture.py` covers identity, mixed-domain scheduling, date and newest-N filters, account scoping, playback leases and opaque HLS children, immutable RSS enclosures, live admission, shared-artifact retention, cancellation, leases, safe Collection removal, bounded nested expansion, path finalization recovery, Source registration, snapshot repair, media-server discovery/mapping, credential files, download progress and bundle rejection. The targeted suite passes 52 tests. `npm run build`, `backend-api db history` and `backend-api background-migrations history` verify the frontend and migration chains. A fresh database was upgraded to the current head.

The full inherited WireLoft suite is not clean at this pinned baseline: two modules import migration files absent from the checkout; earlier baseline verification with those excluded reported 175 failures and 700 passes, including tests built for older WireLoft fields. Those failures are not represented as passing VodLoft acceptance tests.
