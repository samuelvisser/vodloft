# VodLoft

VodLoft is a self-hosted video-on-demand library and downloader built around [yt-dlp](https://github.com/yt-dlp/yt-dlp). Its architecture deliberately follows WireLoft so provider-independent code can converge into shared packages.

The initial foundation is based on WireLoft `develop` commit `fd13eda43a9f74f447b26bd777b572a15e654e4a`, the current develop snapshot inspected when VodLoft was created. DailyWire-specific integration boundaries are replaced by `ytdlp-client`; provider-independent responsibilities retain the same package-oriented FastAPI/SQLAlchemy/React shape.

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

`server/ytdlp_client` is the only package that imports `yt_dlp`. VodLoft calls the supported Python embedding API (`YoutubeDL.extract_info`) for inspection/discovery and download execution. Format selection, extractor behavior, manifests, site support and post-processing remain yt-dlp responsibilities.

`yt_dlp.options` in `config.yml` is passed through to every `YoutubeDL` instance. This is the escape hatch for cookies, extractor arguments, rate limiting, sleep settings and future site-specific requirements without teaching VodLoft about individual websites.

## Profiles

Local media profiles describe a local representation: output template, yt-dlp format selector and post-processing. They have either `collection` or `video` scope. Standalone-video profiles are video-only, matching WireLoft's movie behavior; collection profiles may be video or audio.

Download profiles belong to one channel/playlist and reference a collection-scoped local media profile. Every collection sync discovers metadata through yt-dlp and queues any missing `(video, local media profile)` artifacts for enabled profiles.

Stream profiles also belong to one collection. They resolve a fresh muxed stream through yt-dlp, or can prefer an already-downloaded local artifact.

## Packages

- `server/backend`: FastAPI API, Pydantic API models, SQLAlchemy models and Alembic.
- `server/controller`: orchestration workers.
- `server/config`: YAML configuration.
- `server/ytdlp_client`: thin yt-dlp integration boundary.
- `server/task_manager`: provider-independent background task execution.
- `server/media_profiles`: provider-independent profile/domain enums.
- `ui`: React + TypeScript + Zod frontend.

WireLoft's current `config` and `task-manager` packages still import DailyWire-specific packages, so VodLoft does not depend on them directly. `media_profiles` and the provider-neutral task/config interfaces here are intentionally isolated so they can be extracted to a shared Loft package after WireLoft is decoupled from its DailyWire dependencies.

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
uv run backend-api serve --host 0.0.0.0 --port 8000

cd ui
npm install
npm run dev
```

FFmpeg must be available for yt-dlp merging and post-processing.
