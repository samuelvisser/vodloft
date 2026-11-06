# Installation

Docker is the recommended way to run VODLoft. The published container includes the backend, web interface, FFmpeg, and the web server used to expose them through one HTTP port.

## Quick start

```bash
mkdir vodloft && cd vodloft
curl -O https://raw.githubusercontent.com/samuelvisser/vodloft/main/.docker/docker-compose.yml
docker compose up -d
```

Open:

```text
http://localhost:5274
```

The supplied Compose file is equivalent to:

```yaml
services:
  vodloft:
    image: ghcr.io/samuelvisser/vodloft:latest
    container_name: vodloft
    restart: unless-stopped
    ports:
      - "5274:80"
    volumes:
      - ./config:/config
      - ./downloads:/downloads
    environment:
      - TZ=UTC
      # - VL_ADMIN_AUTH__PASSWORD=change-me
```

After VODLoft opens, continue with [[First-Run-Setup]]. 

## Persistent storage

VODLoft keeps the application itself inside the container and stores persistent data in mounted directories. Recreating or upgrading the container is therefore safe as long as these mounts are preserved.

### `/config` — required

Persist the entire `/config` directory. It contains VODLoft's database, configuration, secret-key material, Daily Wire authentication state, and yt-dlp's updates and cookies file.

If `/config` is lost, VODLoft should be treated as a new installation.

### `/downloads` — your media library

The supplied Compose file maps `./downloads` on the host to `/downloads` in the container. Set **Download root** to `/downloads` when using this layout.

Local Media Profiles use paths beginning with `/downloads/`. VODLoft resolves that virtual prefix from the configured Download root. See [[Local-Media-Profiles]] and [[Settings#downloads]].

You can point Plex, Jellyfin, Audiobookshelf, or another media application at the appropriate folders inside the host's download directory.

VODLoft uses temporary download mode by default. Its **Temporary download folder** defaults to container-local storage so remuxing and metadata processing stay off network media mounts. You can point it at another suitable local disk or mount if needed.

## Choose a database

VODLoft keeps its database in a single SQLite file in `/config` (`vodloft.db`). That needs no setup. VODLoft can also use a PostgreSQL server instead. PostgreSQL copes better when a lot happens at once, such as many downloads running together or bulk actions on thousands of downloads.

To run VODLoft with PostgreSQL, use the PostgreSQL Compose file. It starts a PostgreSQL container next to VODLoft:

```bash
mkdir vodloft && cd vodloft
curl -o docker-compose.yml https://raw.githubusercontent.com/samuelvisser/vodloft/main/.docker/docker-compose.postgresql.yml
```

Before the first start, replace both `change-me` passwords in the file (`POSTGRES_PASSWORD` and the one inside `VL_DATABASE_URL`) with the same new password. Then run `docker compose up -d`. The database lives in `./postgres`, next to `./config`.

To use a PostgreSQL server you already run, set `VL_DATABASE_URL` (or `databaseUrl` in `config.yml`) to `postgresql+psycopg://USER:PASSWORD@HOST:5432/DATABASE`. The database must exist and be empty; VODLoft creates its tables itself.

### Move an existing installation to PostgreSQL

1. Back up `./config` (see [[Backups-and-Upgrades]]).
2. Add the `postgres` service and the `VL_DATABASE_URL` line from the PostgreSQL Compose file to your own Compose file. Keep your `./config` mount as it is.
3. Run `docker compose up -d`.

On its first start with the empty PostgreSQL database, VODLoft copies everything from `/config/vodloft.db` into it. It then renames that file to `vodloft.db.copied-to-postgresql`, so it is never copied twice and you keep it as a backup. If the copy fails, nothing is changed, PostgreSQL stays empty and the container log says why.

To go back to SQLite, remove `VL_DATABASE_URL` and rename the file back to `vodloft.db`. Changes made while VODLoft ran on PostgreSQL are not in that file.

## Set your timezone

Change `TZ` to your local [IANA](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List)
timezone, for example:

```yaml
environment:
  - TZ=Europe/Amsterdam
```

The timezone affects scheduled jobs and how VODLoft displays and interprets time-based behavior.

## Protect the web interface

On a trusted LAN you can run VODLoft without its own administrator password. If other people can reach the service, or if you expose it through a reverse proxy, configure one:

```yaml
environment:
  - VL_ADMIN_AUTH__PASSWORD=choose-a-long-unique-password
```

Restart the container after changing deployment environment variables:

```bash
docker compose up -d
```

This password protects the VODLoft web interface. Private RSS feeds use their own secret URLs instead. See [[Security-and-Remote-Access]].

## Configuration

For normal use, configure VODLoft from **Settings** in the web interface. Changes are saved to the persistent `config.yml` under `/config`.

Environment variables can override settings when you need deployment-level control. If a setting is controlled by an environment variable, the Settings page shows that override and explains the UI cannot overwrite it.

See [[Settings]] for the full reference.

## Reverse proxy and remote access

If VODLoft will be available outside your trusted local network:

- use HTTPS;
- enable the VODLoft administrator password;
- make sure the hostname stored in RSS Stream Profiles is reachable by your podcast clients;
- forward both the normal VODLoft application and `/feeds/rss/` paths;
- keep RSS feed URLs private, because the token in the URL is the feed credential.

A VPN or private overlay network is also a good option when you do not want to expose VODLoft publicly. See [[Security-and-Remote-Access]].

## Updating VODLoft

To upgrade to the newest version:

```bash
docker compose pull
docker compose up -d
```

Each [VODLoft release](https://github.com/samuelvisser/vodloft/releases) also lists the commands to install exactly that version.

VODLoft applies database migrations when the container starts. Back up `/config` before important upgrades. See [[Backups-and-Upgrades]].