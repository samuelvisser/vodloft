# Local Media Profiles

A Local Media Profile describes **the local file VODLoft should create**. It controls the preferred format, where the file is stored, and whether incomplete download work is written directly in the library or staged elsewhere first.

Download Profiles use Local Media Profiles for automatic collection downloads. Movies and single videos use Video Local Media Profiles, and their downloads are started manually.

## The profile form

The form is split into sections: **Profile**, **Quality**, **Files and metadata**, **Subtitles**, **SponsorBlock** and
**Output path**. Click a section to open or fold it. A folded section shows its current choices in one line, so you can
check a profile without opening everything. A new profile opens Profile, Quality and Output path; the other sections
start from good defaults. When saving fails, the sections with a problem open by themselves. Subtitles and SponsorBlock
only show when one of the profile's sites has them.

### Following Settings

Some choices can follow **Settings → Downloads**: the thumbnail, metadata, poster and background, how a download is
written, and filename restrictions. While a choice follows Settings, it has a blue **Follows Settings** badge, and its
checkboxes have a dashed blue border that shows the value from Settings. Changing Settings later changes these
profiles too. Click the badge, a box or **Change** to choose for this profile only. The badge then turns into **Use Settings**,
which makes the choice follow Settings again.

### Files and metadata

The grid at the top chooses where the **thumbnail** and the **metadata** (title, date and description) are saved:
**inside the media**, **beside the media** (an image file, or an NFO file next to the media), both, or neither. With an
NFO file, **Kodi-safe NFO text** replaces emoji and other characters Kodi cannot show with □. Collection profiles also
have **show and season NFO files** (`tvshow.nfo` and `season.nfo`, for Jellyfin, Emby and Kodi) and the **poster and
background**, which are saved in the collection root shown under the output template's example, together with a
poster for each season a playlist fills (see [[Collection-Artwork]]). **Date files by publish date** gives files the
date the episode came out instead of the date it was downloaded.

**Save the site's info file** keeps everything yt-dlp knows about a video as an `.info.json` file beside the media,
for other programs that read it. The form only offers it when the profile is for a site VODLoft downloads with yt-dlp,
such as YouTube or NPO Start.

A Collection profile that writes NFO files also chooses what **each episode is**: an **episode of a show**, or a
**music video**. A music video gets a `musicvideo` NFO with its artist and title instead of a show, season and episode
number, so Jellyfin, Emby and Kodi keep it in a Music Videos library. The artist is the name of the collection's
creator, so put an artist's music video collection under the artist (see
[[Collections-and-Library#music-videos]]).

### Your own title and description

A Collection profile can give every episode a **title** and **description** of its own in its NFO file and in the
metadata inside the media. Both are templates with the same variables as the output path, plus `description` for the
site's own description. `{{ date }} - {{ title }}` puts the date in front of every title, for example. Leave them empty to
keep what the site gives. They change the metadata only, not the file name, and a template that comes out empty keeps
the site's text. They are written in the same editor as the output path, which suggests variables as you type, and each
shows what it gives the example episode picked under **Output path**.

## Collection, Music and Video profiles

### Collection profiles

Collection profiles can use:

- 4K video;
- 1080p video;
- 720p video;
- audio only.

A Collection profile also has an **Available for** setting. This controls where VODLoft offers the profile in the interface: for Podcasts, for Series, or for both.

### Music profiles

Music profiles store the tracks of **Music** collections, and Music collections take no other kind of profile. A Music profile downloads audio only, as M4A, Opus, MP3 or FLAC, and tags every file the way music players expect:

- the **album** is the episode's season, such as a playlist or album the collection holds, or else the collection's title;
- the **artist** and **album artist** are the creator the collection belongs to, or else its author;
- the **track number** is the episode's number in its season.

The thumbnail goes inside the file as its cover art, cut to a square from the middle. Opus files take tags but no cover art. A new Music profile starts with the **Music library** layout, `Artist/Album/01 - Title`, which Plex, Jellyfin, Navidrome and most music players read; the `artist`, `album`, `track_number` and `track_number_padded` variables let you build your own.

FLAC keeps exactly what the site sends. Sites such as YouTube send compressed audio, so a FLAC file is larger but sounds no better than M4A or Opus.

### Video profiles

Video profiles store what you add on its own, outside any collection: single videos, and movies with their extras such as trailers. They can use any video quality from 360p to 8K, or audio only. When a site does not offer the chosen quality, VODLoft downloads the best quality below it.

One profile can hold both videos and movies, but movies usually belong in a folder layout of their own. New installations start with two: **VODLoft Videos** for every site, and **VODLoft Movies**, which is only offered for The Daily Wire's movies. A movie and its extras always use the same profile, so its output template must keep them apart (see [Movies and extras](#movies-and-extras)).

### Sites

Every profile has a **Sites** setting: the sites, such as YouTube or The Daily Wire, whose media it is offered for. Remove a site to stop offering the profile for media from it; media the profile already downloaded stays where it is.

New profiles start with every site VODLoft knows, plus **Include upcoming sites**. With that option, a site VODLoft sees for the first time, for example when you add a link from a new site, is added to the profile's sites automatically. You can still remove it later. A profile meant only for movies leaves it off, so new sites never join it.

## Download behavior

**While downloading**, under Files and metadata, chooses how downloads using the profile are written:

- **System** — follow the current system-wide default from **Settings → Downloads**.
- **Save directly to downloads** — perform the download and processing in the destination area. This avoids a final publication copy, but can be much slower when the destination is network storage.
- **Save to temporary folder first** — keep incomplete download and processing work in the configured temporary folder, then place the completed file in the media library.

Temporary mode is the system default. It is useful both when Plex, Jellyfin, or another application actively watches the destination folder and when the media library is on network storage, because remuxing and metadata embedding can remain on local temporary storage.

The temporary folder may be on different storage from the final library. Configure the system default and temporary location under [[Settings#downloads]].

## Subtitles

Local Media Profiles can save the subtitles a video has, from The Daily Wire and from every site yt-dlp downloads from, such as YouTube.

**Save subtitles** has two boxes, **Inside the media** and **Beside the media**. Tick one, both, or neither to save no subtitles.

- **Inside the media** adds them as tracks you can pick in your player, in MP4 and MKV files.
- **Beside the media** saves SRT files next to the media, such as `Episode.en.srt`. Subtitles beside the media are always SRT.

**When several languages are available** chooses one of:

- **Every language on the list**: one file per language on the list, when the site has it.
- **Only the first one available**: one subtitle per episode: the first language on the list that the video has.
- **Every language the site offers**: whatever the video has. On YouTube this can be dozens when auto-generated subtitles are included.

Below it, **Subtitle languages** is a list in order of preference. Drag a language or use its arrows to move it, and add one at the bottom of the list. The first language on the list that an episode has becomes the default subtitle track in players that read it. New profiles start with English. Profiles from before VODLoft 0.7.0 keep downloading every language the site offers.

With **Every language the site offers**, the list is called **Default track language**: only its first language counts, and it becomes the default track when an episode has it. The other languages are grayed out but stay on the list for when you choose something else again. Leave the list empty to mark no default track.

**Use auto-generated subtitles** never, only when there are no real ones (the default), or always. Only sites downloaded with yt-dlp, such as YouTube, make subtitles themselves, so this setting only shows when the profile stores subtitles and one of its sites has them; its help names those sites. They follow the subtitle languages above.

- **Only when there are no real ones** uses an auto-generated subtitle for a language that has no subtitle a person made.
- **Always** also adds it next to a real one, as its own track marked auto-generated (`Episode.nl.auto.srt` beside the media).

**Series** and Collection profiles available for **Podcasts and Series** start with subtitles beside the media, and so does the **VODLoft Movies** profile. **Podcast-only** profiles and new **Video** profiles start without subtitles.

Forced subtitles use names such as `Movie Name.en.forced.srt`, and auto-generated ones `Episode.nl.auto.srt`. The default track beside the media is named like `Episode.en.default.srt`: Jellyfin and Emby pick it by default, while Plex and Kodi go by the subtitle language set in the player. Plex and similar media servers find these files automatically. NPO Start has no subtitles yet, so a profile only for NPO Start has no subtitle settings. A video without subtitles downloads as before, and a subtitle that fails never stops the download. Audio-only downloads never embed subtitles. An HLS bundle keeps embedded subtitles inside it as WebVTT, the format HLS players read, so a podcast app or player streaming the bundle can offer them. Subtitles beside an HLS bundle are ordinary SRT files: the bundle does not refer to them, so deleting one never breaks it.

## Settings only some sites have

Some settings only do something on some sites, such as auto-generated subtitles and SponsorBlock. They only show when
one of the profile's [Sites](#sites) has them, and their help says which sites they apply to. Each has one value for
the whole profile: a site that doesn't have the setting simply does without it. These settings apply to every download
with the profile, from a Collection's Download Profile and by hand alike. A new profile starts with the
per-site defaults under **Settings → Downloads** (see [[Settings#per-site-defaults]]).

Auto-generated subtitles and SponsorBlock used to be on each Download Profile. When you upgrade, each Local Media
Profile takes what most of its Download Profiles had.

## SponsorBlock

[SponsorBlock](https://sponsor.ajay.app) is a community database of parts of YouTube videos: sponsor reads, "like and subscribe" reminders, intros and so on. It only applies to YouTube, so it only shows when the profile is offered for YouTube. Switch it on, and the profile shows in one sentence what happens to each type of part. **Edit segments** opens the choices for each type of part:

- **Keep**: left as it is.
- **Chapter**: becomes a named chapter that your player can skip. Nothing is removed, so this is the safe choice.
- **Cut out**: removed from the file. This is final; the cut part isn't kept anywhere.

The types are Sponsor, Self-promotion, Interaction reminder, Intro, Outro, Preview and recap, Hook and greetings, Filler and Non-music section. Two more can only be kept or made a chapter, because there is nothing to cut out:

- **Highlight**: the one moment viewers mark as where the video really gets going.
- **Viewer chapters**: chapter titles viewers wrote, mostly for videos without chapters of their own. When other types are chapters too, they all share one list: a part that falls inside a viewer chapter splits it, and the overlap is named after both. On a video that has its own chapters, the two sets of titles mix, so this starts as Keep.

A new profile makes chapters of sponsors, intros, outros and the highlight, and keeps everything else. Saving a profile that keeps every type turns SponsorBlock off, and a new profile starts with it off when your defaults for YouTube keep every type.

Most parts are submitted in the days after a video comes out, so a download made right after upload may find few of them. When a download found parts, the episode page shows them on a timeline: each part, whether it became a chapter or was cut out, and how much shorter the file is.

## Chapters

Many videos split themselves into named chapters, such as "Intro" or "Q&A". On sites VODLoft downloads with yt-dlp,
such as YouTube, a profile has two chapter settings:

- **Keep the video's chapters** writes them into the file, so your player can jump between them. MP4, MKV and M4A
  files can hold chapters. It is on for a new profile.
- **Cut out chapters by title** removes every chapter whose title matches one of your lines from the file. Each line is
  a regular expression, matched anywhere in the title: `^Sponsor` cuts chapters whose title starts with "Sponsor", and
  `(?i)` at the start ignores upper and lower case. Cutting is final, like cutting with SponsorBlock.

A file that is shorter because chapters were cut out doesn't count as a different length for the upgrade check. An HLS
bundle keeps every chapter as it is.

## Quality

Each site offers its own choices, and a profile shows what its sites offer together. The Daily Wire has fixed versions: 480p, 720p and 1080p video, its HLS bundle and audio, with nothing else to choose. Sites downloaded with yt-dlp, such as YouTube, and NPO Start offer every resolution and every choice below. Of those, only YouTube also has an HLS bundle. The choices after **Download** only show when one of the profile's sites has them, and their help names the sites they apply to.

**Download** chooses video up to a ceiling: 360p, 480p, 720p, 1080p, 1440p, 4K or 8K. VODLoft downloads the highest resolution the site has up to that, and otherwise the lower ones. **Audio only** downloads no video. Collection profiles for The Daily Wire and YouTube also have **HLS bundle**: several resolutions kept together, so a podcast app can pick the one that suits its connection. The Daily Wire's bundle has 480p, 720p and 1080p, and YouTube's has 360p, 720p and 1080p in H.264 with its M4A audio, as far as the video has them. Codec and container choices don't apply to it, and SponsorBlock segments are only marked as chapters, never cut out. A profile for several sites can choose what only one of them has: the others then get the nearest they have, such as 1080p video for an HLS bundle.

**Optimise for** chooses which codecs and container are used:

- **Compatibility**: H.264 video and AAC audio in MP4. Plays on every device, also older TVs. Above 1080p there is rarely H.264, so a 1440p or 4K profile usually gets 1080p with this goal.
- **Quality**: AV1, then VP9, then H.264, with Opus audio, in MKV.
- **Small files**: the same codecs, preferring the smaller of two versions.
- **Your own**: drag the codecs into your order and switch off the ones you never want. Choose MP4 or MKV and Opus or AAC yourself. When none of your codecs exists for an episode, VODLoft takes the best version there is, or skips the episode and says why.

Changing a codec, the container or the audio codec while a goal is chosen turns it into **Your own**. Choosing a goal again replaces your order with that goal's.

**Audio format**, for Audio only: **M4A** (plays everywhere, including podcast apps), **Opus** (smallest, not every podcast app plays it) or **MP3** (for very old players). Music profiles can also choose **FLAC**. Opus files get their metadata inside, and their thumbnail beside them.

**Audio language** picks a dubbed audio track when a video has one. **Original** keeps the language the video was made in.

Profiles from before VODLoft 0.7.0 keep what they downloaded: up to their resolution with Compatibility, and a 4K profile with H.264 first but every codec allowed.

A profile represents one local variant. If you want both audio and 1080p copies of the same episode, create separate Local Media Profiles and use them from separate Download Profiles.

## Output templates

The output template controls the folder structure and filename. VODLoft uses Jinja variables so one template can produce a unique path for every episode, movie, or extra.

A simple collection example is:

```jinja
/downloads/{{ collection_title }}/{{ episode_title }}.ext
```

A media-server-friendly series example is:

```jinja
/downloads/TV Shows/{{ collection_title }}/Season {{ season_number }}/{{ collection_title }} - {{ episode_label }} - {{ title }}.ext
```

`.ext` is a VODLoft placeholder. It is replaced with the extension that matches the file VODLoft actually produces.

### Path requirements

After Jinja is evaluated, the output path must:

- begin with `/downloads/`;
- end with `.ext`.

Most templates should simply begin with `/downloads/`. Advanced templates may place Jinja setup statements before it as long as those statements do not output any text.

For example:

```jinja
{% set folder = collection_title %}/downloads/{{ folder }}/{{ episode_title }}.ext
```

The `/downloads/` prefix maps to VODLoft's configured **Download root**. In a normal Docker installation that is the mounted media directory.

### Use the editor preview

The Local Media Profile editor includes a variable picker and path preview. Use those rather than memorizing the full reference below. The preview is especially helpful when optional values or Jinja conditionals are involved.

The preview starts on an episode of a collection that uses the profile, when one does, and you can pick any other
episode. While you
add a collection, it starts on one of that collection's newest episodes, which VODLoft looks up in the background
without saving them. Some numbers are only known once the collection is saved and all of its episodes are indexed, such
as `episode_index` and custom indexes, so the preview shows their names in brackets, like `[episode_index]`, until then.

## Optional values and conditionals

Some metadata, such as a release date, may not exist for every item. Missing values are empty, so Jinja conditionals can omit the punctuation or folder that belongs with them.

Example:

```jinja
/downloads/{{ collection_title }}/{{ episode_title }}{% if year %} ({{ year }}){% endif %}.ext
```

### Custom date formatting

Most of our date variables have conveniently preformatted values, such as `date` as `YYYY-MM-DD` and the separate `year`, `month`, and `day` values. When you need another representation, use the `strftime` filter:

```jinja
/downloads/{{ collection_title }}/{{ date | strftime("%d %B %Y") }} - {{ episode_title }}.ext
```

For a date of September 24, 2026, that expression renders as `24 September 2026`. The filter uses Python `strftime` directives, so formats such as `%Y%m%d`, `%d-%m-%Y`, and `%H-%M` are also available. It works with VODLoft's date, time, and datetime template values; a missing value remains empty.

### Text filters

Three filters work with Python regular expressions:

- `regex_replace(pattern, replacement)` replaces every match. Add a count, such as `regex_replace(' +', ' ', 1)`, to replace only the first matches.
- `regex_search(pattern)` is true when the pattern matches anywhere, for use in a condition.
- `regex_groups(pattern)` gives the groups of the first match as a list, or an empty list when nothing matches. A group that took no part in the match is empty.

For example, to keep only the part of a title before ` | `, and leave the title as it is when there is no ` | `:

```jinja
{% set parts = title | regex_groups('^(.+?) \| ') %}{% set title = parts[0] if parts else title %}
/downloads/{{ collection_title }}/{{ title }}.ext
```

`as_typed` names a value as if you typed it into the template, so the filename mode cleans it like typed text; see [Filename restrictions](#filename-restrictions). Use it as the last filter.

## Collection template variable reference

| Variable | Meaning |
| --- | --- |
| `collection` | Collection slug |
| `collection_title` | Collection title |
| `collection_author` | Collection author, host or channel name |
| `collection_site_id` | The id the site gives the collection, such as a YouTube channel or playlist id |
| `creator_title` | Name of the creator the collection belongs to, or empty when it belongs to none |
| `creator_handle` | The creator's handle, such as `@kurzgesagt`, when the site has one |
| `creator_kind` | What the site calls a creator, such as `YouTube creator` or `The Daily Wire host` |
| `section_title` | The playlist or show of the creator that the episode came from, such as `Shorts`; empty otherwise |
| `section_kind` | `feed` for Videos, Live or Shorts, `list` for a playlist or show, `item` for a single movie; empty otherwise |
| `artist` | Who the music is by: the creator's name, else the collection's author |
| `album` | The episode's season when it holds one playlist or album, else the collection's title |
| `track_number` | The episode's number on its album, such as `3` |
| `track_number_padded` | The track number with two digits, such as `03` |
| `season` | Season slug, or empty when unavailable |
| `season_name` | Season name, or empty when unavailable |
| `season_index` | VODLoft's internal persistent season index |
| `season_type` | `normal` or `extra` |
| `season_number` | Stable media-library season number; Extras seasons use `0` |
| `episode` | Episode slug |
| `episode_title` | Episode title |
| `title` | Episode title |
| `episode_site_id` | The id the site gives the episode, such as a YouTube video id |
| `episode_uploader` | Who uploaded the episode, when the site says; empty otherwise |
| `duration_seconds` | Episode duration in whole seconds |
| `dw_episode_number` | Raw episode number exactly as returned by The Daily Wire |
| `episode_type` | `ep` for a normal episode on every site; other types depend on the site: `ep-extra`, `aux` and `trailer` on The Daily Wire, `short` and `livestream` on YouTube |
| `episode_extra_type` | `other` or `trailer` for attached episode extras; empty otherwise |
| `episode_number` | The episode's number; an episode extra has its episode's number, and other types count on their own |
| `extra_index` | VODLoft's number for an extra, counted across the whole collection; empty for normal episodes (see below) |
| `episode_sub_number` | The Daily Wire fractional/sub-episode number for `ep-extra`; empty otherwise |
| `episode_label` | Canonical identifier label without the type prefix |
| `episode_identifier` | Full VODLoft episode identifier; unique within the collection |
| `episode_published_date` | Publication date as `YYYY-MM-DD` |
| `episode_published_time` | Publication time as `HH:MM:SS` |
| `episode_published_datetime` | Publication date and time |
| `date` | Generic episode date value |
| `time` | Generic episode time value |
| `datetime` | Generic episode date/time value |
| `year` | Four-digit year |
| `month` | Month value |
| `day` | Day value |
| `hour` | Hour value |
| `minute` | Minute value |
| `second` | Second value |

`season_number` is the value intended for media-library season numbering. It ignores Daily Wire Extras collections and remains stable if another Extras season appears later. `season_index` is used by VODLoft to order the seasons themselves and is unique for a season within a collection.

VODLoft preserves The Daily Wire's episode number for full episodes and attached episode extras. It only invents collection-wide numbers for auxiliary content and standalone collection trailers. Extras seasons use `season_type == 'extra'` and `season_number == 0`, which is handy if you want specials to end up in a different 'Specials' directory, for example.

Two more date variables number days within the year: `day_of_year` is `001` on 1 January, and
`day_of_year_reversed` counts down to `001` on the last day, so the newest episode sorts first.

### Long names

Most file systems allow at most 255 bytes in one file or folder name. When a value such as a long title would make a
name longer than that, VODLoft shortens that value, and keeps the rest of the name and the extension as they are. The
editor's preview warns when a name will be shortened.

### The extra index

An extra is an episode of an Extras season, or an episode of any type other than `ep`: auxiliary episodes, trailers, episode extras, YouTube Shorts and livestreams. VODLoft numbers every extra of a collection in one count, in episode order, and keeps that number in `extra_index`. So no two extras share a number, which is what a media server's Specials season needs. The Media Server presets use it:

```jinja
{% set is_extra = season_type == 'extra' or episode_type != 'ep' %}
{% if is_extra %}S00E{{ "%02d"|format(extra_index|int) }}{% else %}S{{ season_num }}E{{ ep_num }}{% endif %}
```

An extra keeps its number, so its files keep their names. A new extra takes the next number, and an episode that stops being an extra leaves a gap.

## Custom Indexes

A Custom Index numbers the episodes a template picks out, such as the featurettes of a collection, so they can have their own running number. Add it with **Indexing values** in a Collection profile: give it a name and a key, such as `featurettes`. Then use the key in the template:

```jinja
{% if episode_type == 'aux' %}{% set n = 'featurettes' | custom_index %}/downloads/{{ collection_title }}/Featurettes/Featurette {{ n }}.ext{% else %}/downloads/{{ collection_title }}/{{ title }}.ext{% endif %}
```

Every episode that reaches the key gets the next number, in episode order, starting at 1. An episode that doesn't reach it gets none. VODLoft works the numbers out again whenever the template or the episodes change, and can rename the files.

Three options change the numbering:

| Option | Effect | Example |
| --- | --- | --- |
| `per=` | Counts each group on its own. A list groups by all its values together. | `custom_index(per=season_number)` starts again at 1 in every season |
| `start=` | The first number, instead of 1. | `custom_index(start=0)` gives 0, 1, 2 |
| `step=` | How far each number is from the last, instead of 1. | `custom_index(start=10, step=10)` gives 10, 20, 30 |

`start=` and `step=` must be whole numbers, and `step=` can't be 0. `per=` takes the episode's own values, such as variables and pure filters like `lower`, but not another Custom Index.

### Keep numbers

Normally the numbers follow episode order, so an older episode found later moves the numbers after it up by one, and those files get renamed. Turn on **Keep numbers once given out** for an index to keep every number it gives. A newly found episode then takes the next number after the highest one in its group, wherever it falls in episode order. Turning the option off numbers everything in order again.

## Moving episodes to another profile

To retire a Collection profile, or to give its episodes another layout, open the profile and choose **Actions → Move episodes to another profile**. Pick the profile to move to, and VODLoft shows per collection which episodes move and where their files will go. Untick a collection to leave it where it is.

What a move does:

- The episodes belong to the other profile from then on. Their download history, quality and **kept** mark come along.
- Their files, and the subtitles, thumbnails and NFO files next to them, are renamed into the other profile's layout. Folders left empty are removed.
- When the other profile writes NFO files or thumbnail images and an episode has none yet, VODLoft adds them. Subtitles are not added: they come with a redownload.
- Nothing is overwritten. An episode the other profile already has, a path another file already uses, a missing file or a running download stays where it is. The clock icon next to such an episode opens its download history, where you can delete the leftover copy.

Download Profiles pause while their collection's files move. When the collection's Download Profile uses the old profile and the new one has none, VODLoft offers to move it along, so it keeps managing the same episodes. Without that, it would download the moved episodes into the old profile again. When the new profile already has a Download Profile for the collection, the moved episodes join it, and the preview warns about episodes it would delete as older episodes.

Once nothing downloaded is left on the old profile and no Download Profile uses it, the dialog offers to delete it.

## Movies and extras

For a movie, a Video profile's template has two groups of values:

- variables beginning with `movie_` always describe the parent movie, and are empty for a single video;
- variables without that prefix describe the actual item being downloaded, which can be either the main movie or a specific movie extra.

This makes it possible to keep all extras inside the movie's folder while giving each item its own filename.

Example:

```jinja
/downloads/Movies/{{ movie_title }}{% if movie_year %} ({{ movie_year }}){% endif %}/{{ media_type }} - {{ title }}.ext
```

A Video profile's template must use an item-specific value such as `{{ title }}`, `{{ slug }}`, or `{{ media_type }}` so the main movie and an extra cannot resolve to the same output path.  
VODLoft never overwrites existing files if the same output path is generated for multiple items, but it is
still a case that should be avoided to make it obvious what content is in a file.

### Parent movie variables

| Variable | Meaning |
| --- | --- |
| `movie_slug` | Parent movie slug |
| `movie_title` | Parent movie title |
| `movie_extended_title` | Parent movie extended title |
| `movie_author` | Parent author/creator value |
| `movie_mature_rating` | Parent mature rating |
| `movie_duration_seconds` | Parent duration in seconds |
| `movie_date`, `movie_time`, `movie_datetime` | Parent release-date values |
| `movie_year`, `movie_month`, `movie_day` | Parent release-date components |
| `movie_hour`, `movie_minute`, `movie_second` | Parent release-time components |

### Current item variables

These describe the main movie or the specific extra currently being downloaded:

| Variable | Meaning |
| --- | --- |
| `slug` | Item slug |
| `title` | Item title |
| `extended_title` | Item extended title |
| `author` | Item author when available |
| `mature_rating` / `rating` | Item rating when available |
| `duration_seconds` | Item duration |
| `media_type` | `movie` for the main feature, or the extra type |
| `source` | Name of the site the movie comes from |
| `date`, `time`, `datetime` | Item date/time values |
| `year`, `month`, `day`, `hour`, `minute`, `second` | Item date/time components |

The Daily Wire does not always provide every field for movie extras. Use conditionals around values that may be empty.

## Videos

For a single video, a Video profile's template has these values. The `movie_` variables are empty.

| Variable | Meaning |
| --- | --- |
| `title`, `extended_title` | Video title |
| `slug` | The site's own id for the video |
| `author` | Channel or uploader, when the site names one |
| `source` | Name of the site the video comes from |
| `duration_seconds` | Video duration in seconds |
| `media_type` | `video` |
| `date`, `time`, `datetime` | Upload date/time values |
| `year`, `month`, `day`, `hour`, `minute`, `second` | Upload date/time components |

Titles are not unique, so include `{{ slug }}` in the filename. Sites do not always give an uploader or an upload date, so fall back or use a conditional:

```jinja
{% set output_date = date ~ ' - ' if date %}/downloads/videos/{{ author or source }}/{{ output_date }}{{ title }} [{{ slug }}].ext
```

## Filename restrictions

Each profile's **Filename restrictions** setting controls how file and folder names are made safe. **System**, the default, uses the mode in **Settings → Downloads**; choose a mode for one profile to name its files differently, such as an ASCII-only copy for a car stereo. Files you already have keep their names until you rename the profile's files. The three modes follow yt-dlp, so files are named like yt-dlp and Pinchflat name them. Each value a template fills in, such as a title, is cleaned the way yt-dlp cleans it. Text you type in the template itself is made safe too, and the editor says when typed text has a character the mode will replace. The preview shows the result.

The examples show `Q&A: Is AI "conscious"? | Ep. 12/13` in each mode.

### Minimal restrictions (`unrestricted`)

Like yt-dlp's `--no-windows-filenames`. Only a `/` in a value changes, to the look-alike `⧸`, so a value can never add a folder. Control characters are dropped. `Q&A: Is AI "conscious"? | Ep. 12⧸13`

### Windows-compatible filenames (`windows`) — default

Like yt-dlp's default, which Pinchflat uses. `: " * < > ? | / \` become the look-alikes `： ＂ ＊ ＜ ＞ ？ ｜ ⧸ ⧹`, and a time such as `10:30` becomes `10_30`. Reserved Windows names such as `CON` and `NUL` get a `_` in front, trailing dots and spaces are removed, and control characters become `_`. `Q&A： Is AI ＂conscious＂？ ｜ Ep. 12⧸13`

### Restricted filenames (`restricted`)

Like yt-dlp's `--restrict-filenames`: ASCII letters, numbers, `.`, `_` and `-` only. Letters are spelled out in ASCII first, such as `ß` as `ss`, `Æ` as `AE` and `Ł` as `L`, curly quotes become straight ones and `…` becomes `...`; accents are then dropped. A colon becomes `_-`, and anything else becomes `_`. `Q_A_-_Is_AI_conscious_Ep._12_13`

Text you type in the template keeps its spaces and punctuation, as in yt-dlp and Pinchflat, and is only made ASCII: `Season 01/{{ title }}` gives `Season 01/Q_A_-_Is_AI_conscious_Ep._12_13`. A typed `: ` becomes ` - `, and `? " * < > | \` are removed or become `_`. To name a value like typed text, end it with `as_typed`: `{{ collection_title | as_typed }}` keeps `Mike Winger` as it is, where `{{ collection_title }}` gives `Mike_Winger`. A Pinchflat import uses it for a source's custom name, which Pinchflat doesn't restrict either.

A file name with nothing ASCII left, such as a Japanese title, becomes `no_ascii_file_name`. A second one in the same folder becomes `no_ascii_file_name_2`, and so on. The number stays with the file.

Use this only when another application or filesystem needs very simple filenames.

Files you already have keep their names until you rename a profile's files.

## Media server presets

**Start from a preset** above a Collection profile's output template fills in a layout that a media server reads well,
together with the matching metadata and NFO choices: **Plex**, **Jellyfin and Emby**, **Kodi**, **Audiobookshelf** for
audio, **Music library** for a Music profile, and **Music videos**, which files each video as `Artist/Title` with a
`musicvideo` NFO. You can change everything afterwards.

## Suggested layouts

A common arrangement is:

- one Collection video profile for Plex/Jellyfin;
- one Collection audio profile for podcast-style storage or Audiobookshelf;
- one Video profile for single videos;
- one Video profile for The Daily Wire's movies, with a conventional movie folder and item-specific extra names.

Local Media Profiles only control files VODLoft creates. Your media server can independently scan whichever subfolders you want.