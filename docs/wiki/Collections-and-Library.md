# Collections and Library

VODLoft separates discovering media, managing it, and downloading it. Adding a collection or movie to your Library does not automatically download anything.

## Home

The Home page is the quickest way to see the state of VODLoft. It summarizes active and queued downloads, failed or problematic downloads, recent completions, Library size, and items that need attention.

Use Home when you want to know whether VODLoft is operating normally or something needs your attention.

## Add media

**Add media** in the Library takes a link to a collection, an episode, a movie or a single video. VODLoft asks each Source that claims the link's website whether it recognises it, and shows a preview from the first one that does. Continuing opens the normal Add Collection wizard, or the movie page, already filled in. A single video is added straight away and opens its video page. A link to an episode opens the collection it belongs to. If no Source recognises the link, VODLoft says so instead of guessing.

## Browse

Browse shows The Daily Wire's content that can be added to VODLoft. Collections and movies are kept separate so it is easier to find the kind of media you want.

Adding an item from Browse creates a managed entry in your Library. For collections, VODLoft indexes seasons and episodes. For movies, VODLoft stores the information needed for the local movie page and downloads.

## Library

Library contains the collections, movies and videos you have chosen to manage. Each card names the Source it comes from, and when your Library holds items from more than one Source, you can filter it by Source.

It has separate Collections, Movies and Videos views; a view appears once the Library holds that kind of media. Collection filters are remembered in that browser, so returning to the Library restores the last show-type selection you used.

### Shows

A collection page brings together its seasons and episodes, current publication state, local downloads, Download Profiles, RSS Stream Profiles, manual synchronization, and recent sync history.

A collection can stay in the Library without any download or RSS profiles. This is useful when you only want VODLoft to index it for now.

### Automatic download rules

Which automatic download options a collection offers follows its episode identification, whether the collection is a Podcast or a Series.

- Download Profiles can use a rolling date window, a number of recent episodes, or no limit.
- For a collection identified by season, Download Profiles also choose seasons and can automatically include future seasons.

See [[Download-Profiles]].

### Checking and cookies per Collection

A Collection's edit page has two choices that are normally best left alone.

**Look for new episodes** decides how often VODLoft checks the Collection:

- **Like other Collections** follows the schedules in Settings.
- **Less often** checks at most every six hours. It suits a Collection that posts once a week or less, and saves
  YouTube API quota for the rest.
- **On its own schedule** checks only on the schedule you set there; the regular checks leave it alone.

After about three weeks VODLoft knows how often a Collection posts, and the edit page suggests a choice when another
one would suit it better.

**Use the cookies file** appears for Collections from the yt-dlp Source, once you added a cookies file under
Settings, Sources. Signing in for every download can get an account flagged, so by default (**Only when needed**) a
Collection downloads without the cookies file. When a download fails because the site wants you signed in, such as a
bot check or a members-only video, the Collection uses the cookies file for a week, starting with the retry. The edit
page shows when that is the case. **Always** and **Never** do what they say.

## Seasons and episodes

Series can contain multiple seasons. The collection page lets you switch between them rather than treating the entire collection as one long list.

Episodes can also have different Daily Wire types, such as regular episodes and auxiliary items. Profiles can choose which types they apply to.

An episode can appear in VODLoft before final downloadable media exists. You may therefore see an episode that is scheduled, live, processing, still using a countdown version, final, or temporarily unavailable. VODLoft continues monitoring recent non-final episodes automatically.

## Sync now and sync history

VODLoft checks managed collections automatically, but a collection's **Sync now** action checks that collection immediately.

Use it when you know Daily Wire has published something and you do not want to wait for the next scheduled check.

The collection also keeps recent synchronization results. This helps distinguish between VODLoft not having checked yet and a successful check that found nothing new.

## Local copies of episodes

An episode can have more than one local copy when different Local Media Profiles are used, for example an audio version and a 1080p video version.

The episode page shows its downloads, formats, file sizes, and download history. Queue-wide activity is available from the main **Downloads** page. See [[Downloads-and-File-Integrity]].

### Bulk download and bulk delete

**Bulk download** on a collection's page downloads many episodes at once with one Local Media Profile. Choose the episode types and, for a series, the seasons. For a podcast you can limit it to the latest episodes, the last so many days, or episodes from a start date. Episodes that already have a file for that profile, that are still running, or that VODLoft cannot download (DRM, removed from the Source, or a subscription VODLoft is not signed in with) are skipped. Missing files are downloaded again.

**Bulk delete downloads** and **Bulk delete and re-download** can delete everything, or only episodes older than a number of days, or everything except the latest downloads in the chosen profiles. Episodes without a download do not count toward that number. Deleting everything with **Bulk delete downloads** turns off the Download Profiles for the chosen profiles first, so they do not download it all again. Deleting only some episodes leaves the Download Profiles on, so episodes they cover can be downloaded again.

## Movies and extras

Movies are managed separately from collections and are downloaded manually rather than through collection Download Profiles.

A movie page can include the main movie, descriptive and release metadata, available download formats, movie extras supplied by Daily Wire, and download progress/history.

Upcoming movies can be added to the Library before their final media is available. VODLoft keeps the local movie entry available and can refresh its Daily Wire metadata as the release approaches.

Movie output templates should distinguish the main movie from extras so different items cannot use the same filename. See [[Local-Media-Profiles#movies-and-extras]].

## Single videos

A single video is one video added on its own, outside any collection. It appears under **Videos** in the Library. Its page shows the uploader, upload date and description, and one download row for each Video Local Media Profile. Single videos are downloaded manually. **Refresh details** asks the site for the current title, description and thumbnail.

Single videos come from yt-dlp, which supports YouTube and well over a thousand other sites. A link to a page yt-dlp has no dedicated support for is shown as "Other sites · best effort": VODLoft tries to find a video on the page, which often works for plain video pages but not always.

## YouTube channels and playlists

A YouTube channel or playlist, or a playlist on another site yt-dlp supports, can be added as a collection: paste its link in **Add media** or in the Add Collection wizard and pick Podcast or Series, or find it with **Search YouTube** (below). A channel link adds all of the channel's uploads: its videos, Shorts and livestreams. A link to the channel's Shorts or Live tab adds only those.

These collections have no seasons of their own, so VODLoft makes one season per upload year. They are added as a Series identified by date by default; pick another episode identification in the Add Collection wizard if you prefer. Seasonal numbers the videos in each year by upload date, such as S2024E01 and S2024E02, and Numbered counts them across the collection. A video found later is numbered after the ones VODLoft already has, so existing file names never change. Download Profiles work as for any other collection. Their streams serve downloaded files only.

YouTube videos are tagged **Video**, **Short** or **Livestream**. A livestream keeps its tag after the broadcast ends. Shorts and livestreams are numbered on their own across the collection, such as short.12 and livestream.3, so they never shift the numbers of normal videos, and episode cards show a Short or Livestream badge. Download and RSS profiles choose which tags they want; new YouTube profiles start with Video and Livestream and leave Shorts out. Videos from other sites are all tagged Video.

A quick check looks for new videos every 10 minutes or so, adds only what is new, and hands it to your Download Profiles; a full re-scan once a day catches anything it missed (see [[Settings#episode-discovery-and-monitoring]]). With a YouTube Data API key (see [[Settings#youtube-data-api-key]]), a YouTube channel of a few thousand videos is fully listed in under a minute. Without a key, VODLoft looks up each new video with yt-dlp and pauses between lookups, so the first scan of a large channel takes hours; the result is the same, only slower. Private and deleted videos are skipped.

### Upcoming streams and premieres

An announced livestream or premiere is added as soon as VODLoft finds it, marked **Upcoming** with the time it starts. VODLoft looks it up again every hour, and every couple of minutes from 15 minutes before it starts. While it is on, it shows as **Live**, and VODLoft checks it every few minutes. Once the video is published, your Download Profiles download it like any other video. VODLoft never records a stream while it is live.

A stream that starts late shows as **Delayed**. In a collection named by date, the episode takes the date it was actually published. A stream that is cancelled, or made private before it airs, gets **No usable media** and is removed after a while, just like a Daily Wire episode that disappears. If it comes back, VODLoft follows it again.

This works for every site yt-dlp supports that announces streams, not only YouTube. If you would rather only see videos once they are published, turn off **Upcoming and live videos** for the site under **Settings → Automation → Per-Site scheduling**, or for every site at once with the system setting there.

### Renamed and removed videos

The daily re-scan also refreshes the episodes VODLoft already has. A video that was renamed or got a new description or thumbnail shows its new title, description and thumbnail in VODLoft. File names never change, so files you already downloaded keep their names; files downloaded later use the new title.

A video that was deleted or made private gets a **Removed** badge. Its downloaded files are kept, and Download Profiles stop trying to download it. If the video comes back, the badge goes away.

With a YouTube Data API key this costs 1 unit per 50 episodes a day. Without a key, or once the quota is used up, titles are refreshed from yt-dlp's listing of the collection instead. yt-dlp cannot tell a removed video from one it did not list, so only the API marks videos as removed.


### Search YouTube

**Search YouTube** on the Add media page finds channels, playlists and videos by name. Type a search and choose **Search** or press Enter; each search costs YouTube API quota, so VODLoft does not search while you type. Picking a channel or playlist continues to the Add Collection wizard, or opens the collection when it is already in your Library; picking a video adds it under **Videos**, as if you had pasted its link.

With a YouTube Data API key, a search goes through the API and collections subscriber and video counts, durations and upload dates. It costs about 102 units from the search share, and the line above the results says how many API searches are left today. Without a key, when the search share is used up or set to 0, or when the API fails, VODLoft searches with yt-dlp instead. That takes a few seconds longer and collections fewer details, and the line above the results says why yt-dlp answered. The same search within an hour is answered again without asking YouTube.

## NPO Start

Series and programmes from NPO Start (npo.nl) can be added without an NPO account. **Search NPO Start** on the Add media page finds series and programmes by name, or paste a link to a series, season or episode. A series is added as a collection with NPO's own seasons. By default it is a Series identified by season, with NPO's episode numbers, such as S02E05; the Add Collection wizard lets you identify episodes by date or number instead. A programme outside a series is added as a single video.

Many NPO programmes are protected by DRM, often whole seasons, and VODLoft marks them as described below. The rest download in the best quality NPO offers without an account. Programmes that need an NPO Plus subscription cannot be downloaded yet.

## Media protected by DRM

VODLoft cannot download media that is protected by DRM. Such an episode, movie or video shows a DRM badge, and its page says "Protected by DRM, cannot be downloaded" where the download controls would be. VODLoft marks an item this way when its Source reports DRM, or when a download fails because of it. Download Profiles skip protected episodes, and a download that fails because of DRM is not retried.

## Profiles and files are separate

A Local Media Profile describes the local file VODLoft should create. A Download Profile describes which collection episodes should be downloaded automatically. An RSS Stream Profile describes a private feed. A download record represents actual file activity.

Changing or deleting a profile is therefore not the same as deleting a downloaded file. Before changing retention or removing profiles, review the affected collection and its existing downloads so the result matches what you intend to keep.