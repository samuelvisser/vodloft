# Sources

VODLoft calls the services it adds media from **Sources**. Each Source knows how to talk to one service: how to recognise its links, list a show's episodes and find the media to download. Everything after that, such as profiles, file naming, metadata, artwork, NFO files and RSS feeds, works the same whatever the Source.

**Settings → Sources** lists every Source with what it supports, and holds its sign-in and settings.

## The Sources

| Source | Sites | Adds | Account |
|---|---|---|---|
| The Daily Wire | dailywire.com | Shows, podcasts, movies and movie extras | Optional, needed for member content |
| yt-dlp | YouTube and [well over a thousand other sites](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md), plus any other page with a video | Channels and playlists as shows, single videos | Optional cookies file and YouTube API key |
| NPO Start | npo.nl | Series as shows, programmes outside a series as single videos | Not needed; NPO Plus is not supported yet |

### The Daily Wire

The Daily Wire has the most complete support: browse its catalogue, add shows and movies, sign in for member content, and stream episodes through RSS without downloading them. Only The Daily Wire has live episodes, movie extras, membership levels and RSS streaming, so those controls appear only on its items. See [[Daily-Wire-Integration]].

### yt-dlp

[yt-dlp](https://github.com/yt-dlp/yt-dlp) handles YouTube and many other video sites. A channel or playlist becomes a show with one season per upload year, and a link to one video becomes a single video under **Videos** in the Library. See [[Shows-and-Library#youtube-channels-and-playlists]].

yt-dlp also tries any site no other Source claims. Such a link is labelled "Other sites · best effort": it often works for a plain page with one video, but not always.

Sites change often, and yt-dlp has to keep up. VODLoft updates yt-dlp once a week, and **Update now** on its card does it straight away. A cookies file lets yt-dlp reach videos that need a signed-in viewer, and an optional free YouTube Data API key makes YouTube channels much faster to list and check. **Search YouTube** on the Add media page finds YouTube channels, playlists and videos by name, with or without a key. See [[Settings#yt-dlp]] and [[Shows-and-Library#search-youtube]].

### NPO Start

NPO Start is the catalogue of the Dutch public broadcaster. **Search NPO Start** on the Add media page finds series and programmes by name, or paste a link to a series, season or episode. No account is needed. See [[Shows-and-Library#npo-start]].

Much of NPO Start is protected by DRM, often whole seasons, so a series can be indexed in full while only part of it can be downloaded.

## Adding media by link

Paste a link on the **Add media** page. VODLoft asks the Sources that claim the link's site whether they recognise it, and shows a preview from the first one that does. Nothing is added until you continue.

Some sites can be handled by more than one Source. Today that is npo.nl, which both NPO Start and yt-dlp claim. NPO Start is asked first by default. The **Sites** card under Settings → Sources changes which Source is asked first for a site, and **Look up with** on the Add media page asks another Source for one link.

A show stays with the Source it was added from.

## Media protected by DRM

VODLoft never downloads media protected by DRM, on any Source, and does not try to get around it.

Protected media is still listed, so you can see everything a show contains. It carries a **DRM** badge, and its page says "Protected by DRM, cannot be downloaded" where the download controls would be. Download Profiles skip it, and a download that fails because of DRM is marked the same way and not retried.

## Not in this beta

- NPO Plus sign-in, so NPO programmes that need a subscription cannot be downloaded.
- NPO films as Movies, and NPO subtitles.
- RSS streaming without downloading, for anything other than The Daily Wire. yt-dlp and NPO stream links expire, so their feeds serve downloaded files only.
- Moving a show from one Source to another.
