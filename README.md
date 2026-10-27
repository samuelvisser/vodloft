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
> VODLoft is in beta. Expect rough edges, and back up `/config` before upgrading.

## What it does

VODLoft is a self-hosted media manager for online video and podcasts. You tell it which shows, channels, playlists,
movies or single videos you want, and it keeps them in a tidy library on your own server: it finds new episodes as
they come out, downloads them in the format you choose, names and files them the way you like, adds metadata and
artwork for your media server, and can publish private RSS feeds for your podcast app.

VODLoft works with many websites. Each one is handled by a **Source**:

| Source | Sites | What you can add |
|---|---|---|
| **The Daily Wire** | dailywire.com | Shows, podcasts, movies and their extras. Sign in for member content. |
| **yt-dlp** | YouTube and [well over a thousand other sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md), plus a best-effort mode for any other page with a video | Channels and playlists as shows, and single videos. |
| **NPO Start** | npo.nl | Series and programmes, found by search or by link. No account needed. |

Whatever the Source, everything after that works the same way. To add something, paste a link: VODLoft finds the
Source that recognises it and shows a preview before anything is added. When more than one Source can handle a
site, such as npo.nl, you choose which one VODLoft asks first.

How media is downloaded and stored is set with three kinds of profiles:

- A **Local Media Profile** describes a file: audio or video, which quality, and where it goes, using a Jinja
  template for folders and file names.
- A **Download Profile** decides which episodes of a show are downloaded automatically, such as every episode,
  the latest ten, the last month, or certain seasons.
- An **RSS Stream Profile** publishes a show as a private podcast or video feed.

A show can have several of each. For example, you can keep every episode of a show as audio while keeping only
the latest five as 1080p video, and listen to both through one feed.

VODLoft does not play media itself. For downloaded files, use a self-hosted media server such as Plex or Jellyfin
for video, or Audiobookshelf for podcasts and audio. For RSS, add the VODLoft feed to your favorite podcast app.

This project was inspired by [Pinchflat](https://github.com/kieraneglin/pinchflat), an awesome project that allows you to automatically download videos from YouTube channels and playlists.

## Features

- Fully featured, easy-to-use Web UI for navigation and configuration.
- Add shows, podcasts, movies and single videos from The Daily Wire, YouTube, NPO Start and many other sites.
- Download premium Daily Wire content using your own Daily Wire subscription.
- Create multiple media profiles for the same show — for example, automatically maintain separate video and audio downloads.
- Organize your library exactly how you want with configurable naming, directory structures, and powerful Jinja templates.
- Automatically embed metadata and artwork, generate NFO files, and download show assets for media servers such as Jellyfin and Plex.
- Intelligently handles live Daily Wire episodes, avoiding countdown footage and waiting for the proper published version when appropriate.
- Create private audio or video RSS feeds for your shows and use them in your favorite podcast app.
- Stream Daily Wire episodes through RSS without downloading them, with stable episode URLs that can seamlessly transition to locally downloaded media once available.
- Automatically discover, download, refresh, and clean up media in the background.
- Configure automatic retention rules to remove older content from your server.
- Keeps yt-dlp up to date on its own, because sites change often.

## What VODLoft does not do

- **DRM-protected media cannot be downloaded, on any Source.** VODLoft does not bypass DRM. It still lists such
  media, so you can see what a show contains, but marks it with a **DRM** badge and never queues it for download.
  On NPO Start this applies to a large share of programmes, often whole seasons.
- NPO Plus sign-in is not supported yet, so programmes that need an NPO Plus subscription cannot be downloaded.
- RSS feeds for YouTube, NPO and other yt-dlp sites serve downloaded files only. Their stream links expire, so
  only Daily Wire episodes can be streamed through a feed without downloading them first.


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

* `/config` -- App configuration (`config.yml`), the SQLite database, session secret key, your Source sign-ins, and yt-dlp's updates and cookies file. Persist this directory so your settings, shows, and sign-ins survive container restarts and upgrades.
* `/downloads` -- Downloaded episodes and movies.

#### Useful environment variables

* `TZ` -- Container timezone. Defaults to `UTC`.
* `VL_ADMIN_AUTH__PASSWORD` -- Set this to require a password to access the Web UI. Leave it unset for open access on your local network. Always set this when exposing VODLoft through a reverse proxy.
* `API_URL` -- Override the API base URL given to the Web UI. This defaults to the relative `/api`, which works out of the box regardless of which host port you map.

Literally every setting VODLoft provides can be managed by environment variables, too. However, I generally do not advise
using environment variables for anything but the above examples. Any setting configured by environment variable cannot be changed in the VODLoft UI.

See the [Settings documentation](https://github.com/samuelvisser/vodloft/wiki/Settings) for all available settings, including their `config.yml` keys, environment variables, defaults, and explanations.


## Special thanks

VODLoft grew out of [WireLoft](https://github.com/samuelvisser/wireloft), an earlier project of mine that does the same for The Daily Wire only. The open-source [DailyWirePodcastProxy](https://github.com/fpnewton/DailyWirePodcastProxy) project has helped tremendously in figuring out how The Daily Wire API works. 
DailyWirePodcastProxy allows you to access premium versions of Daily Wire shows directly from your podcast app. Definitely check it out if you're interested!
Everything VODLoft downloads from YouTube and most other sites goes through [yt-dlp](https://github.com/yt-dlp/yt-dlp), which does the hard work of keeping up with those sites.


## Disclaimer
This project is not affiliated with or endorsed by The Daily Wire, YouTube, NPO or any other site it can download from.
Only download media you are allowed to, only connect accounts you are authorized to use, and comply with all
applicable terms and laws.