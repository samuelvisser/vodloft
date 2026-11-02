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
