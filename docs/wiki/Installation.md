# Installation

Use Docker Compose from the VodLoft repository:

```sh
docker compose up --build -d
```

Open http://localhost:8080. The image includes the production web interface, backend, FFmpeg, and separately installed yt-dlp and The Daily Wire Sources. The build needs internet access to fetch locked dependencies.

The default Compose file mounts `./config` for configuration, database, Source runtimes, bundles, and secrets; `./downloads` stores media and feed files. Keep both directories when recreating the container. The default media root inside the container is `/downloads`.

Set `WL_ADMIN_AUTH__PASSWORD` in the Compose environment before allowing other people to reach the installation. Sign in with username `admin`. Change the published port or timezone in Compose if needed.

A reverse proxy can serve VodLoft over HTTPS. Proxy both `/api/` and `/feeds/`, preserve the public Host and scheme, and support byte-range media requests. See [Security and remote access](Security-and-Remote-Access.md).

For development commands and requirements, see the repository README.
