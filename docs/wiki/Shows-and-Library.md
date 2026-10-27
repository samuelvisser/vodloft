# Shows and Library

VODLoft separates discovering media, managing it, and downloading it. Adding a show or movie to your Library does not automatically download anything.

## Home

The Home page is the quickest way to see the state of VODLoft. It summarizes active and queued downloads, failed or problematic downloads, recent completions, Library size, and items that need attention.

Use Home when you want to know whether VODLoft is operating normally or something needs your attention.

## Add media

**Add media** in the Library takes a link to a show, an episode, a movie or a single video. VODLoft asks each Source that claims the link's website whether it recognises it, and shows a preview from the first one that does. Continuing opens the normal Add Show wizard, or the movie page, already filled in. A single video is added straight away and opens its video page. A link to an episode opens the show it belongs to. If no Source recognises the link, VODLoft says so instead of guessing.

## Browse

Browse shows The Daily Wire's content that can be added to VODLoft. Shows and movies are kept separate so it is easier to find the kind of media you want.

Adding an item from Browse creates a managed entry in your Library. For shows, VODLoft indexes seasons and episodes. For movies, VODLoft stores the information needed for the local movie page and downloads.

## Library

Library contains the shows, movies and videos you have chosen to manage. Each card names the Source it comes from, and when your Library holds items from more than one Source, you can filter it by Source.

It has separate Shows, Movies and Videos views; a view appears once the Library holds that kind of media. Show filters are remembered in that browser, so returning to the Library restores the last show-type selection you used.

### Shows

A show page brings together its seasons and episodes, current publication state, local downloads, Download Profiles, RSS Stream Profiles, manual synchronization, and recent sync history.

A show can stay in the Library without any download or RSS profiles. This is useful when you only want VODLoft to index it for now.

### Automatic download rules

Which automatic download options a show offers follows its episode identification, whether the show is a Podcast or a Series.

- Download Profiles can use a rolling date window, a number of recent episodes, or no limit.
- For a show identified by season, Download Profiles also choose seasons and can automatically include future seasons.

See [[Download-Profiles]].

## Seasons and episodes

Series can contain multiple seasons. The show page lets you switch between them rather than treating the entire show as one long list.

Episodes can also have different Daily Wire types, such as regular episodes and auxiliary items. Profiles can choose which types they apply to.

An episode can appear in VODLoft before final downloadable media exists. You may therefore see an episode that is scheduled, live, processing, still using a countdown version, final, or temporarily unavailable. VODLoft continues monitoring recent non-final episodes automatically.

## Sync now and sync history

VODLoft checks managed shows automatically, but a show's **Sync now** action checks that show immediately.

Use it when you know Daily Wire has published something and you do not want to wait for the next scheduled check.

The show also keeps recent synchronization results. This helps distinguish between VODLoft not having checked yet and a successful check that found nothing new.

## Local copies of episodes

An episode can have more than one local copy when different Local Media Profiles are used, for example an audio version and a 1080p video version.

The episode page shows its downloads, formats, file sizes, and download history. Queue-wide activity is available from the main **Downloads** page. See [[Downloads-and-File-Integrity]].

## Movies and extras

Movies are managed separately from shows and are downloaded manually rather than through show Download Profiles.

A movie page can include the main movie, descriptive and release metadata, available download formats, movie extras supplied by Daily Wire, and download progress/history.

Upcoming movies can be added to the Library before their final media is available. VODLoft keeps the local movie entry available and can refresh its Daily Wire metadata as the release approaches.

Movie output templates should distinguish the main movie from extras so different items cannot use the same filename. See [[Local-Media-Profiles#movies-and-extras]].

## Single videos

A single video is one video added on its own, outside any show. It appears under **Videos** in the Library. Its page shows the uploader, upload date and description, and one download row for each Video Local Media Profile. Single videos are downloaded manually. **Refresh details** asks the site for the current title, description and thumbnail.

Single videos come from yt-dlp, which supports YouTube and well over a thousand other sites. A link to a page yt-dlp has no dedicated support for is shown as "Other sites · best effort": VODLoft tries to find a video on the page, which often works for plain video pages but not always.

## YouTube channels and playlists

A YouTube channel or playlist, or a playlist on another site yt-dlp supports, can be added as a show: paste its link in **Add media** or in the Add Show wizard and pick Podcast or Series. A channel link adds all of the channel's uploads: its videos, Shorts and livestreams. A link to the channel's Shorts or Live tab adds only those.

These shows have no seasons of their own, so VODLoft makes one season per upload year. They are added as a Series identified by date by default; pick another episode identification in the Add Show wizard if you prefer. Seasonal numbers the videos in each year by upload date, such as S2024E01 and S2024E02, and Numbered counts them across the show. A video found later is numbered after the ones VODLoft already has, so existing file names never change. Download Profiles work as for any other show. Their streams serve downloaded files only, and their metadata is not refreshed after a video is added.

YouTube videos are tagged **Video**, **Short** or **Livestream**. A livestream keeps its tag after the broadcast ends. Shorts and livestreams are numbered on their own across the show, such as short.12 and livestream.3, so they never shift the numbers of normal videos, and episode cards show a Short or Livestream badge. Download and RSS profiles choose which tags they want; new YouTube profiles start with Video and Livestream and leave Shorts out. Videos from other sites are all tagged Video.

VODLoft checks the channel or playlist for new videos on the usual schedule. With a YouTube Data API key (see [[Settings#youtube-data-api-key]]), a YouTube channel of a few thousand videos is fully listed in under a minute. Without a key, VODLoft looks up each new video with yt-dlp and pauses between lookups, so the first scan of a large channel takes hours; the result is the same, only slower. Private and deleted videos are skipped, and an upcoming or ongoing livestream is added once it has finished.

## NPO Start

Series and programmes from NPO Start (npo.nl) can be added without an NPO account. **Search NPO Start** on the Add media page finds series and programmes by name, or paste a link to a series, season or episode. A series is added as a show with NPO's own seasons. By default it is a Series identified by season, with NPO's episode numbers, such as S02E05; the Add Show wizard lets you identify episodes by date or number instead. A programme outside a series is added as a single video.

Many NPO programmes are protected by DRM, often whole seasons, and VODLoft marks them as described below. The rest download in the best quality NPO offers without an account. Programmes that need an NPO Plus subscription cannot be downloaded yet.

## Media protected by DRM

VODLoft cannot download media that is protected by DRM. Such an episode, movie or video shows a DRM badge, and its page says "Protected by DRM, cannot be downloaded" where the download controls would be. VODLoft marks an item this way when its Source reports DRM, or when a download fails because of it. Download Profiles skip protected episodes, and a download that fails because of DRM is not retried.

## Profiles and files are separate

A Local Media Profile describes the local file VODLoft should create. A Download Profile describes which show episodes should be downloaded automatically. An RSS Stream Profile describes a private feed. A download record represents actual file activity.

Changing or deleting a profile is therefore not the same as deleting a downloaded file. Before changing retention or removing profiles, review the affected show and its existing downloads so the result matches what you intend to keep.