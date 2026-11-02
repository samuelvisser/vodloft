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
