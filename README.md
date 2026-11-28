<p align="center">
  <picture>
    <source
      media="(prefers-color-scheme: dark)"
      srcset="docs/logos/logo-wide-vodloft-white.png"
    >
    <source
      media="(prefers-color-scheme: light)"
      srcset="docs/logos/logo-wide-vodloft-black.png"
    >
    <img
      src="docs/logos/logo-wide-vodloft-black.png"
      alt="VODLoft Logo"
      width="450"
    >
  </picture>
</p>

<h2 align="center">Highly polished self-hosted media manager and RSS generator for YouTube and well over a thousand other sites</h2>


<p align="center">
  <picture>
    <source
      media="(prefers-color-scheme: dark)"
      srcset="docs/assets/screenshots/library-dark.png"
    >
    <source
      media="(prefers-color-scheme: light)"
      srcset="docs/assets/screenshots/library-light.png"
    >
    <img
      src="docs/assets/screenshots/library-light.png"
      alt="The VODLoft Library"
      width="700"
    >
  </picture>
</p>

<p align="center">
  <picture>
    <source
      media="(prefers-color-scheme: dark)"
      srcset="docs/assets/screenshots/collection-episode-dark.png"
    >
    <source
      media="(prefers-color-scheme: light)"
      srcset="docs/assets/screenshots/collection-episode-light.png"
    >
    <img
      src="docs/assets/screenshots/collection-episode-light.png"
      alt="A collection and one of its episodes in VODLoft"
      width="700"
    >
  </picture>
</p>

## What it does

VODLoft is an easy-to-use, highly polished self-hosted app that brings your favorite web content home. Tell it which
YouTube channels, playlists, podcasts or single videos you want, and it keeps them in a tidy library on your own
server: it finds new episodes as they come out, downloads them in the format you choose, names and files them exactly
the way you like, adds metadata and artwork for your media server, and can publish private RSS feeds for your podcast
app.

It is built for self-hosting nerds who want to keep the things they watch and listen to, without being tied to a
website or an app. VODLoft works with YouTube and [well over a thousand other sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md)
through [yt-dlp](https://github.com/yt-dlp/yt-dlp), plus a best-effort mode for almost any other page with a video on it.
Adding something is as simple as pasting a link: VODLoft shows you a preview first, and nothing is added until you say so.

VODLoft is highly customizable to fit your exact needs. Keep every episode of a channel as audio while keeping only the
latest five as 1080p video, and listen to both through one feed. Download everything, only the last month, only
certain seasons, or nothing at all and just keep an eye on what comes out. Whatever you want.

Despite everything it offers, VODLoft is designed to stay easy to install and use: launch the Docker container, open
the Web UI, and everything will explain itself. My philosophy with this software is to allow basically any
configuration you can think of, but help you along with advisory messages where your setup could be better, usually
with a button to apply the fix right away. This keeps you in control without leaving you in the dark.

VODLoft does not play media itself; it downloads, organizes and streams it for you. For downloaded files, use a
self-hosted media server such as Plex or Jellyfin for video, or Audiobookshelf for podcasts and audio. For RSS, add the
VODLoft feed to your favorite podcast app.

This project was inspired by [Pinchflat](https://github.com/kieraneglin/pinchflat), an awesome project that
automatically downloads videos from YouTube channels and playlists. VODLoft takes that idea further, to many more
sites, and can import an existing Pinchflat installation for you.


## Features

- Fully featured, easy-to-use Web UI for navigation and configuration, on your desktop as well as your phone.
- Add channels, playlists and podcasts as collections, and single videos, from YouTube and well over a thousand other sites.
- Search YouTube right from VODLoft, or paste any link to see a preview before you add it.
- Create multiple media profiles for the same collection — for example, automatically maintain separate video and audio downloads.
- Download in audio, 720p, 1080p or 4K, with subtitles and SponsorBlock where the site offers them.
- Organize your library exactly how you want with configurable naming, directory structures, and powerful Jinja templates.
- Automatically embed metadata and artwork, generate NFO files, and download collection artwork for media servers such as Jellyfin and Plex.
- Create private audio or video RSS feeds for your collections and use them in your favorite podcast app.
- Automatically discover, download, refresh, and clean up media in the background.
- Configure automatic retention rules to remove older content from your server.
- Adopt files you already have, or import an existing Pinchflat installation, so nothing is downloaded twice.
- Grab a single file from a link with Quick download, without adding anything to your library.
- Share VODLoft with your household through user accounts.
- Keeps yt-dlp up to date on its own, because sites change often.

### Built-in support for The Daily Wire and NPO Start

On top of yt-dlp, VODLoft has its own built-in support for [The Daily Wire](https://www.dailywire.com) and
[NPO Start](https://npo.nl/start), for extra stability on those sites. For The Daily Wire this includes member content
through your own subscription, movies with their extras, smart handling of live episodes, and RSS feeds that stream
episodes without downloading them first. See [Sources](https://github.com/samuelvisser/vodloft/wiki/Sources) for what
each one can do.

### Good to know

- VODLoft never bypasses DRM. Media protected by DRM is still listed, with a **DRM** badge, so you can see what a
  collection contains, but it is never downloaded.
- RSS feeds for YouTube and other yt-dlp sites serve downloaded files, because their stream links expire after a while.


## Running with Docker

The best way to run VODLoft is using its Docker container. Everything is managed for you automatically within the container.


### Quick start: use the published image

Run the following to get started immediately:

```bash
mkdir vodloft && cd vodloft
curl -O https://raw.githubusercontent.com/samuelvisser/vodloft/main/.docker/docker-compose.yml
docker compose up -d
```

Then open http://localhost:5274.

See **Volumes** and **Useful environment variables** below for persistence and configuration options. Edit the Compose file in place if you want to change anything beyond the defaults.


### Or create the Compose file yourself

```yaml
services:
  vodloft:
    image: ghcr.io/samuelvisser/vodloft:latest
    restart: unless-stopped
    ports:
      - "5274:80"
    volumes:
      - ./config:/config
      - ./downloads:/downloads
    environment:
      # Set the timezone to your local timezone
      - TZ=UTC
```


### Setup

#### Volumes

* `/config` -- App configuration (`config.yml`), the SQLite database (unless you use PostgreSQL), session secret key, your Source sign-ins, and yt-dlp's updates and cookies file. Persist this directory so your settings, collections, and sign-ins survive container restarts and upgrades.
* `/downloads` -- Downloaded episodes, videos and movies.

#### Useful environment variables

* `TZ` -- Container timezone. Defaults to `UTC`.
* `VL_ADMIN_AUTH__PASSWORD` -- Set this to require a password to access the Web UI. Leave it unset for open access on your local network. Always set this when exposing VODLoft through a reverse proxy.
* `VL_DATABASE_URL` -- Keep the database in PostgreSQL instead of SQLite, for example `postgresql+psycopg://vodloft:password@postgres/vodloft`. [`.docker/docker-compose.postgresql.yml`](.docker/docker-compose.postgresql.yml) sets this up with a PostgreSQL container. An empty PostgreSQL database is filled from the existing SQLite database on its first start. See [Installation](https://github.com/samuelvisser/vodloft/wiki/Installation#choose-a-database).
* `API_URL` -- Override the API base URL given to the Web UI. This defaults to the relative `/api`, which works out of the box regardless of which host port you map. The Web UI adds the API version itself (`/api/v1/...`), so leave it out here.

Literally every setting VODLoft provides can be managed by environment variables, too. However, I generally do not advise
using environment variables for anything but the above examples. Any setting configured by environment variable cannot be changed in the VODLoft UI.

See the [Settings documentation](https://github.com/samuelvisser/vodloft/wiki/Settings) for all available settings, including their `config.yml` keys, environment variables, defaults, and explanations.
The [wiki](https://github.com/samuelvisser/vodloft/wiki) covers everything else, from your first run to backups and upgrades.


## Special thanks

Everything VODLoft downloads from YouTube and most other sites goes through [yt-dlp](https://github.com/yt-dlp/yt-dlp),
which does the hard work of keeping up with all those sites.

VODLoft grew out of [WireLoft](https://github.com/samuelvisser/wireloft), an earlier project of mine for The Daily Wire,
and can import a WireLoft installation. The open-source [DailyWirePodcastProxy](https://github.com/fpnewton/DailyWirePodcastProxy)
project has helped tremendously in figuring out how The Daily Wire API works. Definitely check it out if you're interested!


## Disclaimer
This project is not affiliated with or endorsed by YouTube, The Daily Wire, NPO or any other site it can download from.
Only download media you are allowed to, only connect accounts you are authorized to use, and comply with all
applicable terms and laws.
