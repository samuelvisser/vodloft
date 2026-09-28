# VodLoft

VodLoft is a WireLoft-derived local web media manager. Its generic library has separately packaged yt-dlp and Daily Wire Sources; the FastAPI and React layers use a versioned Source contract, Domain-based profiles, durable acquisition jobs and downstream delivery records.

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

1. Add a public URL and review the normalized Source preview. Import is explicit. Domain, Source, account connection, canonical media identity, Collection membership and local artifacts are stored separately.
2. Create a Local Media Profile for the item's Domain, choose video or MP3 audio, an output path template and optional delivery targets. A profile remains valid if the selected Source implementation changes.
3. Download a playable item directly, or create a Collection Download Profile with selected Local Media Profiles, a backfill rule, date/title filters and refresh interval. Mixed-domain Collections report members without an applicable profile. Paged Source enumeration records an incomplete checkpoint when upstream scanning stops.
4. Watch or listen through the authenticated web player. The playback URL binds to an immutable artifact for its session, and the administrator's resume position appears on Home.
5. Create an audio or video Collection Stream Profile and its revocable feed. The feed publishes only compatible local renditions and preserves bytes behind each enclosure URL.
6. Connect a Jellyfin, Plex or Audiobookshelf podcast library. VodLoft maps its visible file path to the server path, requests a scan after publication and records the server item identity when discovered. Jellyfin receives an `.nfo` sidecar; Plex scanner and agent details are exposed by the connection test.

The Source manager accepts versioned wheelhouse bundles from `/config/source-bundles/<source-id>/<version>/`. It rejects undeclared wheels, verifies each digest, installs in an independent environment, checks protocol compatibility and health, then activates the newest eligible release according to the automatic update channel and pin. A previous runtime remains available for rollback. A queued acquisition freezes its Source command and profile specification, claims a database lease, and reports stages through TaskOperations. Trusted administrators control the mounted bundle directory; a digest in a manifest does not authenticate an untrusted publisher. An additional adapter can be registered by an operator-owned JSON file in `VODLOFT_SOURCE_REGISTRY`, for example `{"sources":{"example":{"module":"example_source.worker","package":"example-source"}}}`; it still requires a trusted installed package or verified wheelhouse.

## Current limits

This is a working prototype with substantial parts of the architecture document implemented. The inherited Daily Wire-specific pages and background tasks still use their original WireLoft integration rather than the new Source gateway. The generic Source contract covers URL matching/resolution, bounded previews and paged Collection enumeration, downloads and Domain catalogues; it does not yet offer rich search, automatic nested Collection traversal, typed authentication challenges, a complete format/track model or upstream Stream Leases. Collection policies do not yet implement live continuity or retention-driven file removal. Media-server scans and path matching are implemented, but no real connected Plex, Jellyfin or Audiobookshelf instance was available to verify their API responses; server-side playback progress synchronization and deep links are not included. Native helper networking needs an operator egress policy in addition to the built-in Python socket guard. Multiuser requests, quotas and permissions remain outside this single-administrator prototype.

## Verification

`uv run pytest -q tests/unit/test_vodloft_prototype.py tests/unit/test_vodloft_architecture.py` covers identity, mixed-domain scheduling, date filters, multiple representations, feed immutability and format selection, account scoping, cancellation, leases, safe Collection removal, path finalization recovery, Source registration and bundle rejection. `npm run build`, `uv run backend-api db history` and `uv run backend-api background-migrations history` verify the frontend and migration chains. Backend and Vite smoke checks return HTTP 200 locally.

The full inherited WireLoft suite is not clean at this pinned baseline: two modules import migration files absent from the checkout; with those excluded it reports 175 failures and 700 passes, including tests built for older WireLoft fields. These failures are not represented as passing VodLoft acceptance tests.
