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

Persist the entire `/config` directory. It contains VODLoft's database, configuration, secret-key material, and Daily Wire authentication state.

If `/config` is lost, VODLoft should be treated as a new installation.

### `/downloads` — your media library

The supplied Compose file maps `./downloads` on the host to `/downloads` in the container. Set **Download root** to `/downloads` when using this layout.

Local Media Profiles use paths beginning with `/downloads/`. VODLoft resolves that virtual prefix from the configured Download root. See [[Local-Media-Profiles]] and [[Settings#downloads]].

You can point Plex, Jellyfin, Audiobookshelf, or another media application at the appropriate folders inside the host's download directory.

VODLoft uses temporary download mode by default. Its **Temporary download folder** defaults to container-local storage so remuxing and metadata processing stay off network media mounts. You can point it at another suitable local disk or mount if needed.

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

For a normal Compose installation:

```bash
docker compose pull
docker compose up -d
```

VODLoft applies database migrations when the container starts. Back up `/config` before important upgrades. See [[Backups-and-Upgrades]].