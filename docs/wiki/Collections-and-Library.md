# Collections and Library

VODLoft separates discovering media, managing it, and downloading it. Adding a collection or movie to your Library does not automatically download anything.

## Home

The Home page is the quickest way to see the state of VODLoft. It summarizes active and queued downloads, failed or problematic downloads, recent completions, Library size, and items that need attention.

Use Home when you want to know whether VODLoft is operating normally or something needs your attention.

## Add media

**Add media** in the Library takes a link to a collection, an episode, a movie or a single video. VODLoft asks each Source that claims the link's website whether it recognises it, and shows a preview from the first one that does. Continuing opens the normal Add Collection wizard, or the movie page, already filled in. A single video is added straight away and opens its video page. A link to an episode opens the collection it belongs to. If no Source recognises the link, VODLoft says so instead of guessing.

The Add Collection wizard suggests a collection type and episode identification, which you can change. It suggests **Music** for an album on YouTube Music, for a playlist or channel of a YouTube channel with releases on YouTube Music, as a music artist's has, and for anything on a music site such as Bandcamp or SoundCloud, and says why. Music is always identified by season, with each album as one. Whether its items are tracks or music videos follows from the site: sound only on Bandcamp and SoundCloud, video on YouTube.

**Add empty collection** starts a collection of your own, without a link: give it a name, choose Series or Music, and the Seasons window opens so you can add its links. See [Collections of only playlists](#collections-of-only-playlists).

## Browse

Browse shows The Daily Wire's content that can be added to VODLoft. Collections and movies are kept separate so it is easier to find the kind of media you want.

Adding an item from Browse creates a managed entry in your Library. For collections, VODLoft indexes seasons and episodes. For movies, VODLoft stores the information needed for the local movie page and downloads.

## Library

Library contains the collections, movies and videos you have chosen to manage. Each card names the Source it comes from, and when your Library holds items from more than one Source, you can filter it by Source.

It has separate Collections, Movies and Videos views; a view appears once the Library holds that kind of media. Collection filters are remembered in that browser, so returning to the Library restores the last show-type selection you used.

Collections are listed **Recently used** first: the collection whose page you opened last comes first, and collections you never opened come last. The sort menu beside the search also lists them by **Often used** (the ones you open most first), **Name**, **Release date** (when the oldest episode came out) or **Added at** (when the collection was added to VODLoft), and the button next to it turns the order around. VODLoft remembers the order you pick for your user account; without user accounts, the browser remembers it. While you search, the best matches come first, whatever order you picked.

A collection imported from Pinchflat counts as added on the day it was added to Pinchflat.

### Shows

A collection page brings together its seasons and episodes, current publication state, local downloads, Download Profiles, RSS Stream Profiles, manual synchronization, and recent sync history.

A collection can stay in the Library without any download or RSS profiles. This is useful when you only want VODLoft to index it for now.

### Automatic download rules

Which automatic download options a collection offers follows its episode identification, whether the collection is a Podcast, a Series or Music.

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

**Use the cookies file** appears for Collections from the yt-dlp Source. It uses the cookies file of the Collection's
site, added under Settings › Sources › Authentication. Signing in for every download can get an account flagged, so by default (**Only when needed**) a
Collection downloads without the cookies file. When a download fails because the site wants you signed in, such as a
bot check or a members-only video, the Collection uses the cookies file for a week, starting with the retry. The edit
page shows when that is the case. **Always** and **Never** do what they say.

### Podcast, Series and Music

Every collection is a **Podcast**, a **Series** or **Music**. You choose when adding it, and can change it later on its Edit page.

- A **Podcast** downloads its newest episodes, by date or by number.
- A **Series** downloads by season.
- **Music** is an artist's music: each season is an album, and each episode a track. It downloads by season, like a Series, and takes Collection profiles available for Music, which keep tracks or music videos (see [[Local-Media-Profiles#music-tracks-and-music-videos]]). VODLoft uses those words everywhere for it: its pages, menus and windows say album instead of season, and track instead of episode. On a site with videos, such as YouTube, what the collection lists are called music videos.

A collection can only change to a type its Download Profiles suit. To make a Series into Music, remove its Download Profiles first, and add new ones with a profile for Music.

### Changing how episodes are numbered

A collection's **Episode identification** decides how its episodes are numbered: by date (such as 2025-01-31), by number (such as 2460), or by season and episode (such as S03E12). You can change it later on the collection's Edit page.

Before anything changes, VODLoft shows what the change would do:

- a few episodes with their old and new numbers, and how many episodes get a new one;
- episodes that have no number of their own on their site, which become auxiliary episodes;
- how many downloaded files are renamed, because their file names use the episode number;
- Download Profiles whose filters would now leave some episodes out, and how many of their downloads would be deleted.

Once you confirm, the collection's page opens and shows the change's progress. VODLoft numbers the episodes again, moves the downloaded files to their new names, and rewrites the metadata in and next to them, without downloading anything again. While the change runs, the Episode identification can't be changed again.

Numbering by season needs every season to have a number. If a season has none, the Seasons window numbers it when you put the seasons in order (see [Renaming and ordering seasons](#renaming-and-ordering-seasons)).

## Seasons and episodes

Series can contain multiple seasons. The collection page lets you switch between them rather than treating the entire collection as one long list.

### Renaming and ordering seasons

**Seasons** on a collection's **Edit** page opens the Seasons window. Give a season another name, or drag the seasons, or use the arrows, to put them in another order. The seasons are numbered again in their new order. **Automatic order** puts them back in VODLoft's own order. Seasons can't be deleted here; only a playlist or album season goes away, when you turn it off (see below).

Renaming a season or giving it another number doesn't rename files you already downloaded. To give them their new names, use **Rename all episode files** in the collection's **Actions** menu. Turn on **Rename season folders too** there to move files into the folder of the season they are in now, with its new number. In a collection with playlist seasons, downloaded videos then also move to the playlist season they belong in now.

### Playlists and albums as seasons

A collection of a whole YouTube channel, or of an artist on Bandcamp or SoundCloud, can make the channel's playlists, or the artist's albums, seasons of their own. Turn on **Playlists as seasons** in the Seasons window (in a Music collection, the Albums window has **The artist's albums**), and choose:

- **Which playlists**: every playlist, also the ones to come, or only those you switch on in the list. **Look for new playlists** asks the site for the list again. A playlist you switch on is **A season of its own**, or **Contents only**: its videos are then in the collection, but in its other seasons, such as Videos or a season per year, instead of a season named after the playlist. **Bulk edit** above the list lets you pick several playlists and switch them on or off, or make them seasons or contents only, in one go; the changes are saved with the rest of the window.
- **When the channel adds a playlist**: ask you, make it a season right away, or always skip it. A site that knows more than one kind of list has a setting for each: on SoundCloud, one for new albums and one for new playlists. A Music collection on such a site skips new playlists until you choose otherwise, and when it is set up it starts with only the albums switched on.
- **Videos in no playlist**: one season called **Videos** (**Singles** for music), or a season per year.
- **How playlist content fits in the collection** (in the site's own word, such as album), for videos of other channels in these playlists: **Only include media already in the collection** (the default), **Include media that is not in the collection**, in their playlist's season, or **Include only what the playlists contain** (see [Collections of only playlists](#collections-of-only-playlists)).

Each playlist season is named after its playlist, and its videos keep the order of the playlist, as do their episode numbers. An album's tracks keep the album's track order. Playlist seasons go in the order of their first video, so with a season per year a 2025 playlist comes after the 2025 season. An artist's albums come after Singles, in the order the artist lists them; you can still reorder them, and **Automatic order** brings back the artist's order. A video that is in more than one playlist goes to the season that comes first, unless the collection is set to put it in each (see [A video in several seasons](#a-video-in-several-seasons)). Files you already downloaded keep their numbers.

**Playlists** (**Albums**) chooses how the playlist seasons are laid out: **A season per playlist**, or **Together in seasons by year**. By year, the playlists still decide which videos are in the collection, but every video goes to the season of the year it came out, as do the videos in no playlist. Inside a year, videos go by date. Videos you already downloaded stay where they are, marked **Moved**, until you move them. Output templates still get the playlist a video came from as `section_title`, so files can be named by playlist inside a year folder.

#### A video in several seasons

In the Seasons window, **When an episode belongs in several seasons** (in a Music collection, **When a track belongs on several albums**) decides what happens with a video that more than one of the collection's playlist seasons have, such as a track that is on an album and on a "Best of":

- **Only in the first season** (**Only on the first album**): it is one episode, in the season that comes first in the order shown in the window. This is where a Podcast or Series starts.
- **In each season** (**On each album**): it is an episode in each of those seasons, with its own number and its own files, so every season is whole. Each one downloads on its own, so a track on two albums is two files, each tagged with its own album and track number. This is where a Music collection starts.

Two playlists that share one season still give a video one episode there, and with **Together in seasons by year** a video has one upload year, so it is in one season. When a playlist no longer has a video, only its episode in that season leaves. Switching back to **Only in the first season** removes the extra episodes: ones without downloads go at once, and downloaded ones stay, marked **Removed**, until you answer on Home whether to keep them.

Several playlists can share one season, such as a "Part 1" and a "Part 2" of the same series. In the Seasons window, pick the other season under **Together with** on a playlist's season. The season keeps its name and holds the videos of its first playlist first, then those of the next, numbered in that order. **Own season** gives a playlist a season of its own again. Either way, downloaded videos move with their files.

When a playlist season is turned off, its downloaded videos move to the season a new video would go to, and their files are renamed and moved with them. A video that was only in the collection because that playlist had it leaves the collection, and **its downloaded files are deleted**. The same happens when you switch back to leaving out other channels' videos. The Seasons window tells you before you save how many videos leave and how many of them have files.

When the channel takes such a video out of the playlist, VODLoft never deletes its files on its own. A video without files leaves the collection. A downloaded one stays, marked **Removed**, and the Home page asks whether to keep it, as for a video its site no longer has. **Keep** keeps it in the collection; **Don't keep** removes it, files and all. If the playlist lists it again, it is back as usual.

A downloaded video stays where it is when it belongs in another season now, for example because it was added to a playlist after it was downloaded, since moving it renames its files. The collection marks it **Moved**, and its page explains where it belongs now. **Move it there** on its page, or **Move to its new season** in its **Actions** menu, moves it and renames its files to match. To move every such video of the collection at once, use **Move episodes** in the collection's **Actions** menu. Both first show what the move does. The **Home** page lists collections with such videos under **Needs attention**.

Episodes can also have different Daily Wire types, such as regular episodes and auxiliary items. Profiles can choose which types they apply to.

An episode can appear in VODLoft before final downloadable media exists. You may therefore see an episode that is scheduled, live, processing, still using a countdown version, final, or temporarily unavailable. VODLoft continues monitoring recent non-final episodes automatically.

### Collections of only playlists

A collection set to **Include only what the playlists contain** holds nothing but its playlist seasons. There is no Videos season, and videos of the channel that are in none of its playlists are left out. Choosing this for an existing collection removes the videos no playlist has; the Seasons window tells you how many, and how many of them have files, before you save.

Such a collection doesn't need a link of its own. You can add links to it yourself in the Seasons window: a playlist, a channel or a single video, from any site yt-dlp supports, so one collection can hold playlists from YouTube and Vimeo side by side. Each link becomes a season. **Remove** takes a link you added out again, together with the videos only it had. When the collection does have a channel link, set or change it on its **Edit** page, its playlists are offered as before, and VODLoft keeps looking for new ones.

## Sync now and sync history

VODLoft checks managed collections automatically, but a collection's **Sync now** action checks that collection immediately.

Use it when you know Daily Wire has published something and you do not want to wait for the next scheduled check.

The collection also keeps recent synchronization results. This helps distinguish between VODLoft not having checked yet and a successful check that found nothing new.

## Local copies of episodes

An episode can have more than one local copy when different Local Media Profiles are used, for example an audio version and a 1080p video version.

The episode page shows its downloads, formats, file sizes, and download history. Queue-wide activity is available from the main **Downloads** page. See [[Downloads-and-File-Integrity]].

### Bulk download and bulk delete

**Bulk download** on a collection's page downloads many episodes at once with one Local Media Profile. Choose the episode types and, for a series or music, the seasons. For a podcast you can limit it to the latest episodes, the last so many days, or episodes from a start date. Episodes that already have a file for that profile, that are still running, or that VODLoft cannot download (DRM, removed from the Source, or a subscription VODLoft is not signed in with) are skipped. Missing files are downloaded again.

**Bulk delete downloads** can delete everything, or only episodes older than a number of days, or everything except the latest downloads in the chosen profiles. Episodes without a download do not count toward that number. Switch on **Re-download the deleted episodes** to have VODLoft download each deleted episode again right away. Without that switch, deleting everything turns off the Download Profiles for the chosen profiles first, so they do not download it all again. Deleting only some episodes leaves the Download Profiles on, so episodes they cover can be downloaded again.

### Rewriting metadata

**Rewrite metadata of all files** in a collection's **Actions** menu writes the tags inside the downloaded files and their NFO files again, for one Local Media Profile or all of them. Use it after changing a collection's genre or content rating, or a profile's title and description templates, to bring files that were already downloaded up to date. The files are not downloaded again: only their metadata changes. Profiles that keep no metadata are skipped.

## Movies and extras

Movies are managed separately from collections and are downloaded manually rather than through collection Download Profiles.

A movie page can include the main movie, descriptive and release metadata, available download formats, movie extras supplied by Daily Wire, and download progress/history.

Upcoming movies can be added to the Library before their final media is available. VODLoft keeps the local movie entry available and can refresh its Daily Wire metadata as the release approaches.

Movie output templates should distinguish the main movie from extras so different items cannot use the same filename. See [[Local-Media-Profiles#movies-and-extras]].

## Single videos

A single video is one video added on its own, outside any collection. It appears under **Videos** in the Library. Its page shows the uploader, upload date and description, and one download row for each Video Local Media Profile. Single videos are downloaded manually. **Refresh details** asks the site for the current title, description and thumbnail.

Single videos come from yt-dlp, which supports YouTube and well over a thousand other sites. A link to a page yt-dlp has no dedicated support for is shown as "Other sites · best effort": VODLoft tries to find a video on the page, which often works for plain video pages but not always.

## YouTube channels and playlists

A YouTube channel or playlist, or a playlist on another site yt-dlp supports, can be added as a collection: paste its link in **Add media** or in the Add Collection wizard and pick Podcast or Series, or find it with **Search YouTube** (below). A channel link adds all of the channel's uploads: its videos, Shorts and livestreams, unless you switch a feed off (see [Feeds and the channel's own season](#feeds-and-the-channels-own-season)). A link to the channel's Shorts or Live tab adds only those.

These collections have no seasons of their own, so VODLoft makes one season per upload year. They are added as a Series identified by date by default; pick another episode identification in the Add Collection wizard if you prefer. Seasonal numbers the videos in each year by upload date, such as S2024E01 and S2024E02, and Numbered counts them across the collection. A video found later is numbered after the ones VODLoft already has, so existing file names never change. Download Profiles work as for any other collection. Their streams serve downloaded files only.

YouTube videos are tagged **Video**, **Short** or **Livestream**. A livestream keeps its tag after the broadcast ends. Shorts and livestreams are numbered on their own across the collection, such as short.12 and livestream.3, so they never shift the numbers of normal videos, and episode cards show a Short or Livestream badge. Download and RSS profiles choose which tags they want; new YouTube profiles start with Video and Livestream and leave Shorts out. Videos from other sites are all tagged Video.

A quick check looks for new videos every 10 minutes or so, adds only what is new, and hands it to your Download Profiles; a full re-scan once a day catches anything it missed (see [[Settings#episode-discovery-and-monitoring]]). With a YouTube Data API key (see [[Settings#youtube-data-api-key]]), a YouTube channel of a few thousand videos is fully listed in under a minute. Without a key, VODLoft looks up each new video with yt-dlp and pauses between lookups, so the first scan of a large channel takes hours; the result is the same, only slower. Private and deleted videos are skipped.

### Upcoming streams and premieres

An announced livestream or premiere is added as soon as VODLoft finds it, marked **Upcoming** with the time it starts. VODLoft looks it up again every hour, and every couple of minutes from 15 minutes before it starts. While it is on, it shows as **Live**, and VODLoft checks it every few minutes. Once the video is published, your Download Profiles download it like any other video. VODLoft never records a stream while it is live.

A stream that starts late shows as **Delayed**. In a collection named by date, the episode takes the date it was actually published. A stream that is cancelled, or made private before it airs, is removed, like any video its site no longer has. A stream that already went live gets 4 hours to show up as a video before it is removed. See [[Automation-and-Background-Tasks#episodes-their-site-no-longer-has]].

This works for every site yt-dlp supports that announces streams, not only YouTube. If you would rather only see videos once they are published, turn off **Upcoming and live videos** for the site under **Settings → Automation → Per-Site scheduling**, or for every site at once with the system setting there.

### Renamed and removed videos

The daily re-scan also refreshes the episodes VODLoft already has. A video that was renamed or got a new description or thumbnail shows its new title, description and thumbnail in VODLoft. File names never change, so files you already downloaded keep their names; files downloaded later use the new title.

A video that was deleted or made private gets a **Removed** badge. Its downloaded files are kept, and Download Profiles stop trying to download it. If the video comes back, the badge goes away.

With a YouTube Data API key this costs 1 unit per 50 episodes a day. Without a key, or once the quota is used up, titles are refreshed from yt-dlp's listing of the collection instead. yt-dlp cannot tell a removed video from one it did not list, so only the API marks videos as removed.


### Search SoundCloud

**Search SoundCloud** on the Add media page finds SoundCloud accounts, albums, playlists and tracks by name, the way SoundCloud's own search does, with follower and track counts. Type a search and choose **Search** or press Enter. Picking an account, an album or a playlist continues to the Add Collection wizard; picking a track adds it under **Videos**. No key or account is needed: VODLoft searches the way yt-dlp reaches SoundCloud. If SoundCloud's search ever stops answering, VODLoft searches only its tracks instead, lists the accounts that made them first, and says so above the results.

A link you share from the SoundCloud app, such as `on.soundcloud.com/…`, works like the full link: VODLoft follows it to the page it stands for, so an artist's share link can be added as a collection.

### Search YouTube

**Search YouTube** on the Add media page finds channels, playlists and videos by name. Type a search and choose **Search** or press Enter; each search costs YouTube API quota, so VODLoft does not search while you type. Picking a channel or a playlist continues to the Add Collection wizard, or opens the collection when it is already in your Library; picking a video adds it under **Videos**, as if you had pasted its link.

With a YouTube Data API key, a search goes through the API and collections subscriber and video counts, durations and upload dates. It costs about 102 units from the search share, and the line above the results says how many API searches are left today. Without a key, when the search share is used up or set to 0, or when the API fails, VODLoft searches with yt-dlp instead. That takes a few seconds longer and collections fewer details, and the line above the results says why yt-dlp answered. The same search within an hour is answered again without asking YouTube.

## Creators

A creator is whoever makes the work you follow: the person or group behind a YouTube channel, a host on The Daily Wire, or an artist on Bandcamp or SoundCloud. In VODLoft a creator only groups collections: it gets a card and a page of its own in your Library, and its collections show on that page instead of next to it in the Library, though a search still finds them. Being part of a creator changes nothing about what a collection holds. Each collection keeps its own link, feeds, playlists, seasons, profiles and files, and decides on its own what it takes in. VODLoft calls a creator what their site calls them, so on The Daily Wire every button and page says host instead, and for music it says artist.

### Channel and list collections

Every collection is one of two kinds, from its link:

- A **channel** collection is made from a creator's own page: a YouTube channel (or only its Shorts or Live tab), an artist on Bandcamp or SoundCloud, or a Daily Wire show. It can make the creator's playlists or albums seasons of its own (see [Playlists and albums as seasons](#playlists-and-albums-as-seasons)), and it can be part of a creator.
- A **list** collection is made from one playlist or album. It holds what that list holds, in the list's order, and can't be part of a creator.

On a site where VODLoft knows no creators, such as NPO Start, every collection is a list collection.

### Feeds and the channel's own season

In the Seasons window of a channel collection (the Albums window for music), **Feeds** lists the parts of the channel the collection takes its videos from, such as Videos, Shorts and Live on YouTube. Switch a feed off to leave its videos out. The channel is listed again when you save: its videos that no feed or playlist of the collection still has leave the collection, and downloaded ones stay until Home asks whether to keep them.

**The channel's own season** chooses what the season of the channel itself holds:

- **What is in no playlist** (the default), as **Videos** (**Singles** for music): a video that is in a playlist season is only there.
- **Everything**, as **Channel**: every video of the feeds is in it, also the ones in a playlist that is a season, so they are in two seasons.

### Adding a collection to a creator

In the Add Collection wizard, a channel link shows **Add to a creator** (**Add to a host**, **Add to an artist**). Leave it on to group the new collection under the creator behind the link, who is added to your Library when they are not there yet, or pick another creator in your Library. A link to a Daily Wire host's page is not a collection: paste the link to one of their shows instead, and once it is in your Library the host's page offers the rest of their work.

A collection that is already in your Library can join later: choose **Add to creator** in its **Actions** menu. VODLoft finds the creator behind the collection's link, or you pick another one in your Library, for example for an artist's music videos on their label's channel. **Remove from creator** in the same menu makes it a plain collection again. Neither changes anything in the collection: it keeps its episodes, numbers, profiles, files, genre and content rating.

The creator's name becomes the author of their collections, and output templates can use `creator_title`, `creator_handle` and `creator_kind`, and `section_title` and `section_kind` for the playlist or feed an episode came from. See [Local Media Profiles](Local-Media-Profiles#collection-template-variable-reference).

### The creator's page

The creator's page shows their collections in your Library, and their movies. When a creator has more on their site than you have, such as a Daily Wire host's other shows and movies, a folded line at the bottom says so; open it to see them, each with a **+** button. A show not in your Library opens the Add Collection wizard, which adds it to the creator. A movie is added as one of the creator's, without downloading it. Taking a creator out of your Library keeps their collections and movies.

The creator's **Edit** page changes their name, and their **Genre** and **Content rating**. Those are written to the NFO file of each of the creator's collections that has none of its own; changing them here changes the collections that still had the old value.

### A creator on several sites

The same person or group often has a page on more than one site, such as a Daily Wire host who also has a YouTube channel. VODLoft keeps them as one creator, with an account for each site.

- **Combine with another creator** in a creator page's **Actions** menu makes two creators one. The other creator's accounts and collections move over, and they leave your Library as a creator of their own. Their collections keep their seasons, episodes, profiles and files.
- **Split off** on one of the accounts in the creator page's **Actions** menu undoes that: the account becomes a creator of its own again, named as its site names them, and takes the collections of that site along.

A creator is called what their site calls them while all their accounts are on one site, such as host on The Daily Wire, and an artist when they have a Music collection. On several sites, they are a creator.

### Music artists

A musician on **Bandcamp** or **SoundCloud** is added like any channel: paste a link to the artist's page, such as `https://artist.bandcamp.com` or `https://soundcloud.com/artist`, in the Add Collection wizard. VODLoft takes it for Music. Turn on **The artist's albums** in its Albums window to make each album an album of its own, with the other tracks under **Singles**. On SoundCloud a **Tracks** feed holds everything the artist uploaded, so tracks that are on no album have a place too; a Music collection there starts with only the albums switched on, and skips the artist's other playlists until you choose otherwise. To keep one album apart, add the album's own link as a list collection instead. Download them with a profile for Music that downloads audio only (see [[Local-Media-Profiles#music-tracks-and-music-videos]]), which tags every track with its album, artist and track number, such as 3/10.

A creator with a Music collection is called an **artist**, on its page and in the Library.

### Music videos

An artist's music videos are a collection of their own on the artist's page, beside the albums: they go to a Music
Videos library, not a Music library. Make it a Music collection and give it a Collection profile for **Music** that downloads video,
made from the **Music videos** preset (see [[Local-Media-Profiles#media-server-presets]]), which files each video under
the artist's name with a `musicvideo` NFO. A new profile for Music starts with Audio only, so choose a video
download, such as 1080p, and the form moves it to that preset.

Official videos are often on another channel than the albums, such as the artist's label. **Add to creator** can put
that collection under the artist anyway: pick the artist from your Library in its window.

### Full albums: splitting videos by chapter

Some channels upload a whole album as one long video, with a chapter per track. Set **Videos with chapters** to **A part per chapter** on the collection's Edit page, and each new video with chapters becomes a season of its own, named after the video, with an episode per chapter. In a Music collection that makes each video an album and each chapter a track, with its own title, length, track number and file.

Each part downloads only its own stretch of the video, so it works with everything else in VODLoft: Download Profiles, retention, upgrade checks and RSS feeds treat it like any other episode. A feed only offers a part once it is downloaded, because the site itself only has the whole video. A video without chapters stays one episode, and videos already in the collection when you turn this on stay as they are.

## NPO Start

Series and programmes from NPO Start (npo.nl) can be added without an NPO account. **Search NPO Start** on the Add media page finds series and programmes by name, or paste a link to a series, season or episode. A series is added as a collection with NPO's own seasons. By default it is a Series identified by season, with NPO's episode numbers, such as S02E05; the Add Collection wizard lets you identify episodes by date or number instead. A programme outside a series is added as a single video.

Many NPO programmes are protected by DRM, often whole seasons, and VODLoft marks them as described below. The rest download in the best quality NPO offers without an account. Programmes that need an NPO Plus subscription cannot be downloaded yet.

## Media protected by DRM

VODLoft cannot download media that is protected by DRM. Such an episode, movie or video shows a DRM badge, and its page says "Protected by DRM, cannot be downloaded" where the download controls would be. VODLoft marks an item this way when its Source reports DRM, or when a download fails because of it. Download Profiles skip protected episodes, and a download that fails because of DRM is not retried.

## Locked media: members and subscribers only

Some videos are only for paying viewers: channel members or subscribers on YouTube and other sites, a site's premium subscribers, NPO Plus subscribers, or a Daily Wire membership level such as Insider or All Access. When VODLoft knows a video needs such access, it shows a lock badge with what it needs, such as **Members only** or **All Access**. When the site refuses a download for that reason, the download shows as **Locked** on the Downloads page instead of as an error, and VODLoft does not keep retrying it or send a "download failed" notification.

For YouTube, VODLoft spots members-only videos from the badge YouTube shows on the channel page, both when it first finds a video and in its daily check of the channel, with or without a YouTube API key. While VODLoft keeps refreshing a new video's title and thumbnail in its first days, it also asks yt-dlp each time whether the video is for members only, on YouTube and every other site yt-dlp supports. When a site gives no such sign, VODLoft only finds out when a download is refused.

Some channels keep a video for members for a few days and then open it up for everyone. When VODLoft's daily check of a channel, or its refresh of a new video's details, sees that a video is open to everyone now, the lock badge goes away, and a video whose download was refused is downloaded right away. VODLoft also checks refused videos again on its own: a day after they were refused, then after three days and a week, and then weekly for about five weeks. When a video has opened up, its Download Profile downloads it as usual.

If you gained access yourself, for example by joining a channel and adding a new cookies file, or by signing in with a higher Daily Wire membership, VODLoft checks its locked videos again right away. You can also ask for this yourself: **Check again** in a locked download's log, or **Check locked videos again** in a collection's **Actions** menu, which only appears while the collection has locked videos.

## Profiles and files are separate

A Local Media Profile describes the local file VODLoft should create. A Download Profile describes which collection episodes should be downloaded automatically. An RSS Stream Profile describes a private feed. A download record represents actual file activity.

Changing or deleting a profile is therefore not the same as deleting a downloaded file. Before changing retention or removing profiles, review the affected collection and its existing downloads so the result matches what you intend to keep.