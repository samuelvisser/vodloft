# Local Media Profiles

A Local Media Profile describes **the local file VODLoft should create**. It controls the preferred format, where the file is stored, and whether incomplete download work is written directly in the library or staged elsewhere first.

Download Profiles use Local Media Profiles for automatic collection downloads. Movies and single videos also use Local Media Profiles, but their downloads are started manually.

## Collection, Movie and Video profiles

### Collection profiles

Collection profiles can use:

- 4K video;
- 1080p video;
- 720p video;
- audio only.

A Collection profile also has an **Available for** setting. This controls where VODLoft offers the profile in the interface.

### Movie profiles

Movie profiles can use 4K, 1080p, or 720p video. The same profile can be used for the main movie and its extras, so its output template must keep those items distinct.

### Video profiles

Video profiles store single videos that you added on their own, outside any collection. They can use 4K, 1080p or 720p video, or audio only. When a site does not offer the chosen quality, VODLoft downloads the best quality below it. New installations start with a **VODLoft Videos** profile; on an existing installation, create one from **Profiles → Local Media Profiles**.

## Download behavior

Each Local Media Profile can choose how downloads using it are written:

- **System** — follow the current system-wide default from **Settings → Downloads**.
- **Save directly to downloads** — perform the download and processing in the destination area. This avoids a final publication copy, but can be much slower when the destination is network storage.
- **Save to temporary folder first** — keep incomplete download and processing work in the configured temporary folder, then place the completed file in the media library.

Temporary mode is the system default. It is useful both when Plex, Jellyfin, or another application actively watches the destination folder and when the media library is on network storage, because remuxing and metadata embedding can remain on local temporary storage.

The temporary folder may be on different storage from the final library. Configure the system default and temporary location under [[Settings#downloads]].

## Subtitles

Local Media Profiles can save the subtitles a video has, from The Daily Wire and from every site yt-dlp downloads from, such as YouTube.

**Subtitles** chooses where they are stored: not at all, inside the media, beside the media, or both.

- **Inside the media** adds them as tracks you can pick in your player, in MP4 and MKV files.
- **Beside the media** saves SRT files next to the media, such as `Episode.en.srt`. Subtitles beside the media are always SRT.

**Subtitle languages** is a list in order of preference. Drag a language or use its arrows to move it, and add one at the bottom of the list. **When several languages are available** chooses one of:

- **Every language on the list**: one file per language on the list, when the site has it.
- **Only the first one available**: one subtitle per episode: the first language on the list that the video has.
- **Every language the site offers**: whatever the video has. On YouTube this can be dozens when auto-generated subtitles are included.

The first language on the list becomes the default subtitle track in players that read it. New profiles start with English. Profiles from before VODLoft 0.7.0 keep downloading every language the site offers.

**Auto-generated subtitles** only exist on YouTube, so that choice is on each Download Profile of a YouTube Collection (see [Download Profiles](Download-Profiles#youtube)). When a Local Media Profile is used for YouTube Collections, a folded line below says per Collection whether auto-generated subtitles are downloaded, with a link to each Download Profile.

**Movies**, **Series** and Collection profiles available for **Podcasts and Series** start with subtitles beside the media. **Podcast-only** profiles and **Video** profiles start without subtitles.

Forced subtitles use names such as `Movie Name.en.forced.srt`, and auto-generated ones `Episode.nl.auto.srt`. Plex and similar media servers find these files automatically. NPO Start has no subtitles yet. A video without subtitles downloads as before, and a subtitle that fails never stops the download. Audio-only downloads never embed subtitles, and an HLS bundle can only have them beside it.

## Quality

Quality applies to sites downloaded with yt-dlp, such as YouTube. The Daily Wire offers fixed formats and keeps them.

**Download** chooses video up to a ceiling: 360p, 480p, 720p, 1080p, 1440p, 4K or 8K. VODLoft downloads the highest resolution the site has up to that, and otherwise the lower ones. **Audio only** downloads no video. Collection profiles also have **HLS bundle**, The Daily Wire's bundle of its 480p, 720p and 1080p versions.

**Optimise for** chooses which codecs and container are used:

- **Compatibility**: H.264 video and AAC audio in MP4. Plays on every device, also older TVs. Above 1080p there is rarely H.264, so a 1440p or 4K profile usually gets 1080p with this goal.
- **Quality**: AV1, then VP9, then H.264, with Opus audio, in MKV.
- **Small files**: the same codecs, preferring the smaller of two versions.
- **Your own**: drag the codecs into your order and switch off the ones you never want. Choose MP4 or MKV and Opus or AAC yourself. When none of your codecs exists for an episode, VODLoft takes the best version there is, or skips the episode and says why.

Changing a codec, the container or the audio codec while a goal is chosen turns it into **Your own**. Choosing a goal again replaces your order with that goal's.

**Audio format**, for Audio only: **M4A** (plays everywhere, including podcast apps), **Opus** (smallest, not every podcast app plays it) or **MP3** (for very old players). Opus files get their thumbnail and metadata beside them, not inside.

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
| `episode_type` | `ep`, `ep-extra`, `aux`, or `trailer` |
| `episode_extra_type` | `other` or `trailer` for attached episode extras; empty otherwise |
| `episode_number` | The Daily Wire main episode number for `ep`/`ep-extra`, or VODLoft's collection-wide counter for `aux`/`trailer` |
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

Movie templates have two groups of values:

- variables beginning with `movie_` always describe the parent movie;
- variables without that prefix describe the actual item being downloaded, which can be either the main movie or a specific movie extra.

This makes it possible to keep all extras inside the movie's folder while giving each item its own filename.

Example:

```jinja
/downloads/Movies/{{ movie_title }}{% if movie_year %} ({{ movie_year }}){% endif %}/{{ media_type }} - {{ title }}.ext
```

A movie template must use an item-specific value such as `{{ title }}`, `{{ slug }}`, or `{{ media_type }}` so the main movie and an extra cannot resolve to the same output path.  
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
| `date`, `time`, `datetime` | Item date/time values |
| `year`, `month`, `day`, `hour`, `minute`, `second` | Item date/time components |

The Daily Wire does not always provide every field for movie extras. Use conditionals around values that may be empty.

## Videos

Video templates describe one single video:

| Variable | Meaning |
| --- | --- |
| `title` | Video title |
| `slug` | The site's own id for the video |
| `author` | Channel or uploader, when the site names one |
| `source` | Name of the site the video comes from |
| `duration_seconds` | Video duration in seconds |
| `date`, `time`, `datetime` | Upload date/time values |
| `year`, `month`, `day`, `hour`, `minute`, `second` | Upload date/time components |

Titles are not unique, so include `{{ slug }}` in the filename. Sites do not always give an uploader or an upload date, so fall back or use a conditional:

```jinja
{% set output_date = date ~ ' - ' if date %}/downloads/videos/{{ author or source }}/{{ output_date }}{{ title }} [{{ slug }}].ext
```

## Filename restrictions

The global **Filename restrictions** setting controls how file and folder names are made safe. The three modes follow yt-dlp, so files are named like yt-dlp and Pinchflat name them. Each value a template fills in, such as a title, is cleaned the way yt-dlp cleans it. Text you type in the template itself is made safe too, and the editor says when typed text has a character the mode will replace. The preview shows the result.

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

## Suggested layouts

A common arrangement is:

- one Collection video profile for Plex/Jellyfin;
- one Collection audio profile for podcast-style storage or Audiobookshelf;
- one Movie profile with a conventional movie folder and item-specific extra names.

Local Media Profiles only control files VODLoft creates. Your media server can independently scan whichever subfolders you want.