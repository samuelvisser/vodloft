# Coming from ytdl-sub or Pinchflat

VODLoft downloads YouTube channels and playlists, and many other sites, into a media library, like ytdl-sub and
Pinchflat do. It imports either of them, so you keep your files and do not download anything twice.

## What you get

- **A web interface for everything.** No YAML to read up on: collections, profiles and filters are set in the UI, and
  every setting explains itself.
- **Your library, browsable.** Every channel, playlist and video is in the Library, with its episodes, seasons and
  what is downloaded.
- **Files for your media server.** Output templates are Jinja, with presets for Plex, Jellyfin and Emby, Kodi and
  Audiobookshelf, and NFO files and artwork when you want them (see [[Local-Media-Profiles]]).
- **Watching without downloading.** Share a collection as a private podcast feed, a TV channel with a guide, or a
  folder for Infuse and Kodi: [[Podcast-RSS-Feeds]], [[IPTV-Channels]] and [[WebDAV-Shares]]. Episodes can come from
  your downloads or straight from the site.
- **Better versions later.** The upgrade check downloads a video again when a higher resolution, new SponsorBlock
  segments or real subtitles come out, and only replaces the file when the new one is better (see
  [[Download-Profiles#upgrade-check]]).
- **Throttling handled.** When YouTube only offers 360p, VODLoft waits and tries again instead of keeping a poor file
  (see [[Downloads-and-File-Integrity#when-youtube-only-offers-360p]]).

## How the things you know map to VODLoft

| ytdl-sub | Pinchflat | VODLoft |
| --- | --- | --- |
| A subscription | A source | A collection |
| Presets such as *Max 1080p* and the TV show presets | A media profile | A **Local Media Profile**: quality, subtitles, SponsorBlock and the output template |
| Only Recent, Filter Keywords, Filter Duration | Title filter, length limits, retention | A **Download Profile**: which episodes to download and how long to keep them |
| The cron job | Indexing schedule | VODLoft's own checks, per collection or per Site (see [[Automation-and-Background-Tasks]]) |
| The download archive | The database | VODLoft's database |

## Move over

1. Install VODLoft (see [[Installation]]) and mount the folder with your downloads at `/downloads`. To keep the same
   file owner as before, set `PUID` and `PGID` (see [[Installation#run-as-your-own-user]]).
2. Open **Settings → Import** and upload ytdl-sub's `subscriptions.yaml` (and `config.yaml`), or Pinchflat's config
   folder.
3. Check the preview: where VODLoft finds your files, the collections, the profiles with their templates, and how many
   files were found.
4. Stop ytdl-sub's cron job or pause Pinchflat, so the two do not download the same videos.
5. Import. VODLoft adopts every file it found, then turns on the Download Profiles if you asked for that.

The details of each import are in [[Existing-Files-and-Imports#importing-from-ytdl-sub]] and
[[Existing-Files-and-Imports#importing-from-pinchflat]].
