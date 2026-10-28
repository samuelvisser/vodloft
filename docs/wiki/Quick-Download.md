# Quick download

**Quick download** gets you one file from a link, without adding anything to your library. Paste a link, pick what you want, and your browser downloads the file. VODLoft deletes its own copy shortly after.

Use it for a single video you want to keep on a laptop or phone, or for the audio of a talk. For a show you want to follow, add it on **Add media** instead (see [[Shows-and-Library]]).

## Downloading a file

1. Open **Quick download** in the sidebar, or press **Quick download** on **Add media** after looking up a link.
2. Paste the link and press **Look up**. When more than one Source handles the site, choose which one to use.
3. Pick a row: **Best**, a quality such as **1080p**, or **Audio**. The recommended row follows your defaults. The bars show how big each file is, when the Source reports sizes.
4. Press **Download**. The file is prepared in the background and shows up under **Ready to download**, with a notice that links to it.
5. Press **Download file**. Your browser saves it.

A link that is protected by DRM, or that needs a subscription VODLoft is not signed in to, is not downloaded. The page says why.

## Formats and codecs

The chips on each row choose the format: **MP4** or **MKV** for video, **M4A** or **MP3** for audio. **Format and codec** opens the full set of choices:

- **Video codec**: Auto leaves it to the Source. H.264 plays everywhere; H.265, VP9 and AV1 are smaller but need newer devices. Codecs a video does not offer are greyed out.
- **MP3 quality**: 320, 192 or 128 kbps. M4A keeps the original audio; MP3 converts it, for older players and car stereos.
- **Inside the file**: the title, show or channel and date, and the cover art.

Format and codec choices are offered for links that list their formats, such as yt-dlp links. Other Sources download as Best MP4 video or M4A audio.

Tick **Use these as my defaults next time** to keep your choices for the next link. The defaults are also under **Settings › Quick download**.

## Where the file waits

Each file is prepared in its own folder under `.vodloft-quick` inside the temporary folder (`downloadSettings.temporaryDownloadRoot`), never in your library. VODLoft deletes it:

- a few minutes after your browser has received every byte (10 minutes by default, so a failed save can be retried);
- when nobody downloads it in time (24 hours by default);
- when you press **Discard**.

A quick download does not start when it would leave less free space in the temporary folder than you set under **Settings › Quick download**.

## History

The **History** list shows what was downloaded, from where, as what and how it ended: downloaded, deleted before anyone downloaded it, discarded, canceled, failed, or not downloaded because of DRM or a rule. No files or paths are kept.

**Download again** looks the link up once more with the same choices. **Clear history** forgets every finished entry. Entries are forgotten on their own after 90 days. Turn the history off with **Keep a history** in Settings.

## Rules

**Settings › Quick download › Rules** limits what anyone can choose on the page. All rules are off by default.

| Rule | What it does |
| --- | --- |
| Highest quality | Higher rows are greyed out with the reason, and Best is held to this height. |
| Codec | Only video in this codec, for links that list their codecs. A video without it does not start. |
| Largest file | Checked before starting when the Source reports a size, and again while yt-dlp fetches the file. |
| Longest video | Checked when the Source reports how long a video is. |
| Allow MP4, MKV, M4A, MP3 | A format that is not allowed shows a lock. |
| Allow each Source | Quick download from a Source that is turned off does not start. |
| Lock choices to the defaults | The page shows only the link box and the defaults. |

VODLoft checks the rules itself when a quick download starts, so a choice the rules do not allow never starts, even when someone sends the request without the page.

## Settings

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `quickDownload.defaultKind` | `VL_QUICK_DOWNLOAD__DEFAULT_KIND` | `video` | Video or audio, as the page first suggests. |
| `quickDownload.defaultQuality` | `VL_QUICK_DOWNLOAD__DEFAULT_QUALITY` | `1080p` | The recommended row. A video without this quality recommends the next one down. |
| `quickDownload.defaultContainer` | `VL_QUICK_DOWNLOAD__DEFAULT_CONTAINER` | `mp4` | MP4 or MKV for video. |
| `quickDownload.defaultCodec` | `VL_QUICK_DOWNLOAD__DEFAULT_CODEC` | `auto` | The codec quick downloads prefer. |
| `quickDownload.defaultAudioFormat` | `VL_QUICK_DOWNLOAD__DEFAULT_AUDIO_FORMAT` | `m4a` | M4A or MP3 for audio. |
| `quickDownload.defaultMp3Bitrate` | `VL_QUICK_DOWNLOAD__DEFAULT_MP3_BITRATE` | `192` | 320, 192 or 128 kbps. |
| `quickDownload.embedMetadata` | `VL_QUICK_DOWNLOAD__EMBED_METADATA` | `true` | Embed title, show or channel and date. |
| `quickDownload.embedArtwork` | `VL_QUICK_DOWNLOAD__EMBED_ARTWORK` | `true` | Embed cover art. |
| `quickDownload.keepDownloadedMinutes` | `VL_QUICK_DOWNLOAD__KEEP_DOWNLOADED_MINUTES` | `10` | Minutes a file stays after it was downloaded. 0 deletes it at the last byte. |
| `quickDownload.keepUnclaimedHours` | `VL_QUICK_DOWNLOAD__KEEP_UNCLAIMED_HOURS` | `24` | Hours a ready file waits for someone to download it. |
| `quickDownload.keepFreeGigabytes` | `VL_QUICK_DOWNLOAD__KEEP_FREE_GIGABYTES` | `5` | Space to keep free in the temporary folder. |
| `quickDownload.keepHistory` | `VL_QUICK_DOWNLOAD__KEEP_HISTORY` | `true` | Keep the History list. |
| `quickDownload.historyRetentionDays` | `VL_QUICK_DOWNLOAD__HISTORY_RETENTION_DAYS` | `90` | Days an entry stays in the history. |
| `quickDownload.maxQuality` | `VL_QUICK_DOWNLOAD__MAX_QUALITY` | `best` | Rule: the highest quality; `best` is no limit. |
| `quickDownload.allowMp4`, `allowMkv`, `allowM4a`, `allowMp3` | `VL_QUICK_DOWNLOAD__ALLOW_MP4` and so on | `true` | Rule: whether each format may be chosen. |
| `quickDownload.fixedCodec` | `VL_QUICK_DOWNLOAD__FIXED_CODEC` | `auto` | Rule: only video in this codec; `auto` is no rule. |
| `quickDownload.maxFileGigabytes` | `VL_QUICK_DOWNLOAD__MAX_FILE_GIGABYTES` | `0` | Rule: the largest file; 0 is no limit. |
| `quickDownload.maxDurationMinutes` | `VL_QUICK_DOWNLOAD__MAX_DURATION_MINUTES` | `0` | Rule: the longest video; 0 is no limit. |
| `quickDownload.allowedSources` | `VL_QUICK_DOWNLOAD__ALLOWED_SOURCES` | empty | Rule: comma-separated Source ids, such as `ytdlp,dailywire`; empty allows all. |
| `quickDownload.lockToDefaults` | `VL_QUICK_DOWNLOAD__LOCK_TO_DEFAULTS` | `false` | Rule: only the defaults can be downloaded. |
