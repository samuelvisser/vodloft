# VodLoft

VodLoft is a self-hosted video-on-demand library and downloader built around [yt-dlp](https://github.com/yt-dlp/yt-dlp). Its architecture deliberately follows WireLoft so provider-independent code can converge into shared packages without carrying DailyWire-specific assumptions into VodLoft.

The foundation is based on WireLoft `develop` commit `fd13eda43a9f74f447b26bd777b572a15e654e4a`. Provider-specific integration is replaced by `ytdlp-client`; library, profile, task, settings, persistence and frontend responsibilities retain the same package-oriented FastAPI/SQLAlchemy/React shape wherever that remains provider-neutral.

## Domain mapping

| WireLoft | VodLoft |
| --- | --- |
| Show | Collection |
| Series / Podcast | Channel / Playlist |
| Episode | Video in a collection |
| Movie | Standalone video |
| DailyWire API/downloader | yt-dlp |
| Local media profile | Local media profile |
| Download profile | Collection-scoped download profile |
| Stream profile | Collection-scoped stream profile |
| Media download | Media download artifact |

A canonical video can belong to multiple collections. Adding the same source as an individual video marks it as standalone without duplicating the video record.

## yt-dlp boundary

`server/ytdlp_client` is the only package that imports `yt_dlp`. VodLoft delegates extraction, site support, format selection, manifests, downloads and post-processing to yt-dlp and only consumes normalized models.

Adding or inspecting a collection asks yt-dlp for minimal metadata only. Full channel/playlist membership discovery is performed by the durable `collection.sync` task worker. This keeps API requests small and ensures manual, scheduled and event-driven synchronization all follow the same execution path.

`yt_dlp.options` in `config.yml` is passed through to every `YoutubeDL` instance. It is the escape hatch for cookies, extractor arguments, rate limits, sleep settings and future site-specific requirements without teaching VodLoft about individual websites.

## Profiles

Local media profiles describe a local representation: output template, yt-dlp format selector and post-processing. They have either `collection` or `video` scope. Standalone-video profiles are video-only; collection profiles may be video or audio. Profiles can be created, edited and deleted through the frontend and API.

Output templates stay rooted below `/downloads/`. When a template would otherwise allow two videos with the same title to overwrite each other, VodLoft inserts the yt-dlp video ID before `%(ext)s`. A server-side preview endpoint shows the normalized template and an example output path.

Download profiles belong to one channel/playlist and reference a collection-scoped local media profile. Collection synchronization emits an event that plans missing artifacts for every enabled download profile.

Stream profiles also belong to one collection. They resolve a fresh muxed stream through yt-dlp, or can prefer an already-downloaded local artifact.

## Durable task system

`server/task_manager` follows WireLoft's durable automation structure rather than using an in-memory job list. Python decorators register task definitions and their triggers:

- `@task(...)` registers a worker and its allowed resource types, retry defaults and optional concurrency limit.
- `@on_event(...)` registers event-driven task triggers.
- `@on_cron(...)` and `@on_interval(...)` register persistent scheduler definitions.

The registry is synchronized to SQLAlchemy models on startup. `TaskDefinition`, `TaskSchedule`, `TaskRun` and `TaskOperation` rows provide a persistent task ledger that survives application restarts. Runs record progress, attempts, backoff, cancellation state, errors, results, runtime and source. Interrupted runs are recovered on startup and stalled progress is reconciled by a maintenance worker.

Core event flow:

1. adding a collection emits `collection.added`;
2. `collection.sync` discovers/updates its videos through yt-dlp;
3. synchronization emits `collection.synced`;
4. `collection.plan_downloads` queues missing media for enabled download profiles;
5. `video.download` runs through a concurrency-limited durable download lane.

Changing an enabled download profile emits `download_profile.changed`, which uses the same planning worker. Scheduled all-collection synchronization and file verification are registry-backed tasks rather than special controller loops.

Queued downloads can be prioritized. Priority is timestamp-based: the most recently prioritized queued item is selected when the next constrained download slot opens. Running work is never interrupted by prioritization.

## Downloads and verification

Every `(video, local media profile)` artifact has a persistent media-download row linked to its current task run. The Downloads page supports cancellation, prioritization, retrying failed/canceled/missing media, opening completed files and deleting inactive artifacts.

A scheduled verification worker checks downloaded files on disk and marks missing artifacts so they can be retried. Deletion is blocked while a worker still owns an artifact, preventing a downloader from racing a ledger/file removal.

## Settings, authentication and RSS

Application settings include the current Alembic revision and private RSS state. Operational configuration remains in `config.yml` and can be edited in the frontend, including worker/retry limits, scheduler intervals, download concurrency and arbitrary yt-dlp options. Settings that size worker pools or decorator-backed schedules take full effect after a restart; dynamic yt-dlp/retry settings are re-read after saving.

Administrator authentication is optional. When configured, the admin API is protected by a signed HTTP-only session cookie. RSS uses a separate rotatable token so feed readers do not need the administrator session.

VodLoft exposes tokenized RSS feeds for individual collections and recently downloaded media. Downloaded artifacts are attached as RSS enclosures through token-protected media URLs.

## Packages

- `server/backend`: FastAPI API, Pydantic API models, SQLAlchemy models and Alembic migrations.
- `server/controller`: thin orchestration compatibility layer and stream resolution.
- `server/config`: YAML configuration and persistence.
- `server/ytdlp_client`: thin yt-dlp integration boundary.
- `server/task_manager`: durable registry, scheduler, events, workers and task ledger.
- `server/media_profiles`: provider-independent profile/domain enums.
- `ui`: React + TypeScript + Zod frontend.

WireLoft's current provider-neutral candidates are not yet published as a separate shared package, so VodLoft does not pretend that sharing already exists. The boundaries are intentionally aligned so common task/config/profile code can be extracted once WireLoft's remaining DailyWire dependencies are separated.

## Docker

The runtime mirrors WireLoft's single-container layout: React is built in a Node stage; the Python runtime includes FastAPI, ffmpeg and Nginx; `/api` is reverse-proxied internally; `/config` and `/downloads` are persistent volumes.

```bash
docker compose up -d --build
```

VodLoft is exposed on `http://localhost:8081` by default, allowing it to run beside WireLoft on `8080`.

## Local development

```bash
cp config/config.yml.default config/config.yml
uv sync
uv run backend-api db upgrade head
uv run pytest
uv run backend-api serve --host 0.0.0.0 --port 8000

cd ui
npm install
npm run build
npm run dev
```

FFmpeg must be available for yt-dlp merging and post-processing.
