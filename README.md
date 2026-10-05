> [!IMPORTANT]  
> VodLoft is based on [WireLoft]([WireLoft](https://github.com/samuelvisser/wireloft)), which is a mature download manager for The Daily Wire. VodLoft's goal is to expand that same idea to
> any domain/ website it can. It will use both yt-dlp and other sources to accomplish this.
> Its still very early days and this project is NOT ready for usage yet. [WireLoft]([WireLoft](https://github.com/samuelvisser/wireloft)) 
> very much is though if you're interested


# VodLoft 0.1

VodLoft builds a local web-media library from WireLoft. It separates websites (**Domains**), independently installed acquisition adapters (**Sources**), canonical media, Collection membership, local renditions, and downstream media-server delivery.

The 0.1 prototype includes yt-dlp and The Daily Wire Sources; Videos, Movies, shared Movie Extras, and nested Collections; automatic collection acquisition; a browser player; portable podcast/video RSS feeds; local accounts and approval requests; and Plex, Jellyfin, and Audiobookshelf integrations.

## Start with Docker

Clone this branch and run from its root:

```sh
git clone --branch codex/vodloft-wireloft-prototype https://github.com/samuelvisser/VodLoft.git
cd VodLoft
docker compose up --build -d
```

Open **http://localhost:8080** and complete the welcome screen. Set `WL_ADMIN_AUTH__PASSWORD` in the Compose environment before sharing the server. The administrator signs in as `admin`. Without a configured administrator password, the installation operates in local, unrestricted administrator mode.

Compose persists configuration, SQLite, secrets, Source bundles, and Source runtimes in `./config`, and media in `./downloads`. The image builds the production UI, applies database migrations, and installs both bundled Sources in separate Python environments. FFmpeg is included. No paid Font Awesome credentials are needed.

## Use the library

1. In **Discover**, paste a public media, channel, show, or playlist URL. Select a Source/account when more than one can handle it. Sources with search expose search previews. Review the result and import it explicitly.
2. In **Management**, create a **Local Media Profile** for the Domain. Choose applicable media types, video/audio quality, languages, fallback behavior, subtitles, container, codecs, chapters, artwork, metadata, output template, and delivery targets. Initial profiles are supplied for YouTube and The Daily Wire.
3. Download individual items or attach a **Collection Download Profile**. Choose Local Media Profiles, a Source/account reference, backfill, groups/roles, future-group inclusion, date/title filters, refresh interval, and retention. Partial upstream scans preserve known members. Nested Collections expand only through bounded explicit expansion.
4. Use **Library** for item details, metadata edits, Source history, Movie Extras, profiles, local playback, and upstream playback where supported. The player supports queues, resume, speed, chapters, and subtitle tracks. **Home** shows continue-watching, recent items, activity, and acquisition/delivery issues.
5. Attach a **Collection Stream Profile** for an audio or video feed. Choose portable local renditions or have VodLoft prepare them through the normal acquisition queue. A subscription publishes stable enclosure bytes behind a revocable URL; changing an upstream item or local rendition does not change already published bytes. Feed URLs support HEAD and byte ranges.
6. Add a media-server target, test it, and select it on a Local Media Profile. VodLoft publishes server-compatible files and metadata, requests scanning, and records actual downstream item availability. Audiobookshelf supports shared-folder delivery or RSS-pull delivery, explicit local-to-remote user mapping, and a progress import that never rewinds local progress.
7. Create local **member** or **manager** accounts, grant Source connections and server targets, and choose subscription permission, request quota, and automatic approval. Members request acquisitions; managers can approve/reject requests and manage library metadata. Local accounts, upstream accounts, and media-server identities remain separate.

A shared Movie Extra can belong to multiple Movies and have a different upstream role under each parent. Explicit parent/type edits survive Source refreshes.

To link another Source to an existing item, resolve its URL, select the library identity, and explicitly confirm the same edit, language, and edition. The selector includes Collection members and Movie Extras. Linking preserves metadata and local files; acquisition uses the selected reference's formats and capabilities. Collections keep each Source's occurrences and apply their selected Source's groups, ordering, and policies.

## Source installation and updates

Management shows installed adapter/upstream versions, connection schemas, runtime history, automatic-update policy, stable/beta channels, pins, manual checks, and rollback. Accounts use the fields declared by each Source, including secret and credential-file fields or interactive authentication challenges. Secrets remain scoped to the selected connection.

Mounted wheelhouses and optional native executables are verified and installed independently. Signed HTTPS release catalogues can be configured with an operator-trusted Ed25519 public key. Release identity includes dependency/artifact digests, compatible Python, configuration schema, Domain catalogue, and helper requirements. A failed install, protocol/schema mismatch, health check, or incompatible saved configuration leaves the previous runtime active. Queued/running acquisitions and upstream playback sessions retain the runtime and bundled helpers they started with.

See [Source authoring and releases](docs/SOURCE_AUTHORING.md) for third-party registration, wheelhouse building, signing, interpreter selection, and catalogue configuration. Adding a registered third Source does not require core or frontend changes.

## Upgrade from WireLoft

The implementation preserves WireLoft Git ancestry at commit `7853ee7bdf1137111193932fe9da7e8243442bd5`. The former VodLoft code is retained on `archive/pre-wireloft-rebuild-2026-09-27`; the original WireLoft baseline is retained on `archive/wireloft-baseline-7853ee7b`.

Back up the database, configuration, secrets, and media first. Point `WL_DATABASE_PATH` to the existing WireLoft database filename and retain its existing media mount/path. The Docker entrypoint performs schema migrations; background migrations then import Shows, Episodes, Movies, shared Extras, account references, profiles, memberships, feed policies, live admissions, and usable files. Original files remain available while owned playback copies are prepared. Scheduled work waits for background migrations.

See [Backups and upgrades](docs/wiki/Backups-and-Upgrades.md). Do not start two application instances against the same SQLite/media directories.

## Development

Use Python 3.13, uv, Node.js 22, and FFmpeg. From the repository root:

```sh
uv sync --frozen
npm install
uv run backend-api db upgrade
uv run backend-api run --host 127.0.0.1 --port 5001
```

In a second terminal, run `npm run dev` and open the Vite URL. Development Sources can use the workspace interpreter; production Docker requires isolated installed runtimes.

```sh
uv run --frozen pytest tests/unit/test_vodloft_architecture.py tests/unit/test_vodloft_prototype.py tests/unit/test_vodloft_upgrade.py -q
npm run build
uv run backend-api db history
uv run backend-api background-migrations history
```

## Verification and operating limits

[The acceptance record](docs/DESIGN_ACCEPTANCE.md) maps the design's acceptance scenarios and feature areas to code and reproducible checks. The acceptance workflow is **manual only**; pushing this implementation does not launch it. It is available for the follow-up regression suite, dependency check, production UI build, independent Source builds, and production-container HTTP/media-processing checks. The final implementation edits were reviewed as code; further tests and GitHub Actions were deferred at the user's request.

Plex, Jellyfin, and Audiobookshelf have adapter and lifecycle fixture coverage; a real deployment still needs the operator's server credentials, reachable mounts, and compatible server-library settings. Provider access depends on supported public URLs and the upstream account's entitlement. The bundled adapters guard Python network access; deployment-level egress controls are needed to constrain native helpers. A Source process is not an operating-system sandbox.

The inherited WireLoft test suite contains baseline failures and references to removed migration files. It is separate from the VodLoft acceptance suite and is not reported as passing. Interactive visual verification was blocked by this workspace's browser restrictions; production asset/build and HTTP checks are recorded separately.

User guides start at [the wiki home](docs/wiki/Home.md).
