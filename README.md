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

<h2 align="center">Self-hosted media downloader and RSS generator for Daily Wire, YouTube, NPO and more</h2>

> [!IMPORTANT]
> VODLoft is in early development and not ready for use yet. It is a fresh fork of
> [WireLoft](https://github.com/samuelvisser/wireloft), a mature download manager for The Daily Wire.
> Right now VODLoft behaves exactly like WireLoft. YouTube (through yt-dlp) and NPO.nl support are being
> added for the 0.1.0 beta. If you only need The Daily Wire, use WireLoft.

## What it does

VODLoft takes everything [WireLoft](https://github.com/samuelvisser/wireloft) does for The Daily Wire and extends it
to more websites. Each website is handled by a **Source**: The Daily Wire through its own API, YouTube and hundreds
of other sites through [yt-dlp](https://github.com/yt-dlp/yt-dlp), and NPO.nl through VODLoft's own NPO client.
Whatever the Source, you get the same profiles, file naming, metadata, artwork, NFO files and RSS feeds.

VODLoft is highly customizable to fit your exact needs. You can automatically download audio for every item in a show while downloading video only for full episodes, do it the other way around, or configure something entirely different.

This project was inspired by [Pinchflat](https://github.com/kieraneglin/pinchflat), an awesome project that allows you to automatically download videos from YouTube channels and playlists.

VODLoft is not meant to be used for consuming the content itself; it downloads, organizes, or streams it for you. For downloaded content, use a self-hosted media server such as Plex or Jellyfin for video, or Audiobookshelf for podcasts and audio. For RSS, use the VODLoft-generated RSS stream in your favorite podcast app and consume the content there.

## Features

- Fully featured, easy-to-use Web UI for navigation and configuration.
- Download series, podcasts, movies, and premium content using your The Daily Wire subscription.
- Create multiple media profiles for the same show — for example, automatically maintain separate video and audio downloads.
- Organize your library exactly how you want with configurable naming, directory structures, and powerful Jinja templates.
- Automatically embed metadata and artwork, generate NFO files, and download show assets for media servers such as Jellyfin and Plex.
- Intelligently handles live episodes, avoiding countdown footage and waiting for the proper published version when appropriate.
- Create private audio or video RSS feeds for your shows and use them in your favorite podcast app.
- Stream live episodes through RSS, with stable episode URLs that can seamlessly transition to locally downloaded media once available.
- Automatically discover, download, refresh, and clean up media in the background.
- Configure automatic retention rules to remove older content from your server.


## Running with Docker

The best way to run VODLoft is using its Docker container. Everything is managed for you automatically within the container.


### Quick start: use the published image

Run the following to get started immediately:

```bash
mkdir vodloft && cd vodloft
curl -O https://raw.githubusercontent.com/samuelvisser/vodloft/develop/.docker/docker-compose.yml
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

* `/config` -- App configuration (`config.yml`), the SQLite database, session secret key, and your Daily Wire login token. Persist this directory so your settings, shows, and login survive container restarts and upgrades.
* `/downloads` -- Downloaded episodes and movies.

#### Useful environment variables

* `TZ` -- Container timezone. Defaults to `UTC`.
* `VL_ADMIN_AUTH__PASSWORD` -- Set this to require a password to access the Web UI. Leave it unset for open access on your local network. Always set this when exposing VODLoft through a reverse proxy.
* `API_URL` -- Override the API base URL given to the Web UI. This defaults to the relative `/api`, which works out of the box regardless of which host port you map.

Literally every setting VODLoft provides can be managed by environment variables, too. However, I generally do not advise
using environment variables for anything but the above examples. Any setting configured by environment variable cannot be changed in the VODLoft UI.

See the [Settings documentation](https://github.com/samuelvisser/vodloft/wiki/Settings) for all available settings, including their `config.yml` keys, environment variables, defaults, and explanations.


## Special thanks

VODLoft is based on [WireLoft](https://github.com/samuelvisser/wireloft). The open-source [DailyWirePodcastProxy](https://github.com/fpnewton/DailyWirePodcastProxy) project has helped tremendously in figuring out how The Daily Wire API works. 
DailyWirePodcastProxy allows you to access premium versions of Daily Wire shows directly from your podcast app. Definitely check it out if you're interested!


## Disclaimer
This project is not affiliated with or endorsed by The Daily Wire. Only connect a Daily Wire account you are authorized to access,
and comply with all applicable terms and laws.