# Download Profiles

Download Profiles decide **which collection episodes VODLoft should download automatically**. The attached Local Media Profile decides the file format, download behavior, and output path. See [[Local-Media-Profiles]].

A collection can have one Download Profile per Local Media Profile. For example, you can keep audio for every episode with one profile, and video for only the newest five with another.

Movies do not use Download Profiles; movie downloads are started manually from the movie page.

## Common options

Every Download Profile lets you choose:

- whether the profile is enabled;
- which Local Media Profile should be used for the resulting files;
- **Which episodes** it downloads (see below).

Disabling a profile keeps its configuration but stops it from automatically selecting new downloads.

## Which episodes

Everything that decides which episodes a profile downloads is one list of filters, written as sentences you can read
from top to bottom:

> Only download if the **season** is **Season 3** or **upcoming seasons**
> Only download if the **episode type** is **Video** or **Livestream**
> Skip if the **title** contains the word “trailer” or “teaser”
> Only download the **latest 25** episodes, and delete older ones

Filters apply from top to bottom, and each filter only looks at the episodes the filters above it let through. In the
example, the latest 25 are the latest 25 Videos and Livestreams of Season 3 that aren't trailers. Drag a filter by its
handle to change the order, or open it and use the arrow buttons.

The number next to a filter says how many of the collection's indexed episodes it leaves out, and the bottom line says
how many are left, for example **37 of 412 indexed episodes will be downloaded**. **Show which** lists every episode,
and for each one that won't be downloaded, the filter that left it out. These numbers load after the page, so a large
collection never makes the page wait.

While you add a collection, it has no indexed episodes yet. The counts and the title and description tests then use
the collection's newest episodes instead, as many as the site gives in one cheap lookup (at least 5), for example
**14 of 15 newest episodes would be downloaded**. Nothing is saved until you finish adding the collection.

### A new profile

A new profile starts with these filters, which you can change, move or remove:

- for a seasonal collection, its **latest season and upcoming seasons**;
- the **episode types** the Source downloads by default. The types come from the show's Source: The Daily Wire has
  Episode, Ep. Extra, Trailer and Auxiliary, and YouTube has Video, Short and Livestream;
- the **latest 25 episodes**, deleting older ones.

Without any filters, a profile downloads every episode. **Add filter** adds a filter where its kind usually goes:
seasons at the top, episode types below them, dates at the bottom, and every other filter just above the dates. Click
the pencil on a filter to change it, and **Done** to fold it back into its sentence. An open filter starts with two
dropdowns that read as the start of its sentence, such as **Only download** if **title**: what the filter does, and what
it looks at.

### What a filter does

- **Skip** leaves out the episodes that match.
- **Only download** leaves out the episodes that *don't* match.
- **Keep** never stops a download. Wherever it is in the list, it protects the downloads it matches from being deleted,
  so you can, for example, keep every episode with “interview” in its title forever while the rest rotate out.

### What a filter looks at

- **Episode type**: any of the types you choose.
- **Season**: any of the seasons you choose. Choose **Upcoming seasons** too to have seasons the collection gets later
  added to the filter.
- **Title** or **description**, using the regular expression editor. You don't need to know regular expressions: the
  Contains and Any of these tabs write one for you, and the tester shows which of the collection's episodes match.
- **Duration**: shorter or longer than a length you choose. An episode whose length isn't known yet is never left out by
  a duration filter.
- **Published** and **downloaded**, the date filters below.

Changing filters later only affects episodes that aren't downloaded yet, apart from what a date filter deletes. An
episode a filter skips says **Skipped by filter** on the collection page and on its own page, where **Download anyway**
downloads it once by hand.

### Date filters

A profile has at most one **published** filter and one **downloaded** filter. They can **Only download** or **Keep**;
skipping by date isn't offered.

A **published** filter looks at when an episode came out:

- **the latest … episodes**: the newest episodes that reach this filter;
- **episodes published in the last … days**;
- **episodes published since a date**: VODLoft starts archiving from that date and keeps downloading everything newer.
  Older downloads are never deleted because of it.

A **downloaded** filter keeps each download for a number of days, counted from the day it was downloaded, however old
the episode already was. Only episodes published within that many days are downloaded. This is how Pinchflat's
retention works.

As a **Keep** filter, a date filter protects downloads instead: **Keep the latest 10 episodes** keeps those ten whatever
the other filters say.

### Deleting downloads

Only an **Only download** date filter deletes downloads, and only with its **And delete them …** switch on. It then
removes downloaded files that fall outside it: on **published**, once an episode is no longer among the latest or was
published longer ago than the window; on **downloaded**, once it was downloaded longer ago. When a download is deleted,
its download record and download history go as well, so it no longer appears on the Downloads page.

Downloads you keep, and downloads a Keep filter matches, are never deleted. Downloads of episodes that can't be
downloaded any more, for example because the Source removed them, are never deleted either.

Leave the switch off if you only want the date filter to decide which new episodes are downloaded while keeping older
files already on disk.

### Keeping a download

The pin button next to a download on an episode's page keeps that one download: no date filter deletes it. Click it
again to let the date filter delete it as usual. Kept downloads are still listed and can still be deleted by hand.

## Upgrade check

A download isn't always the best version of an episode. YouTube adds higher resolutions hours after an upload,
SponsorBlock segments come in over the days after it, and subtitles get added later. The Daily Wire sometimes edits an
episode after it is out, such as cutting a long live stream down to its highlights. The **Upgrade check** card, under
Which episodes, downloads an episode again after a while, but only when something you care about changed.

What the card shows depends on the Collection's site, and on the Source that downloads it. The Daily Wire has countdown
downloads and checks for a different length; YouTube checks for a higher resolution, SponsorBlock segments, subtitles
and the preferred codec; other sites yt-dlp downloads check for all of those except SponsorBlock. A Daily Wire show
added through yt-dlp gets what yt-dlp offers any site. A site with nothing to check has no Upgrade check card at all.
Subtitles only show when the Local Media Profile stores them.

- **Download again when a better version is out** turns the check on. New profiles have it on.
- **Check after … days**: how long after downloading the first check happens. 7 days by default.
- **How often**: **Once, then stop**; **Twice, again after 30 days**; or **Every … days, up to 3 times**, which with
  7 days checks on day 7, 14 and 21. Every choice stops early once an episode can't get any better.
- **Better means**: a higher resolution (up to the Local Media Profile's quality), new SponsorBlock segments of the types
  you mark or cut out, new subtitles in a language the Local Media Profile asks for, or the preferred codec (the first
  allowed codec in the Local Media Profile). A higher resolution and new SponsorBlock segments are on by default.
  For The Daily Wire it is **a different length**: longer or shorter by more than the minutes you set, 5 by default.

The check first asks the site what it has now, and only downloads when one of your improvements is there. The old
file stays until the new one is complete. Kept downloads are checked too: Keep protects a download from being deleted,
not from a better copy. Downloads made after the check is turned on are the ones that get checked.

When a metadata refresh shows that one of your improvements changed, the check runs right away instead of waiting
for its schedule. This includes a refresh you start yourself. Today a refresh can only tell a different length, such as
The Daily Wire listing a new length for an episode; for anything else the check keeps its own schedule. Before downloading again, VODLoft measures the stream The Daily Wire actually
serves, so a wrong length on the site does not cause a download. A countdown download waits for its final version
first. Each download remembers how long its file is; VODLoft reads this from the files you already had when you
updated, and checks Daily Wire downloads of the last 30 days right away.

The episode's download history shows each check and what it found, such as **Better version found: Higher resolution
(720p → 1080p)** or **Different length (7h 12m → 3h 31m)**. On the Collection page, an episode says when it will be checked, or that it was upgraded or checked.

### Countdown and final versions

Some Daily Wire episodes appear with temporary countdown media before the final episode is ready. Both choices are in
the Upgrade check card:

- **Download with countdown** allows VODLoft to download that early version.
- **Download again as the final version** replaces the early version as soon as the final media is out.

If you only want the finished episode, leave countdown downloading disabled.

## YouTube

Download Profiles of YouTube Collections have a YouTube section under Which episodes, with auto-generated subtitles and SponsorBlock.

### Auto-generated subtitles

This setting only appears when the Local Media Profile stores subtitles.

**Use auto-generated subtitles** never, only when there are no real ones (the default), or always. YouTube makes subtitles automatically for most videos; they follow the subtitle languages of the Local Media Profile. When the Local Media Profile saves no subtitles, the choice isn't available and the form links to that profile instead.

- **Only when there are no real ones** uses an auto-generated subtitle for a language that has no subtitle a person made.
- **Always** also adds it next to a real one, as its own track marked auto-generated (`Episode.nl.auto.srt` beside the media).

### SponsorBlock

[SponsorBlock](https://sponsor.ajay.app) is a community database of parts of YouTube videos: sponsor reads, "like and subscribe" reminders, intros and so on. Switch it on, then choose for each type of part:

- **Keep**: left as it is.
- **Chapter**: becomes a named chapter that your player can skip. Nothing is removed, so this is the safe choice.
- **Cut out**: removed from the file. This is final; the cut part isn't kept anywhere.

The types are Sponsor, Self-promotion, Interaction reminder, Intro, Outro, Preview and recap, Filler and Non-music section. SponsorBlock's Highlight is always a chapter. A new YouTube Download Profile makes chapters of sponsors, intros and outros, and keeps everything else. Profiles from before VODLoft 0.7.0 start with SponsorBlock off.

Most parts are submitted in the days after a video comes out, so a download made right after upload may find few of them. The episode page shows what a download found on a timeline: each part, whether it became a chapter or was cut out, and how much shorter the file is.

An episode you download by hand follows the Collection's Download Profile for the same Local Media Profile.

## Using multiple profiles

Multiple Download Profiles are useful whenever format or retention differs. Each one uses its own Local Media Profile.
Examples include:

- audio for all regular and auxiliary episodes with no limit;
- 1080p video for regular episodes, latest five only;
- a high-quality archive profile alongside a smaller podcast-friendly copy.

Because each profile points to a Local Media Profile, several versions of the same episode can coexist without being treated as the same local file.

## Download Profiles and RSS feeds

An RSS Stream Profile can use files created by any suitable Download Profile. It does not need to be linked to one specific Download Profile.

A common setup is:

1. keep recent episodes downloaded locally;
2. enable **Use Downloads** in the RSS profile;
3. also enable **Use DailyWire stream** as a fallback for older episodes that are no longer stored locally.

See [[Podcast-RSS-Feeds]].

## Global download controls

Settings such as maximum simultaneous downloads, retry attempts, timeout, direct-versus-temporary download behavior, file verification, FFmpeg remuxing, and filename compatibility are configured globally under **Settings → Downloads**.

A Local Media Profile can override the system-wide direct/temporary download behavior when needed. See [[Local-Media-Profiles]] and [[Settings#downloads]].