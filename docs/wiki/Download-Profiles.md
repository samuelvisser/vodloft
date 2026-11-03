# Download Profiles

Download Profiles decide **which collection episodes VODLoft should download automatically**. The attached Local Media Profile decides the file format, download behavior, and output path. See [[Local-Media-Profiles]].

A collection can have more than one Download Profile. For example, you can keep audio for every episode while retaining video only for the newest five.

Movies do not use Download Profiles; movie downloads are started manually from the movie page.

## Common options

Every Download Profile lets you choose:

- whether the profile is enabled;
- which Local Media Profile should be used for the resulting files;
- **Which episodes** it downloads (see below).

Disabling a profile keeps its configuration but stops it from automatically selecting new downloads.

## Which episodes

Everything that decides which episodes a profile downloads sits in one section, written as sentences you can read
from top to bottom:

> Download **Video** and **Livestream** episodes
> published in the **last 90 days**, and delete them once they are older
> Skip if the **title** contains the word “trailer” or “teaser”
> Skip if the **duration** is shorter than **2 minutes**

Each line narrows the one above it. The number next to a line says how many of the collection's indexed episodes that
line leaves out, and the bottom line says how many are left, for example **37 of 412 indexed episodes will be
downloaded**. **Show which** lists every episode, and for each one that won't be downloaded, the line that left it out.

The first lines are built in and can't be removed:

- the **episode types**. The types come from the show's Source: The Daily Wire has Episode, Ep. Extra, Trailer and
  Auxiliary, and YouTube has Video, Short and Livestream;
- the **seasons**, for a seasonal collection;
- the **date window** (see Date options below).

Click the pencil on a line to change it, and **Done** to fold it back into its sentence. When you create a profile,
the built-in lines start open so you see them the first time.

### Your own filters

**Add filter** adds a line of your own. Every filter has an action and something it looks at:

- **Skip** leaves out the episodes that match.
- **Only download** leaves out the episodes that *don't* match.
- **Keep** never stops a download. It protects the downloads it matches from being deleted by the date window, so you
  can, for example, keep every episode with “interview” in its title forever while the rest rotate out.

A filter can look at the episode's **title** or **description**, using the regular expression editor (you don't need to
know regular expressions: the Contains and Any of these tabs write one for you, and the tester shows which of the
collection's episodes match), or at its **duration**: shorter or longer than a length you choose. An episode whose
length isn't known yet is never left out by a duration filter.

Changing filters later only affects episodes that aren't downloaded yet; it never deletes a download. An episode a
filter skips says **Skipped by filter** on the collection page and on its own page, where **Download anyway** downloads it
once by hand.

### Keeping a download

The pin button next to a download on an episode's page keeps that one download: the date window never deletes it. Click
it again to let the date window delete it as usual. Kept downloads are still listed and can still be deleted by hand.

## Which options a profile shows

The options follow how the collection identifies its episodes (its **Episode identification**, chosen when you add the collection), not whether it is a podcast or a series:

- a **Seasonal** collection filters by season first, and can use every date option below on top of that;
- a **Date-based** or **Numbered** collection uses the date options only.

If you change a collection's episode identification later, its Download Profiles follow: the season choice only counts while the collection is seasonal.

## Seasons

### Seasons to download

Select the known seasons that should be covered by the profile. Only selected episode types inside those seasons are eligible.

### Include upcoming seasons

Enable **Include upcoming seasons** when the same rules should automatically apply to seasons added later.

This is useful for an ongoing series where you do not want to edit the profile every time a new season appears.

Selecting all seasons in the UI also enables future seasons so the profile keeps following the complete series.

## Date options

### Limit by

Choose how many episodes the profile should consider. On a seasonal collection the limit counts only episodes in the chosen seasons:

- **No limits** — every eligible episode can be downloaded.
- **Date** — only episodes inside a recent number-of-days window are eligible.
- **Number of episodes** — only the newest selected number of eligible episodes are kept in the active window.

### Download starting from

When **No limits** is selected, you can optionally set **Download starting from** to establish a fixed cutoff date.

VODLoft will ignore eligible episodes older than that date and continue downloading new episodes published after it. Existing files are not deleted simply because they predate the cutoff.

This is useful when you want to begin archiving a collection from a particular date without downloading its complete history.

### Delete older episodes

When a rolling Date or Number of episodes limit is active, **Delete older episodes** can also remove downloaded files that fall outside that window. When retention removes an episode, its download record and download history are removed as well, so it no longer appears on the Downloads page.

With a Date limit you also choose when the clock starts:

- **After publication** deletes an episode once it was published longer ago than the window.
- **After downloading** keeps every download for the full number of days, counted from the day it was downloaded,
  however old the episode already was. This is how Pinchflat's retention works.

Downloads you keep, and downloads a Keep filter matches, are never deleted.

Leave it disabled if you only want the limit to control which new episodes are selected while keeping older files already on disk. Planned downloads that never produced a file are still discarded once they fall outside the active Number of episodes window.

### Countdown and final versions

Some Daily Wire episodes appear with temporary countdown media before the final episode is ready.

- **Download with countdown** allows VODLoft to download that early version.
- **Redownload final version** replaces the early version after the final media becomes available.

If you only want the finished episode, leave countdown downloading disabled.

## YouTube

Download Profiles of YouTube Collections have a YouTube section under Which episodes, with auto-generated subtitles and SponsorBlock.

### Auto-generated subtitles

This line only appears when the Local Media Profile stores subtitles.

**Use auto-generated subtitles** never, only when there are no real ones (the default), or always. YouTube makes subtitles automatically for most videos; they follow the subtitle languages of the Local Media Profile.

- **Only when there are no real ones** uses an auto-generated subtitle for a language that has no subtitle a person made.
- **Always** also adds it next to a real one, as its own track marked auto-generated (`Episode.nl.auto.srt` beside the media).

### SponsorBlock

[SponsorBlock](https://sponsor.ajay.app) is a community database of parts of YouTube videos: sponsor reads, "like and subscribe" reminders, intros and so on. Switch it on, then choose for each type of part:

- **Keep**: left as it is.
- **Chapter**: becomes a named chapter that your player can skip. Nothing is removed, so this is the safe choice.
- **Cut out**: removed from the file. This is final; the cut part isn't kept anywhere.

The types are Sponsor, Self-promotion, Interaction reminder, Intro, Outro, Preview and recap, Filler and Non-music section. SponsorBlock's Highlight is always a chapter. A new YouTube Download Profile cuts out sponsors, self-promotion and interaction reminders, and makes chapters of intros, outros and previews. Profiles from before VODLoft 0.7.0 start with SponsorBlock off.

Most parts are submitted in the days after a video comes out, so a download made right after upload may find few of them. The episode page shows what a download found on a timeline: each part, whether it became a chapter or was cut out, and how much shorter the file is.

An episode you download by hand follows the Collection's Download Profile for the same Local Media Profile.

## Using multiple profiles

Multiple Download Profiles are useful whenever format or retention differs. Examples include:

- audio for all regular and auxiliary episodes with no limit;
- 1080p video for regular episodes, latest five only;
- a separate video profile for one particular season;
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