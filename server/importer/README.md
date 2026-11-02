# Importers

`importer` reads another media manager's data, such as Pinchflat's, and turns it
into a neutral `ImportPlan` (`importer.contract`): Collections, profiles, files
and settings, each named by the other program's own id. It never imports
VODLoft's application code. The backend decides how a plan becomes VODLoft rows
and refuses what it can't apply.

## Output templates

`importer.ytdlp_templates` reads yt-dlp output templates with yt-dlp's own
grammar, expands Pinchflat's `{{ name }}` templates as Pinchflat does, and
converts the result to a VODLoft Jinja template. Every part of the template gets
a report entry: exact, close (with why) or unsupported (with what the import did
instead). Fields a YouTube video never fills become yt-dlp's placeholder, as
they would in yt-dlp. Volatile fields, such as `view_count`, are not converted,
because they would rename files all the time.

Pinchflat's per-download values become Collection values or Custom Indexes that
keep the imported numbers, such as `media_upload_date_index`, which becomes
`'day' | custom_index(per=date, start=99, step=-1)`.

## Option files

`importer.ytdlp_templates.options` reads yt-dlp option files with yt-dlp's own
parser, in the order Pinchflat passes them (`base-config.txt` first, then the
media profile's, the source's and the media item's file), after Pinchflat's
own options. yt-dlp reads them back to front, so for an option set twice the
command line wins, then `base-config.txt`, then the more specific files.

Every option written in a file gets a handling (converted, close, not needed,
unsupported or overridden) and one sentence. `--parse-metadata` and
`--replace-in-metadata` become `{% set %}` lines at the top of the converted
template, in yt-dlp's order; actions whose result the template never reads
are left out and reported as such.

## Pinchflat

`importer.pinchflat` reads a private copy of `pinchflat.db` (never the live
file) and refuses a database newer than `NEWEST_KNOWN_VERSION` or one that lacks
the columns it reads. `plan_import` turns it into a plan:

- each media profile becomes a Local Media Profile, with its own variant for a
  source that overrides the template or has its own option file;
- each source becomes a Collection (`source:<id>`) with a Download Profile;
  retention becomes "days in the past" with deletion, a cutoff date becomes
  "starting from";
- each media item with a file becomes a file the backend adopts at its recorded
  path, with its index numbers stored as Custom Index ordinals. Channels number
  down from 99, playlists up from 0, so the first item becomes 1 either way;
- an item Pinchflat was told not to download becomes a suppressed download, a
  culled item is counted as missing;
- settings become VODLoft settings where one exists. The YouTube API key and
  `cookies.txt` are secrets: they are only uploaded when the person asks, and
  the backend deletes them after the run.

`importer.paths` finds the folder VODLoft sees Pinchflat's downloads under by
testing recorded paths on disk. `importer.uploads` names the files an importer
reads (`UPLOAD_FILES`) so an upload of a whole config folder or archive keeps
only those.
