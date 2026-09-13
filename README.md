# VodLoft

VodLoft is a self-hosted video-on-demand library and downloader built around [yt-dlp](https://github.com/yt-dlp/yt-dlp). Its architecture deliberately follows WireLoft so provider-independent code can converge into shared packages.

The initial foundation is based on WireLoft `develop` commit `fd13eda43a9f74f447b26bd777b572a15e654e4a` (the current develop snapshot inspected when VodLoft was created). DailyWire-specific integration boundaries are replaced by the `ytdlp-client` package; the rest keeps the same package-oriented FastAPI/SQLAlchemy/React shape.

## Domain model

- **Collections** are either **channels** or **playlists**. A collection URL is handed to yt-dlp for discovery. VodLoft only normalizes and persists the returned metadata.
- **Videos** can belong to any number of collections, or be added individually. Standalone video downloads are the VodLoft equivalent of WireLoft movie downloads.
- **Local media profiles** define where files are written.
- **Download profiles** define yt-dlp format selection and post-processing.
- **Stream profiles** define a muxed format selector used to resolve a temporary direct media URL.

There is intentionally no YouTube scraper in VodLoft. YouTube and every other supported site are handled by yt-dlp extractors.

## Packages

- `server/backend`: FastAPI API, Pydantic API models, SQLAlchemy models and Alembic.
- `server/controller`: orchestration workers, analogous to WireLoft's controller.
- `server/config`: YAML configuration.
- `server/ytdlp_client`: the only package that imports `yt_dlp`.
- `server/task_manager`: provider-independent background task execution.
- `server/media_profiles`: provider-independent profile enums/defaults intended to become a shared WireLoft/VodLoft package.
- `ui`: React + TypeScript + Zod frontend.

`config`, `task-manager`, and the media-profile primitives are deliberately provider-independent candidates for extraction into packages shared by WireLoft and VodLoft. They should move to a common source only once both applications consume the same interfaces and tests, so one application cannot silently drift from the other.

## Development

```bash
cp config/config.example.yml config/config.yml
uv sync
uv run backend-api db upgrade head
uv run backend-api serve --host 0.0.0.0 --port 8000

cd ui
npm install
npm run dev
```

FFmpeg should be available on the backend host/container for yt-dlp merging and post-processing.

## Configuration

`yt_dlp.options` is an advanced pass-through mapping merged into every `YoutubeDL` invocation. This supports cookies, extractor args, sleep/rate-limit settings and future yt-dlp options without adding website-specific code to VodLoft.
