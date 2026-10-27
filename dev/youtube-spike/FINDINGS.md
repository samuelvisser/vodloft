# Phase 1 findings: yt-dlp and the YouTube Data API

Measured on 27 October 2026 on the test server with `dev/youtube_spike.py`, yt-dlp 2026.10.21 and the cookies file
in use. The run cost 139 API units. Raw numbers are in `results.json` and the recorded videos in
`tests/fixtures/youtube/`.

## Baseline timings

| Case | yt-dlp | YouTube Data API |
| --- | --- | --- |
| Channel @mkbhd (1,861 videos), first index | Videos tab listed 1,728 in 30 s; a full lookup takes 5.7 s a video, so about 3.2 hours | All 1,858 listed and detailed in 15.8 s, 76 units |
| Playlist "First Impressions!" (159 videos) | Listed in 3.5 s; full lookups about 19 minutes | Listed and detailed in 1.7 s, 8 units |
| "Anything new?" on 20 channels | Flat listing of the newest 15: 49.7 s in total | First uploads page: 6.0 s in total, 20 units |

RSS answered all 60 requests (3 per channel) with HTTP 200 and 15 entries, in about 0.04 s each.

## What the API sees

- The uploads playlist (`UU…`) has every upload. The Videos tab yt-dlp lists leaves out Shorts and livestreams:
  the 130 videos only the API listed for @mkbhd are its 124 Shorts and 6 livestreams.
- YouTube keeps `UULF` (long videos), `UUSH` (Shorts) and `UULV` (livestreams) playlists for every channel tried,
  and they add up to the uploads playlist. For @LinusTechTips 6,583 / 289 / 469, @JeffGeerling 477 / 48 / 59,
  @mkbhd 1,728 / 124 / 6.
- The API has no Shorts flag, so membership of `UUSH` decides it. Shorts are three minutes at most, so only shorter
  videos need checking.
- Every recorded livestream has `liveStreamingDetails`, also long after the broadcast, and yt-dlp calls every one of
  them a livestream with `live_status` `was_live`.
- A livestream that was scheduled and never held is `liveBroadcastContent: upcoming` in the API, and yt-dlp cannot
  look it up at all ("Offline").
- Members-only, age-restricted and region-blocked videos were not part of this run.

## Where the two disagree

- **Dates.** None, once a livestream is dated by `liveStreamingDetails.actualStartTime`, which is what yt-dlp's
  `release_timestamp` is. The API's `publishedAt` for a livestream is when the broadcast ended and was published,
  often hours later and sometimes on another day. Every other video's `publishedAt` matches yt-dlp's `timestamp`
  to the second.
- **Durations.** The API rounds up to the next second where yt-dlp rounds down, so the API is 0 or 1 second longer.
- **Thumbnails.** Both pick `maxresdefault`; yt-dlp sometimes gives the WebP copy of the same picture.
- **Tags.** Video, Short and Livestream agree for all 35 videos yt-dlp could look up.

`tests/unit/test_youtube_catalogue.py` keeps the API mapping to these rules against the recorded videos.
