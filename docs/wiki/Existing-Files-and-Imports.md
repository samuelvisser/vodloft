# Existing files and imports

VODLoft can adopt media files you already have, so it doesn't download those episodes again. This works for
files from an older VODLoft template, from yt-dlp, from another program, or copied over by hand.

Adopting never moves, renames or changes a file. VODLoft records it as a download of the episode, with its
artwork, `.nfo` and subtitle sidecars, and from then on treats it like any file it downloaded itself.

## While adding a collection

When you add a collection that VODLoft downloads, the **Existing files** step comes after the Media Profile:

1. Turn on **I already have files for this collection**.
2. Pick the **Folder with the existing files**. It starts at the deepest folder of the Local Media Profile's
   output template that has no variable in it. **Browse** lists the folders VODLoft can see under
   `/downloads/`. Subfolders are searched too.
3. If the files are named in another way than the profile's template, fill in the old layout (see below).

VODLoft creates the Download Profile, but holds it until you are done: nothing is downloaded yet. Once the
episodes are indexed, VODLoft scans the folder and the collection's page shows a banner. Open it to review what
was found.

## For a collection you already have

Open the collection and choose **Match existing files** in its action menu. Pick the Local Media Profile the
files belong to, the folder, and optionally the old layout, and choose **Scan**.

## The old layout

The old layout is an output template, written like a Local Media Profile's template, from `/downloads/` to
`.ext`. You can also write just the file name part, which then applies inside the chosen folder. For example:

```
{{ date }} {{ title }} [{{ episode_site_id }}]
```

VODLoft reads the values back out of each file name. With the episode's id in the layout, matches are certain;
with only dates and titles, they are likely or need a check.

## How files are matched

Each file is matched by the strongest evidence VODLoft finds:

| Matched by | Confidence | What it means |
| --- | --- | --- |
| Recorded path | Certain | An import named this file as the episode's download. |
| Expected path | Certain | The file is exactly where the profile's template puts the episode. |
| Id in name | Certain | The episode's id from its source is in the file name, such as `[dQw4w9WgXcQ]`. |
| Sidecar | Certain | An `.info.json` or `.nfo` next to the file names the episode's id or URL. |
| Template | Likely | The old layout reads values from the name that fit one episode. |
| Title and date | Please check | The name looks like the episode's title, and a date in it is within a day. |

A file that fits more than one episode, or two files that claim the same episode with the same evidence, go to
**Please check**. There you pick the episode for each file, or leave it out.

VODLoft skips unfinished downloads (`.part`, `.ytdl`, `.temp` and similar), the separate video and audio parts
yt-dlp leaves before merging (`.f137.mp4`), and its own temporary files.

## Reviewing and finishing

The review shows each file with the episode it matched and how. **Adopt** adopts every certain and likely match;
**Adopt checked** adopts the files you picked an episode for under **Please check**.

When you are done, choose **Done, download the rest**. The Download Profile turns on and downloads only the
episodes that still have no file.

Adopted files keep their names. To give them the profile's names, choose **Rename to this profile's template**,
which runs the collection's file rename for that profile.

## The Import screen

Administrators find the importers under **Settings → Import**, and in the **Your media** step of the first-run setup.
Each importer has its own card:

1. **Upload.** Choose the other program's config folder, or an archive of it (zip or tar). Only the files the importer
   needs are sent, in small pieces, so a large database also works behind a reverse proxy; an interrupted upload
   continues where it stopped. If the folder is already mounted into VODLoft, choose **Use a folder VODLoft can
   already see** instead. Sign-ins are only taken when you turn on **Also bring sign-ins**.
2. **Preview.** Check the folder mapping (change it and choose **Check again** if VODLoft looks in the wrong place),
   untick collections you don't want, edit a profile's template and see whether existing files keep their paths, and
   tick the settings to bring over. Download Profiles stay off unless you turn on **Turn on Download Profiles**.
3. **Import.** The card follows the run per collection. **Download report** saves what was created, linked, kept and
   refused as a text file. Earlier imports stay listed with their reports.

**Upload again** replaces the upload with a newer one, for example to run the import again later.

## Importing from Pinchflat

Administrators can import a Pinchflat installation from **Settings → Import**. Upload Pinchflat's config folder
(or a zip of it); VODLoft keeps only `db/pinchflat.db` and the yt-dlp option files, and skips `cookies.txt`, your YouTube API key
and your Apprise server unless you choose to bring them.

The preview shows which folder VODLoft found Pinchflat's downloads under, each source as a new or existing
collection, each media profile as a profile with the template it becomes, and whether rendering that template gives
the same paths Pinchflat recorded. Nothing changes until you start the import.

The import creates the collections and profiles, then adopts every downloaded file at the path Pinchflat recorded,
as soon as the collection has its episodes. Videos you told Pinchflat not to download stay skipped. Download
Profiles stay off until all files are adopted; they then turn on if you asked for that and the source was enabled.

A source's title filter becomes an **Only download** filter on the title, and its minimum and maximum length become
**Skip** filters on the duration (see [[Download-Profiles#which-episodes]]). Its retention period deletes downloads that
many days after downloading, as Pinchflat did, and videos you told Pinchflat never to delete are kept.

A media profile's resolution becomes the Local Media Profile's **Up to** step, its subtitle languages its language
list, its audio track its audio language, and MKV its container (see [[Local-Media-Profiles#quality]]). Downloading
auto subtitles becomes **only when there are no real ones** on the Local Media Profile, which is what
Pinchflat did. Its SponsorBlock setting becomes SponsorBlock on the Local Media Profile: the categories
Pinchflat removed are cut out, the ones it marked become chapters (see [[Local-Media-Profiles#sponsorblock]]). A Local
Media Profile that is already used by a Collection keeps its own settings for these.

Options in Pinchflat's yt-dlp option files that VODLoft has no setting for become the Collection's own yt-dlp options,
on its Edit page (see [[Settings#your-own-yt-dlp-options]]), with the file each came from as a note. Lines VODLoft
blocks, such as `--exec`, are left out, and the report gives the reason.

A media profile's redownload delay becomes the upgrade check on its Download Profiles, looking again that many days
after downloading; unlike Pinchflat, VODLoft only replaces the file when the new one is better (see
[[Download-Profiles]]). A source's cookie behaviour becomes the Collection's **Use the cookies file** choice: *Disabled*
is Never, *When needed* is Only when needed, *All operations* is Always. A source Pinchflat indexed less often than
once a day gets that as the Collection's own schedule; one indexed daily or more often, or with *Use Fast Indexing*
on, keeps VODLoft's checks, which look more often (see [[Collections-and-Library#checking-and-cookies-per-collection]]).
Importing again takes back a schedule an earlier import set for a source that now uses fast indexing, unless you
changed it in VODLoft.

Pinchflat's download speed limit becomes a custom speed limit under **Settings → Downloads** (see
[[Settings#speed]]). Its Apprise server becomes a destination called *Pinchflat* under **Settings → Messages and
actions**, added to the default rules, if you choose to bring it: like a sign-in, an Apprise URL holds passwords (see
[[Messages-and-Actions]]). A lifecycle script is listed in the report but never copied, because it runs code: put it in
`/config/scripts` and add it as a script action.

You can run the import again. Anything you changed in VODLoft since the last run is kept, and settings a newer
VODLoft can map, which it reported as unsupported before, are brought over.

## Importing from ytdl-sub

Administrators can import a ytdl-sub setup from **Settings → Import**. Upload your `subscriptions.yaml`, and
`config.yaml` when you made presets of your own there. `cookies.txt` is optional and only brought over if you choose
so. ytdl-sub keeps no database, so VODLoft reads your subscriptions the way ytdl-sub does: every preset a
subscription uses, then `__preset__`, then the subscription's own values. ytdl-sub's own presets, such as
*Jellyfin TV Show by Date* or *Max 1080p*, are known by name.

Each subscription becomes a collection, and each combination of presets becomes a Local Media Profile, named after
it, with the output template ytdl-sub would use. Subscriptions that use the same presets share one profile; one that
changes the template with values of its own gets a profile of its own. The preview groups the collections by preset
and shows each template, so you can check them before importing.

ytdl-sub keeps a download archive next to the videos of each subscription. VODLoft finds your files through it, the
same way as for Pinchflat: the preview shows which folder ytdl-sub saved to and where VODLoft sees it, and how many
of the sampled files it found. When the TV show presets put the episode number in the file name, VODLoft keeps those
numbers.

What comes along:

- **Quality**: *Max 1080p*, *Max 720p* and the other resolution presets, and the audio presets, become the Local
  Media Profile's quality.
- **Subtitles**, **SponsorBlock**, **NFO files** and **thumbnails** become the matching Local Media Profile settings.
- **Only Recent**, `date_range` and `keep_max_files` become the Download Profile's date and "latest N" filters;
  **Filter Keywords** and **Filter Duration** become **Only download** and **Skip** filters.
- The **genre** and **content rating** you give with `= Documentaries` and `= TV-Y` become the collection's own genre
  and content rating, which VODLoft writes into its NFO files.
- ytdl-sub's file names use the same characters as VODLoft's Windows-compatible names, so the import sets that.
- A subscription with **several links** becomes one collection with all of them. A **TV Show Collection** keeps
  each season's number and name, and a video that is in more than one season stays in the highest, as in ytdl-sub.
- **Add the collections** in the preview chooses how they arrive. *As channels*, the default, adds each collection to
  the channel behind its links, such as a YouTube channel, and adds the channel when it is not in your Library yet.
  *As collections* adds each one on its own; you can still add it to its channel later.
- A **Bandcamp** or **SoundCloud Discography** subscription adds the artist. All of the artist's albums go
  into one Music collection, each album a season, with a Music Local Media Profile that keeps ytdl-sub's folder per
  artist and per album. The genre you give with `= Lofi` becomes the artist's genre, which new albums get too.

What does not come along is listed in the report: scripts that compute values (VODLoft's templates are Jinja, see
[[Local-Media-Profiles]]), throttle settings (VODLoft has a guard of its own, see
[[Downloads-and-File-Integrity#when-youtube-only-offers-360p]]), chunked downloads, music videos, *YouTube Releases* and *YouTube Full Albums*
(VODLoft can't read YouTube's Releases tab or split a video into tracks yet), and yt-dlp options VODLoft has no
setting for.

Stop ytdl-sub's cron job before you turn on the imported Download Profiles, or both will download the same videos.

## Importing from WireLoft

VODLoft grew out of WireLoft, and imports a WireLoft installation of any release from 1.0 on. Start VODLoft with
its own, empty config folder and upload WireLoft's config folder from **Settings → Import**. VODLoft keeps only
`wireloft.db` and `config.yml`, plus WireLoft's keyring file if you choose to bring your Daily Wire sign-in. WireLoft's
folder is only read; VODLoft works on its own copy.

The import brings over your shows (as Collections), seasons, episodes, movies and extras with their Daily Wire ids,
episode numbers and Custom Index numbers, so file names stay the same. Local Media Profiles keep their templates;
`show_*` variables become `collection_*`. RSS feeds keep their tokens, so podcast apps only need VODLoft's address.
Downloads are adopted where they are. A show you already added in VODLoft is linked, not added twice.

A feed whose token VODLoft already uses is not imported, and the report says so. A download VODLoft can't reach in
its download folder is kept but marked as not downloaded, and won't be downloaded again; the next import adopts it
once the folder is reachable.

VODLoft no longer upgrades a WireLoft database in place. If VODLoft finds a WireLoft database in its own config
folder, it doesn't start, and asks you to import it instead.
