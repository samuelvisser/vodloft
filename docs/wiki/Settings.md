# Settings

Most VODLoft configuration can be changed from the **Settings** page. The interface groups normal options into General, Downloads, Quick download, Automation, Messages and actions, Sources, Users, Import and Advanced tabs, and explains environment-variable overrides when they are active. Notifications, media server refreshes, webhooks and scripts have their own page: [[Messages-and-Actions]].

This page is the complete 1.1 reference for settings users may need to configure.

## Where settings are stored

Changes made in the Settings page are saved to `config.yml`. VODLoft keeps that file sparse: settings you never change do not need to be written there and continue using their built-in defaults.

In the Docker image, `config.yml` lives under the persistent `/config` mount.

### Environment variables

Environment variables override values from `config.yml`. This is useful when your Compose file or deployment platform should enforce a value.

A nested YAML setting such as:

```yaml
downloadSettings:
  maxConcurrentDownloads: 3
```

can be overridden with:

```text
VL_DOWNLOAD_SETTINGS__MAX_CONCURRENT_DOWNLOADS=3
```

The Settings page identifies environment-controlled values and tells you why you cannot change them in the UI.

### Practical precedence

For normal installations, think of precedence as:

1. environment variables;
2. `config.yml` / Settings UI;
3. built-in defaults.

VODLoft also supports a `.env` file and file-secret settings for advanced deployments. Environment values still take priority over those lower-level sources.

`TZ` is the special environment variable used for the application timezone.

## Configuration file locations

These environment variables choose the configuration source files themselves:

| Variable | Default | Purpose |
| --- | --- | --- |
| `VL_CONFIG_FILE` | `<project>/config/config.yml` | Use a different YAML settings file. |
| `VL_ENV_FILE` | `<project>/.env` | Use a different dotenv file. |

They are deployment options, not keys inside `config.yml`.

---

## General

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `databasePath` | `VL_DATABASE_PATH` | `<project>/config/vodloft.db` | Location of the SQLite database. The Docker image sets this to `/config/vodloft.db`. |
| `logLevel` | `VL_LOG_LEVEL` | `INFO` | Logging detail: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `timezone` | `TZ` | `UTC` | Timezone used for schedules and displayed time-sensitive behavior. Use an [IANA](https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List) value such as `Europe/Amsterdam`. |
| `loginSession.ttlSeconds` | `VL_LOGIN_SESSION__TTL_SECONDS` | `2592000` (30 days) | How long a signed-in browser remains authenticated. |

### Administrator password

Administrator authentication is normally configured as a deployment environment variable:

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `adminAuth.password` | `VL_ADMIN_AUTH__PASSWORD` | unset | Plain password input used when VODLoft starts. Recommended way to enable the UI login in Docker. |
| `adminAuth.passwordHash` | `VL_ADMIN_AUTH__PASSWORD_HASH` | unset | Advanced option for supplying a pre-generated VODLoft password hash. |

If neither is configured, the VODLoft administrator login is disabled. See [[Security-and-Remote-Access]].

---

## Downloads

These settings are available under **Settings → Downloads**.

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `downloadSettings.downloadRoot` | `VL_DOWNLOAD_SETTINGS__DOWNLOAD_ROOT` | `<project>/downloads` | Root directory used for paths beginning with `/downloads/`. In the supplied Docker layout, set/use `/downloads` to target the mounted media volume. |
| `downloadSettings.downloadMode` | `VL_DOWNLOAD_SETTINGS__DOWNLOAD_MODE` | `temporary` | System default: stage downloads in the temporary folder before publishing them. Local Media Profiles can inherit or override it. |
| `downloadSettings.temporaryDownloadRoot` | `VL_DOWNLOAD_SETTINGS__TEMPORARY_DOWNLOAD_ROOT` | system temp directory (`/tmp/vodloft-downloads` in Docker) | Staging directory used by temporary download mode. Keeping this on local storage avoids repeated remux/metadata I/O against a network media library. |
| `downloadSettings.rssCacheRoot` | `VL_DOWNLOAD_SETTINGS__RSS_CACHE_ROOT` | `<download root>/.vodloft-rss-cache` | Root for media cached while fulfilling RSS requests. When omitted, its default follows the download root; an explicit value stays independent. |
| `downloadSettings.quickDownloadRoot` | `VL_DOWNLOAD_SETTINGS__QUICK_DOWNLOAD_ROOT` | `<download root>/.vodloft-quick-downloads` | Where quick downloads are prepared and kept until they are fetched. On the download volume by default, so ready files survive a container update. When omitted, its default follows the download root. |
| `downloadSettings.thumbnailRoot` | `VL_DOWNLOAD_SETTINGS__THUMBNAIL_ROOT` | `thumbnails` next to the config file (`/config/thumbnails` in Docker) | Where VODLoft keeps the thumbnails it makes itself, such as the first frame of a video without a thumbnail. Kept out of the download library by default. |
| `downloadSettings.lockRoot` | `VL_DOWNLOAD_SETTINGS__LOCK_ROOT` | `locks` next to the config file (`/config/locks` in Docker) | Where VODLoft keeps the small lock files that stop two tasks from changing the same collection artwork or episode numbering at once. Kept out of the download library by default. |
| `downloadSettings.rssCacheRetentionSeconds` | `VL_DOWNLOAD_SETTINGS__RSS_CACHE_RETENTION_SECONDS` | `604800` (7 days) | Retains cached RSS media for this long since it was last served. Expired files are cleaned at startup and while new cache entries are prepared. |
| `downloadSettings.maxConcurrentDownloads` | `VL_DOWNLOAD_SETTINGS__MAX_CONCURRENT_DOWNLOADS` | `5` | Maximum primary-media transfers running at once. Their slots are released while post-processing continues. |
| `downloadSettings.maxDownloadAttempts` | `VL_DOWNLOAD_SETTINGS__MAX_DOWNLOAD_ATTEMPTS` | `3` | Automatic attempts before a download is left failed. |
| `downloadSettings.episodeDownloadDelayMinutes` | `VL_DOWNLOAD_SETTINGS__EPISODE_DOWNLOAD_DELAY_MINUTES` | `10` | Delay after publication before automatically downloading an episode. Manual downloads can be scheduled until the delay expires or started immediately. |
| `downloadSettings.ensureSafeDelay` | `VL_DOWNLOAD_SETTINGS__ENSURE_SAFE_DELAY` | `false` | When enabled, post-publication delay is always calculated from a point in time VODLoft itself recorded the episode as published final. With this disabled, VODLoft makes a best- effort guess for publication time as The Daily Wire API does not accurately report it for every collection. |
| `downloadSettings.downloadTimeoutSeconds` | `VL_DOWNLOAD_SETTINGS__DOWNLOAD_TIMEOUT_SECONDS` | `600` | Timeout for one download attempt. |
| `downloadSettings.filenameRestrictionMode` | `VL_DOWNLOAD_SETTINGS__FILENAME_RESTRICTION_MODE` | `windows` | Filename compatibility: `unrestricted`, `windows`, or `restricted`. |
| `downloadSettings.remuxVideoToMp4` | `VL_DOWNLOAD_SETTINGS__REMUX_VIDEO_TO_MP4` | `true` | Repackage compatible downloaded video into MP4 without re-encoding. |
| `downloadSettings.ffmpegPath` | `VL_DOWNLOAD_SETTINGS__FFMPEG_PATH` | `ffmpeg` | FFmpeg executable used for MP4 remuxing. |
| `downloadSettings.verifyDownloadsCronEnabled` | `VL_DOWNLOAD_SETTINGS__VERIFY_DOWNLOADS_CRON_ENABLED` | `true` | Enables the periodic download-verification cron schedule. |
| `downloadSettings.verifyDownloadsCron` | `VL_DOWNLOAD_SETTINGS__VERIFY_DOWNLOADS_CRON` | `0 */2 * * *` | Schedule for periodic download verification; every two hours by default. |
| `downloadSettings.speedLimitMode` | `VL_DOWNLOAD_SETTINGS__SPEED_LIMIT_MODE` | `streaming` | How much of your connection downloads may use: `full`, `streaming` (leave room for streaming) or `custom`. |
| `downloadSettings.speedLimitMbps` | `VL_DOWNLOAD_SETTINGS__SPEED_LIMIT_MBPS` | `5` | The limit in MB/s for all downloads together, with `custom`. |
| `downloadSettings.pauseAtNight` | `VL_DOWNLOAD_SETTINGS__PAUSE_AT_NIGHT` | `false` | Pause downloads every night between the two times below. |
| `downloadSettings.pauseStart` | `VL_DOWNLOAD_SETTINGS__PAUSE_START` | `01:00` | When the pause starts, in VODLoft's timezone. |
| `downloadSettings.pauseEnd` | `VL_DOWNLOAD_SETTINGS__PAUSE_END` | `07:00` | When downloads start again. The pause may run past midnight. |

When you move the temporary, RSS cache, quick download, thumbnail or lock folder, VODLoft removes the old folder the next time it starts, but only if VODLoft alone uses it: a hidden `.vodloft-…` folder or the setting's default folder. Quick downloads and thumbnails move to the new folder first. A folder of your own, and the download root itself, are never removed.

### Download profile defaults

What a new Download Profile starts with, under **Settings → Downloads → Download profile defaults**. Changing these
never changes a Download Profile you already have.

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `downloadProfileDefaults.upgradeCheck` | `VL_DOWNLOAD_PROFILE_DEFAULTS__UPGRADE_CHECK` | `true` | New profiles have the upgrade check on (see [[Download-Profiles#upgrade-check]]). |
| `downloadProfileDefaults.upgradeAfterDays` | `VL_DOWNLOAD_PROFILE_DEFAULTS__UPGRADE_AFTER_DAYS` | `7` | Days after downloading before the first check. |
| `downloadProfileDefaults.upgradeRepeat` | `VL_DOWNLOAD_PROFILE_DEFAULTS__UPGRADE_REPEAT` | `once` | How often it checks: `once`, `twice` or `every`. |
| `downloadProfileDefaults.upgradeImprovements` | `VL_DOWNLOAD_PROFILE_DEFAULTS__UPGRADE_IMPROVEMENTS` | `[resolution]` | What counts as a better version. A Site only checks for what it can find. |
| `downloadProfileDefaults.upgradeLengthMinutes` | `VL_DOWNLOAD_PROFILE_DEFAULTS__UPGRADE_LENGTH_MINUTES` | `5` | How many minutes longer or shorter counts as a different length. |
| `downloadProfileDefaults.autoSubtitles` | `VL_DOWNLOAD_PROFILE_DEFAULTS__AUTO_SUBTITLES` | `fallback` | Auto-generated subtitles: `never`, `fallback` (only when there are no real ones) or `always`. |

Below the system defaults, each Site has a row of its own, the same way as [Per-Site scheduling](#per-site-scheduling):
**Default** follows the system default, and a Site with a preset starts on its own value. The Daily Wire checks after
3 days for a different length; YouTube checks for a higher resolution and new SponsorBlock segments, and counts
3 minutes as a different length; NPO Start starts with the check off. Some settings only
exist on the Sites they are made for, so they have no Default: downloading with the countdown on The Daily Wire, and
SponsorBlock and its segments on YouTube. The Daily Wire makes no subtitles, so it has no auto-generated subtitles.

### Speed

Downloads share one speed limit, however many run at the same time.

- **Full speed** uses all the speed downloads can get.
- **Leave room for streaming** is the default. It keeps downloads to about half of your connection, so watching
  something while VODLoft downloads keeps working. VODLoft learns how fast your connection is from downloads that ran
  at full speed, so a new installation runs at full speed until a few downloads have finished. The Downloads page
  shows what VODLoft measured and the limit it uses now.
- **Custom limit** uses the MB/s you enter. 1 MB/s is 8 Mbit/s.

**Pause downloads at night** holds downloads between the two times you choose. A download that is running finishes
its current file first; the next one waits and shows *Paused* in its progress. Looking for new episodes keeps going
during the pause.

### Direct versus temporary mode

**Temporary** is the default. It keeps incomplete download and processing work in the local temporary folder and publishes the completed media into the final library at the end. This is especially useful when `/downloads` is SMB, NFS, or other network storage because remuxing and metadata embedding otherwise rewrite the full media file across the network. **Direct** writes and processes media in the destination instead.

Temporary mode is useful when a media server watches the destination and should never see partial files. See [[Downloads-and-File-Integrity]] and [[Local-Media-Profiles]].

### Filename modes

The modes follow yt-dlp, so new files are named as yt-dlp and Pinchflat name them. See [[Local-Media-Profiles#filename-restrictions]] for examples.

- `unrestricted` — like yt-dlp's `--no-windows-filenames`: only a `/` in a value changes, to `⧸`.
- `windows` — like yt-dlp's default: characters Windows does not allow become look-alikes such as `：` and `？`, and reserved names are protected. This is the default.
- `restricted` — like yt-dlp's `--restrict-filenames`: values such as titles use ASCII letters, numbers, `.`, `_` and `-` only. Text typed in the template keeps its spaces, as in yt-dlp, and is made ASCII.

---

## Quick download

These settings are under **Settings → Quick download**: the defaults the page suggests, how long files wait in the temporary folder, the history, and optional rules. See [[Quick-Download#settings]] for the full list.

## File watcher

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `fileWatcher.enabled` | `VL_FILE_WATCHER__ENABLED` | `true` | Enables file-watcher behavior, including non-cron triggers. |
| `fileWatcher.scanCronEnabled` | `VL_FILE_WATCHER__SCAN_CRON_ENABLED` | `true` | Enables the periodic file-watcher cron schedule. |
| `fileWatcher.scanCron` | `VL_FILE_WATCHER__SCAN_CRON` | `*/10 * * * *` | File watcher schedule; every ten minutes by default. |
| `fileWatcher.verifyFileSize` | `VL_FILE_WATCHER__VERIFY_FILE_SIZE` | `true` | Marks an empty or unexpectedly smaller completed file as corrupted. |

The watcher tracks files VODLoft already knows about; it is not intended to index arbitrary files across your entire media library.

---

## Automation

These settings are available under **Settings → Automation**.

### Scheduler

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `scheduler.enabled` | `VL_SCHEDULER__ENABLED` | `true` | Enables automatic indexing, monitoring and scheduled work. |
| `scheduler.maxWorkers` | `VL_SCHEDULER__MAX_WORKERS` | `15` | Maximum general background tasks that may run in parallel. Download concurrency is controlled separately. |
| `scheduler.stalledTaskTimeoutMinutes` | `VL_SCHEDULER__STALLED_TASK_TIMEOUT_MINUTES` | `20` | Cancels work whose progress has not changed for this long. |
| `scheduler.defaultMaxRetries` | `VL_SCHEDULER__DEFAULT_MAX_RETRIES` | `3` | Default retry count for eligible background tasks. |
| `scheduler.retryBackoffSeconds` | `VL_SCHEDULER__RETRY_BACKOFF_SECONDS` | `5` | Base delay used when spacing automatic retries. |

### Episode discovery and monitoring

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `newEpisodeSchedule.findEpisodesCronEnabled` | `VL_NEW_EPISODE_SCHEDULE__FIND_EPISODES_CRON_ENABLED` | `true` | Enables the recurring new-episode discovery schedule. |
| `newEpisodeSchedule.findEpisodesCron` | `VL_NEW_EPISODE_SCHEDULE__FIND_EPISODES_CRON` | `*/30 * * * *` | Checks managed collections for new episodes every 30 minutes. YouTube channels and other yt-dlp collections get quick checks instead. |
| `newEpisodeSchedule.quickCheckCronEnabled` | `VL_NEW_EPISODE_SCHEDULE__QUICK_CHECK_CRON_ENABLED` | `true` | Enables quick checks for new videos in yt-dlp collections. |
| `newEpisodeSchedule.quickCheckCron` | `VL_NEW_EPISODE_SCHEDULE__QUICK_CHECK_CRON` | `*/5 * * * *` | Wakes the quick check. Each collection is checked as often as the YouTube API quota allows, and never more often than `youtubeApi.minCheckIntervalMinutes`. |
| `newEpisodeSchedule.fullRescanCronEnabled` | `VL_NEW_EPISODE_SCHEDULE__FULL_RESCAN_CRON_ENABLED` | `true` | Enables the full re-scan of collections with quick checks. |
| `newEpisodeSchedule.fullRescanCron` | `VL_NEW_EPISODE_SCHEDULE__FULL_RESCAN_CRON` | `0 4 * * *` | Lists collections with quick checks in full once a day, to catch anything a quick check missed, and refreshes their episodes (see [[Collections-and-Library#renamed-and-removed-videos]]). |
| `newEpisodeSchedule.monitorNoUsableMediaEpisodeCronEnabled` | `VL_NEW_EPISODE_SCHEDULE__MONITOR_NO_USABLE_MEDIA_EPISODE_CRON_ENABLED` | `true` | Enables recurring checks for episodes without usable media. |
| `newEpisodeSchedule.monitorNoUsableMediaEpisodeCron` | `VL_NEW_EPISODE_SCHEDULE__MONITOR_NO_USABLE_MEDIA_EPISODE_CRON` | `*/20 * * * *` | Rechecks episodes that temporarily have no usable Daily Wire media. |
| `newEpisodeSchedule.metadataRefreshIntervals` | `VL_NEW_EPISODE_SCHEDULE__METADATA_REFRESH_INTERVALS` | `1h,6h,24h,3d` | The system schedule: follow-up metadata refreshes after publication, for every Site without a schedule of its own. |
| `newEpisodeSchedule.upcomingAndLive` | `VL_NEW_EPISODE_SCHEDULE__UPCOMING_AND_LIVE` | `true` | Adds streams and premieres as soon as they are announced, and follows them until they are published. |
| `newEpisodeSchedule.pendingUpcomingMinutes` | `VL_NEW_EPISODE_SCHEDULE__PENDING_UPCOMING_MINUTES` | `60` | How often an upcoming episode is looked up, until 15 minutes before it starts. |
| `newEpisodeSchedule.pendingStartingMinutes` | `VL_NEW_EPISODE_SCHEDULE__PENDING_STARTING_MINUTES` | `2` | How often an episode is looked up from 15 minutes before its start until an hour after. |
| `newEpisodeSchedule.pendingLiveMinutes` | `VL_NEW_EPISODE_SCHEDULE__PENDING_LIVE_MINUTES` | `5` | How often an episode is looked up while it is live, and while the site is still finishing it. |

A quick check looks only at a collection's newest videos and looks up the ones VODLoft does not have yet. For YouTube it reads the first page of the channel's uploads through the YouTube Data API (1 unit). Without a key, or once the quota is used up, it reads the channel's RSS feed, and if that fails, lists the newest videos with yt-dlp. A collection that was never indexed gets its full first index instead.

Metadata intervals accept positive values using `s`, `m`, `h`, or `d`, separated by commas and ordered from shortest to longest.

### Per-Site scheduling

Each Site follows the settings above unless you give it settings of its own under **Settings → Automation → Per-Site
scheduling**. Every setting there has a dropdown: **Default** follows the system setting above, and the other choices give
the Site a value of its own.

Some Sites come with a value of their own already, a *preset*. They start on **Own value** with the preset filled in, and
you can change it or set the Site back to **Default**. The Daily Wire's refresh schedule is `15m,30m,1h,3h,6h,24h,3d`, and
YouTube's is `30m,2h,6h,24h,3d,7d,14d`, because creators keep testing titles and thumbnails there for up to two weeks.

VODLoft keeps each Site's settings under `siteSettings` in `config.yml`, by the Site's key, together with its
[Download Profile defaults](#download-profile-defaults). A setting that is left out uses the Site's preset, or the system
setting when it has none. `default` always means the system setting, even on a Site with a preset:

```yaml
siteSettings:
  youtube:
    metadataRefresh: 30m,2h,24h   # or off, or default
  dailywire:
    upcomingAndLive: false
    lookupMinutes:                # the three lookup times always come together
      upcoming: 30
      starting: 2
      live: 5
    upgradeAfterDays: default     # use the system default instead of The Daily Wire's 3 days
```

### Episode lifecycle safeguards

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `episodeStatusTiming.publishedFinalAfterMinutes` | `VL_EPISODE_STATUS_TIMING__PUBLISHED_FINAL_AFTER_MINUTES` | `180` | Safety threshold for an episode that remains stuck on a countdown-style published version. |
| `episodeStatusTiming.dwProcessingMaxMinutes` | `VL_EPISODE_STATUS_TIMING__DW_PROCESSING_MAX_MINUTES` | `60` | Maximum time an episode may remain in Daily Wire processing before VODLoft treats its media as unavailable. |
| `episodeStatusTiming.noUsableMediaDeleteAfterMinutes` | `VL_EPISODE_STATUS_TIMING__NO_USABLE_MEDIA_DELETE_AFTER_MINUTES` | `240` | Waiting period before a persistently unavailable episode may be cleaned up. |

These are safeguards for unusual Daily Wire publication states. Most users should leave them at their defaults. See [[Automation-and-Background-Tasks]].

---

## Sources

The Sources tab lists every Source VODLoft can add media from, with what it supports. See [[Sources]] for what each one does. Signing in and API keys are set up per site, under **Authentication** at the top. The Daily Wire's card contains advanced integration settings. Ordinary installations should leave the endpoint, OAuth, and pacing values unchanged.

### Authentication

Signing in is optional, and only needed for content that requires an account, such as members-only or age-restricted
videos. It is set up per site, so YouTube, Twitch and NPO Start each have their own. **Authentication** lists every site
VODLoft knows: the sites a Source is made for, and every site you added something from. Each site shows whether it is
signed in and whether it has an API key; open it to change that.

- **The Daily Wire** has a sign-in of its own: follow the steps shown and authorize VODLoft on The Daily Wire's site.
  It takes no cookies file. See [[Daily-Wire-Integration]].
- **Every other site** signs in with a **cookies file**: a `cookies.txt` file (Netscape format) exported from a browser
  where you are signed in on that site, with a browser extension made for that. Every Source that fetches the site uses
  the site's own file, for every lookup and download there: yt-dlp on YouTube, and both NPO Start and yt-dlp on npo.nl.
  A site keeps only its own cookies from the file you choose, so a file with cookies of other sites is fine.
- **NPO Start** checks its cookies file with npo.nl, and shows whether it signs in with NPO Plus.
- **YouTube** also takes an optional YouTube Data API key, which makes VODLoft much faster there. See
  [[Settings#youtube-data-api-key]].

A site shows up once you add something from it. To set up a site first, such as Twitch before adding a members-only
channel, paste a link to a channel or video on that site in the box below the list and choose **Add site**. A link to
the site's home page is often not enough for VODLoft to tell which site it is. The same box is below the site lists of
the Automation and Downloads tabs.

Treat a cookies file like a password: it signs VODLoft in as you.

### yt-dlp

The yt-dlp card shows the installed yt-dlp version and when it was last updated. Sites change often, so VODLoft fetches the latest yt-dlp release once a week; **Update now** does it straight away, which is the first thing to try when a site stops working. The update is stored in the config directory and survives container upgrades.

For videos that need a signed-in viewer, give the site a cookies file under [[Settings#authentication]].

#### Your own yt-dlp options

Optional, and most people leave it empty. Extra yt-dlp options for every download of the yt-dlp Source (YouTube and
the other sites yt-dlp handles, not The Daily Wire or NPO Start). Write them the way yt-dlp's own option files have
them: one or more options per line, and lines starting with `#` are notes. Each line is checked with yt-dlp's own
parser as you type, and gets one of these results:

- **Passed to yt-dlp**: the line is used for every download.
- **Blocked**, with the reason: options that would change where files go or what they are called (such as `-o` and
  `-P`), pick the format past a Local Media Profile's Quality (`-f`), run other programs (`--exec`), or stop VODLoft
  from following the download.
- **VODLoft already has a setting for this**, naming that setting: for example subtitles, thumbnails, the container
  or SponsorBlock.

The options can only be saved when every line passes. A Collection can add its own options on its Edit page, for
exceptions; they come after these, so for an option set in both places the Collection's wins.

#### YouTube Data API key

Optional. A free key from Google lets VODLoft list YouTube channels and find new videos much faster than yt-dlp alone. yt-dlp still downloads every file, and VODLoft keeps working without a key, or when the key's daily quota runs out; it is only slower then.

To get a key, which takes about three minutes:

1. [Create a Google Cloud project](https://console.cloud.google.com/projectcreate). Any name works.
2. [Enable the YouTube Data API v3](https://console.cloud.google.com/apis/library/youtube.googleapis.com) in that project.
3. Under [Credentials](https://console.cloud.google.com/apis/credentials), choose **Create credentials → API key**. Edit the key and, under **API restrictions**, restrict it to the YouTube Data API v3. Leave the website, IP address and app restrictions off.
4. Paste the key into the YouTube Data API panel on YouTube's row under **Authentication**, and choose **Save and test**.

**Test key** checks a saved key again, and explains what to fix in Google Cloud when Google refuses it. A key that stops working, or a quota that runs out, also shows under **Needs attention** on Home. The key is stored next to the cookies file and is never shown again or written to the log.

Google gives each project 10,000 units a day, reset at midnight Pacific time. Most calls cost 1 unit; a search costs about 100. VODLoft counts the units it spends and splits the day like this:

| Setting | Environment variable | Default | What it is for |
| --- | --- | --- | --- |
| `youtubeApi.dailyQuota` | `VL_YOUTUBE_API__DAILY_QUOTA` | `10000` | What Google gives the project. Only raise it if Google gave you more. |
| `youtubeApi.checksQuota` | `VL_YOUTUBE_API__CHECKS_QUOTA` | `7000` | Checks for new videos and full re-scans of your YouTube collections. |
| `youtubeApi.searchQuota` | `VL_YOUTUBE_API__SEARCH_QUOTA` | `2000` | YouTube searches on the Add media page, about 19 a day. When it is used up, or set to `0`, searches use yt-dlp. |
| `youtubeApi.minCheckIntervalMinutes` | `VL_YOUTUBE_API__MIN_CHECK_INTERVAL_MINUTES` | `10` | The shortest time between two checks of the same collection. |

What the checks and search shares leave of the daily total is kept free for adding collections, testing the key and manual refreshes. Adding a collection uses the units kept free first and then the checks share; listing a channel costs about 2 units per 50 videos. The split is under **How to spend the YouTube API quota** on the yt-dlp card, and shows what each share means in practice, such as how often each collection gets checked.

### Sites more than one Source handles

Links to npo.nl can be looked up by NPO Start and by yt-dlp. The **Sites** card lists each such site and the Source VODLoft asks first; pick another to change it. On the Add media page, **Look up with** asks another Source for one link.

### API endpoints

| Setting | Environment variable | Default |
| --- | --- | --- |
| `dwApi.middlewareApi` | `VL_DW_API__MIDDLEWARE_API` | `https://middleware-prod.dailywire.com/middleware` |
| `dwApi.streamApi` | `VL_DW_API__STREAM_API` | `https://stream.media.dailywire.com` |

### OAuth client

| Setting | Environment variable | Default |
| --- | --- | --- |
| `dwOauth.issuer` | `VL_DW_OAUTH__ISSUER` | `https://authorize.dailywire.com` |
| `dwOauth.audience` | `VL_DW_OAUTH__AUDIENCE` | `https://api.dailywire.com/` |
| `dwOauth.clientId` | `VL_DW_OAUTH__CLIENT_ID` | `FCgw3nA6cxkcXLVseAQvCSVBrymwvfpE` |
| `dwOauth.scope` | `VL_DW_OAUTH__SCOPE` | `openid profile offline_access` |

### Request pacing

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `dwTimeout.minFastRequestMs` | `VL_DW_TIMEOUT__MIN_FAST_REQUEST_MS` | `100` | Minimum spacing for normal fast requests. |
| `dwTimeout.maxFastRequests` | `VL_DW_TIMEOUT__MAX_FAST_REQUESTS` | `350` | Number of fast requests allowed before slower pacing applies. |
| `dwTimeout.minSlowRequestMs` | `VL_DW_TIMEOUT__MIN_SLOW_REQUEST_MS` | `120000` (2 minutes) | Slower pacing interval used after the fast-request threshold. |

Aggressive request pacing can make Daily Wire throttling more likely. Leave these values alone unless you are diagnosing a specific integration problem.

See [[Daily-Wire-Integration]].

---

## Movie metadata (TMDB)

VODLoft can optionally use TMDB to enrich movie metadata, particularly release-date information used for matching and output templates.

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `movieMetadata.tmdbReadAccessToken` | `VL_MOVIE_METADATA__TMDB_READ_ACCESS_TOKEN` | unset | TMDB API Read Access Token. The Settings page does not reveal a stored token back to the browser. |
| `movieMetadata.tmdbApiBaseUrl` | `VL_MOVIE_METADATA__TMDB_API_BASE_URL` | `https://api.themoviedb.org/3` | TMDB API endpoint. |
| `movieMetadata.language` | `VL_MOVIE_METADATA__LANGUAGE` | `en-US` | Preferred metadata language. |
| `movieMetadata.requestTimeoutSeconds` | `VL_MOVIE_METADATA__REQUEST_TIMEOUT_SECONDS` | `10` | Timeout for one TMDB request. |
| `movieMetadata.maxRetries` | `VL_MOVIE_METADATA__MAX_RETRIES` | `2` | Retries for transient TMDB failures, from 0 to 5. |

TMDB is optional and separate from Daily Wire authentication.

---

## Encryption and secret-key settings

These advanced settings control the application key used to protect stored sensitive values.

| Setting | Environment variable | Default | What it does |
| --- | --- | --- | --- |
| `crypto.secretKey` | `VL_CRYPTO__SECRET_KEY` | unset | Advanced option for supplying key material directly. Prefer a managed secret/file instead of committing this to YAML. |
| `crypto.secretKeyFile` | `VL_CRYPTO__SECRET_KEY_FILE` | unset | Explicit file containing the application key. |
| `crypto.defaultSecretFile` | `VL_CRYPTO__DEFAULT_SECRET_FILE` | `<project>/data/wl_secret.key`; Docker seed `/config/wl_secret.key` | Generated-key location used when no explicit key is configured. |

Keep the Docker `/config` directory persistent so the generated key survives container recreation. Changing key files can make previously protected authentication data unreadable.

---

## Cron syntax

Cron fields use:

```text
minute hour day-of-month month day-of-week
```

Examples:

```text
*/15 * * * *    # every 15 minutes
0 */6 * * *     # every 6 hours
0 3 * * *       # every day at 03:00
0 8 * * 1,3     # Monday and Wednesday at 08:00
```

Schedules use the `TZ` timezone.

## Example `config.yml`

You only need to include values you actually want to override:

```yaml
logLevel: INFO

downloadSettings:
  downloadRoot: /downloads
  downloadMode: temporary
  temporaryDownloadRoot: /tmp/vodloft-downloads
  rssCacheRoot: /tmp/vodloft-rss-cache
  maxConcurrentDownloads: 3
  episodeDownloadDelayMinutes: 10
  filenameRestrictionMode: windows

scheduler:
  maxWorkers: 15
  stalledTaskTimeoutMinutes: 20

newEpisodeSchedule:
  findEpisodesCron: "*/30 * * * *"

fileWatcher:
  enabled: true
  scanCron: "*/10 * * * *"
```

Anything omitted continues to use its default unless an environment variable overrides it.