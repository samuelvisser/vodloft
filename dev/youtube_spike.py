"""Beta 0.2.0 phase 1: measure yt-dlp against the YouTube Data API, and record fixtures.

Run it inside the VODLoft container, where yt-dlp, the cookies file and the API
key from Settings > Sources are:

    docker exec -i vodloft <container python> - < dev/youtube_spike.py

It writes results.json and fixtures/<video id>.json to a
youtube-spike folder next to the yt-dlp folder in the config directory. The API
calls are counted in the key's reserve share like any other VODLoft call; a full
run costs about 300 units.
"""
from __future__ import annotations

import json
import random
import subprocess
import time
import xml.etree.ElementTree as ET

import requests

from sources import ytdlp_runner as runner
from sources.ytdlp.youtube_api import Share, YouTubeApiClient, key as key_store

BIG_CHANNEL = "@mkbhd"
QUICK_CHECK_CHANNELS = [
    "@mkbhd", "@veritasium", "@LinusTechTips", "@kurzgesagt", "@MrBeast", "@3blue1brown", "@TomScottGo",
    "@smartereveryday", "@markrober", "@CGPGrey", "@Vsauce", "@numberphile", "@NileRed", "@StuffMadeHere",
    "@TechnologyConnections", "@WendoverProductions", "@RealEngineering", "@minutephysics", "@LegalEagle",
    "@JeffGeerling",
]
# Channels with Shorts and livestreams, for the fixtures and the UULF/UUSH/UULV check.
TAG_CHANNELS = ["@LinusTechTips", "@JeffGeerling", "@mkbhd"]
FULL_SAMPLE = 15
PLAYLIST_SAMPLE = 10
PER_PLAYLIST_FIXTURES = 4
YTDLP_KEYS = (
    "id", "title", "duration", "timestamp", "release_timestamp", "upload_date", "release_date", "live_status",
    "media_type", "was_live", "availability", "age_limit", "channel_id", "channel", "uploader", "webpage_url",
    "thumbnail", "extractor_key", "_type",
)

OUT = runner.ytdlp_directory().parent / "youtube-spike"
api = YouTubeApiClient(key_store.load() or "")
units = 0


def call(method, *args, **kwargs):
    global units
    units += 100 if method == "search" else 1
    return getattr(api, method)(*args, share=Share.RESERVE, **kwargs)


def ytdlp(*args: str, timeout: int = 1800) -> tuple[dict, float]:
    started = time.monotonic()
    result = subprocess.run([*runner.command(), "--no-progress", "-J", *args], capture_output=True, text=True, timeout=timeout)
    elapsed = time.monotonic() - started
    if result.returncode != 0:
        return {"_error": result.stderr.strip()[-400:]}, elapsed
    return json.loads(result.stdout), elapsed


def trimmed(info: dict) -> dict:
    out = {key: info.get(key) for key in YTDLP_KEYS if key in info}
    out["description"] = (info.get("description") or "")[:300]
    return out


def channel(handle: str) -> dict:
    [item] = call("channels", handle=handle, part="snippet,contentDetails,statistics")
    return item


def uploads_ids(playlist_id: str) -> tuple[list[str], float, int]:
    ids, token, pages, started = [], None, 0, time.monotonic()
    while True:
        page = call("playlist_items", playlist_id, page_token=token)
        pages += 1
        ids += [item["contentDetails"]["videoId"] for item in page.get("items") or []]
        token = page.get("nextPageToken")
        if not token:
            return ids, time.monotonic() - started, pages


def details(ids: list[str]) -> tuple[dict[str, dict], float]:
    started, found = time.monotonic(), {}
    for start in range(0, len(ids), 50):
        for item in call("videos", ids[start:start + 50]):
            found[item["id"]] = item
    return found, time.monotonic() - started


def ytdlp_listing_and_sample(url: str, sample: int) -> dict:
    listing, listing_seconds = ytdlp("--flat-playlist", url)
    entries = [entry for entry in listing.get("entries") or [] if isinstance(entry, dict) and entry.get("id")]
    picked = random.sample(entries, min(sample, len(entries)))
    timings, errors = [], []
    for entry in picked:
        info, seconds = ytdlp("--no-playlist", f"https://www.youtube.com/watch?v={entry['id']}", timeout=180)
        timings.append(seconds)
        if "_error" in info:
            errors.append({"id": entry["id"], "error": info["_error"]})
        time.sleep(1.0)
    per_video = sum(timings) / len(timings) if timings else None
    return {
        "listing_error": listing.get("_error"),
        "listed": len(entries),
        "listing_seconds": round(listing_seconds, 1),
        "sampled": len(picked),
        "seconds_per_full_lookup": round(per_video, 2) if per_video else None,
        "estimated_full_index_seconds": round(listing_seconds + per_video * len(entries) + len(entries), 0) if per_video else None,
        "lookup_errors": errors,
        "ids": [entry["id"] for entry in entries],
    }


def api_full_index(playlist_id: str) -> dict:
    before = units
    ids, list_seconds, pages = uploads_ids(playlist_id)
    found, detail_seconds = details(ids)
    return {
        "listed": len(ids), "pages": pages, "detailed": len(found),
        "missing_from_videos_list": [video for video in ids if video not in found][:20],
        "seconds": round(list_seconds + detail_seconds, 1), "units": units - before, "ids": ids,
    }


def rss(channel_id: str) -> dict:
    started = time.monotonic()
    try:
        response = requests.get(f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}", timeout=30)
        entries = len(ET.fromstring(response.content).findall("{http://www.w3.org/2005/Atom}entry")) if response.ok else 0
        return {"status": response.status_code, "entries": entries, "seconds": round(time.monotonic() - started, 2)}
    except Exception as exc:
        return {"error": str(exc)[:200], "seconds": round(time.monotonic() - started, 2)}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fixtures").mkdir(exist_ok=True)
    results: dict = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "ytdlp_version": runner.version()}

    # 1. A big channel, both ways.
    big = channel(BIG_CHANNEL)
    uploads = big["contentDetails"]["relatedPlaylists"]["uploads"]
    print("Big channel:", big["snippet"]["title"], big["statistics"].get("videoCount"), flush=True)
    api_big = api_full_index(uploads)
    ytdlp_big = ytdlp_listing_and_sample(f"https://www.youtube.com/{BIG_CHANNEL}/videos", FULL_SAMPLE)
    api_ids, ytdlp_ids = set(api_big.pop("ids")), set(ytdlp_big.pop("ids"))
    results["big_channel"] = {
        "handle": BIG_CHANNEL, "video_count": big["statistics"].get("videoCount"), "api": api_big, "ytdlp_videos_tab": ytdlp_big,
        # The Videos tab leaves out Shorts and livestreams; the uploads playlist has everything.
        "only_in_api_uploads": len(api_ids - ytdlp_ids), "only_in_ytdlp_videos_tab": sorted(ytdlp_ids - api_ids)[:20],
    }

    # 2. A playlist of about 200 videos from the same channel.
    global units
    units += 1
    page = api._get(
        "playlists", {"part": "snippet,contentDetails", "channelId": big["id"], "maxResults": 50}, share=Share.RESERVE,
    ).get("items") or []
    playlist = min(page, key=lambda item: abs(item["contentDetails"]["itemCount"] - 200)) if page else None
    if playlist:
        print("Playlist:", playlist["snippet"]["title"], playlist["contentDetails"]["itemCount"], flush=True)
        api_playlist = api_full_index(playlist["id"])
        api_playlist.pop("ids")
        ytdlp_playlist = ytdlp_listing_and_sample(f"https://www.youtube.com/playlist?list={playlist['id']}", PLAYLIST_SAMPLE)
        ytdlp_playlist.pop("ids")
        results["playlist"] = {
            "id": playlist["id"], "title": playlist["snippet"]["title"], "item_count": playlist["contentDetails"]["itemCount"],
            "api": api_playlist, "ytdlp": ytdlp_playlist,
        }

    # 3. "Anything new?" for 20 channels: RSS, the API's first page, and a flat yt-dlp listing of the newest 15.
    quick = []
    for handle in QUICK_CHECK_CHANNELS:
        try:
            item = channel(handle)
        except Exception as exc:
            quick.append({"handle": handle, "error": str(exc)[:200]})
            continue
        started = time.monotonic()
        call("playlist_items", item["contentDetails"]["relatedPlaylists"]["uploads"])
        api_seconds = time.monotonic() - started
        _, flat_seconds = ytdlp("--flat-playlist", "--playlist-items", "1:15", f"https://www.youtube.com/{handle}/videos")
        quick.append({
            "handle": handle, "api_seconds": round(api_seconds, 2), "ytdlp_flat_seconds": round(flat_seconds, 1),
            "rss": [rss(item["id"]) for _ in range(3)],
        })
    results["quick_check"] = {
        "channels": quick,
        "total_api_seconds": round(sum(q.get("api_seconds", 0) for q in quick), 1),
        "total_ytdlp_flat_seconds": round(sum(q.get("ytdlp_flat_seconds", 0) for q in quick), 1),
        "rss_ok": sum(1 for q in quick for r in q.get("rss", []) if r.get("status") == 200),
        "rss_tries": sum(len(q.get("rss", [])) for q in quick),
    }
    print("Quick check done", flush=True)

    # 4. The UULF / UUSH / UULV playlists, and fixtures from them.
    tag_playlists, fixture_ids = {}, []
    for handle in TAG_CHANNELS:
        item = channel(handle)
        rest = item["id"][2:]
        for prefix in ("UULF", "UUSH", "UULV"):
            try:
                page = call("playlist_items", prefix + rest)
                ids = [i["contentDetails"]["videoId"] for i in page.get("items") or []]
                tag_playlists[f"{handle} {prefix}"] = {"items": len(ids), "total": page.get("pageInfo", {}).get("totalResults")}
                fixture_ids += [(prefix, video) for video in ids[:PER_PLAYLIST_FIXTURES]]
            except Exception as exc:
                tag_playlists[f"{handle} {prefix}"] = {"error": str(exc)[:200]}
    results["tag_playlists"] = tag_playlists

    api_items, _ = details([video for _, video in fixture_ids])
    disagreements = []
    for prefix, video in fixture_ids:
        info, _ = ytdlp("--no-playlist", f"https://www.youtube.com/watch?v={video}", timeout=180)
        time.sleep(1.0)
        fixture = {"playlist": prefix, "ytdlp": trimmed(info) if "_error" not in info else info, "api": api_items.get(video)}
        (OUT / "fixtures" / f"{video}.json").write_text(json.dumps(fixture, indent=1, ensure_ascii=False))
        api_item = api_items.get(video) or {}
        disagreements.append({
            "id": video, "playlist": prefix,
            "ytdlp_media_type": info.get("media_type"), "ytdlp_live_status": info.get("live_status"),
            "ytdlp_timestamp": info.get("timestamp"), "ytdlp_release_timestamp": info.get("release_timestamp"),
            "api_published_at": (api_item.get("snippet") or {}).get("publishedAt"),
            "api_live": bool(api_item.get("liveStreamingDetails")),
            "api_live_broadcast_content": (api_item.get("snippet") or {}).get("liveBroadcastContent"),
            "ytdlp_duration": info.get("duration"), "api_duration": (api_item.get("contentDetails") or {}).get("duration"),
            "ytdlp_error": info.get("_error"),
        })
    results["fixtures"] = disagreements
    results["api_units"] = units
    results["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    (OUT / "results.json").write_text(json.dumps(results, indent=1, ensure_ascii=False))
    print("Wrote", OUT, "using", units, "API units", flush=True)


if __name__ == "__main__":
    main()
