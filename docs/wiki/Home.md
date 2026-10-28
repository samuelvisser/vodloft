# VODLoft Wiki

VODLoft is a self-hosted media manager for shows, podcasts, movies and videos from The Daily Wire, YouTube, NPO Start and many other sites. It keeps a local library of the media you choose, downloads it to your own storage, and exposes shows through private RSS feeds.

Each site VODLoft works with is handled by a **Source**; see [[Sources]].

## What you can do with VODLoft

- Add media by pasting a link, search YouTube or NPO Start, or browse The Daily Wire's catalogue.
- Add YouTube channels and playlists as shows, and single videos from YouTube and many other sites.
- Keep show seasons and episodes synchronized automatically.
- Download episodes in audio, 720p, 1080p, or 4K where available.
- Download movies and movie extras using separate movie storage rules.
- Keep only the latest episodes, a date window, selected seasons, or everything.
- Organize files with customizable Local Media Profiles and Jinja output templates.
- Subscribe to private RSS feeds that use downloaded files, or for The Daily Wire also its streams.
- Track active, queued, failed, missing, and corrupted downloads from one place.

VODLoft never downloads media protected by DRM. It lists such media with a DRM badge instead. See [[Sources#media-protected-by-drm]].

## Main areas of the interface

### Home

The Home page is VODLoft's status dashboard. It shows active and queued downloads, recent completions, and items that need attention such as failed downloads or movie metadata problems.

### Add media and Browse

**Add media** takes a link to a show, episode, movie or video from any Source, and shows a preview before anything is added. It also searches YouTube and NPO Start. **Browse** is The Daily Wire's catalogue, for finding its shows and movies that are not yet in your Library.

### Library

The Library contains the shows, movies and videos VODLoft manages for you. Adding something to the Library does **not** automatically mean it must be downloaded.

For shows, VODLoft can manage seasons, episodes, automatic downloads, and RSS feeds. Movies and single videos are downloaded manually. Movies can include extras such as trailers or featurettes when The Daily Wire provides them.

### Downloads

The Downloads page is the central history and queue for actual media files. It shows progress, format, size, status, and available actions such as cancel, retry, prioritize, and viewing the download log.

### Profiles

VODLoft separates three decisions so they can be changed independently:

1. A **Local Media Profile** defines the format, download behavior, and output path for a local file.
2. A **Download Profile** decides which show episodes should be downloaded automatically with a Local Media Profile.
3. An **RSS Stream Profile** decides which episodes appear in a private feed and whether media should come from local downloads, The Daily Wire's streams, or both.

This makes it possible, for example, to keep every episode as audio, retain only the latest five episodes as 1080p video, and expose both through one RSS feed.

### Settings

The Settings page covers normal application, download, automation, Sources, and advanced settings. Most users can configure VODLoft entirely from this page; environment variables are mainly useful when a deployment needs to enforce a value.

## Start here

- [[Installation]] — install VODLoft with Docker and persist the correct directories.
- [[First-Run-Setup]] — sign in to Sources, secure VODLoft, and add your first media.
- [[Sources]] — which sites VODLoft supports, how links are matched, and what DRM means for downloads.
- [[Shows-and-Library]] — understand Home, Add media, Browse, Library, shows, movies, videos, seasons, and episodes.
- [[Local-Media-Profiles]] — choose formats, download behavior, and output paths.
- [[Download-Profiles]] — configure automatic show downloads and retention.
- [[Downloads-and-File-Integrity]] — use the download queue and understand missing/corrupted file handling.
- [[Quick-Download]] — download one file from a link, without adding it to your library.
- [[Podcast-RSS-Feeds]] — create private podcast/video feeds.
- [[Automation-and-Background-Tasks]] — understand what VODLoft keeps updated automatically.
- [[Settings]] — complete user-facing settings reference.
- [[Security-and-Remote-Access]] — protect the UI and private feeds.
- [[Backups-and-Upgrades]] — back up and update your installation safely.
- [[Troubleshooting]] — symptom-based help for common problems.

## Accounts and access

VODLoft does not bypass any site's access checks, memberships or DRM. Public Daily Wire content can be used without connecting an account. Member-exclusive content requires a Daily Wire account that already has access to it.

VODLoft uses Daily Wire's device authorization flow, so you authorize VODLoft through The Daily Wire rather than giving VODLoft your Daily Wire password. See [[Daily-Wire-Integration]].

## Keep RSS URLs private

A VODLoft RSS feed URL contains a secret token. Treat the complete URL like a password or API key. Anyone who has it can use that feed without signing in to the VODLoft web interface.

If a feed URL is exposed, regenerate it from the Stream Profile. See [[Podcast-RSS-Feeds]] and [[Security-and-Remote-Access]].