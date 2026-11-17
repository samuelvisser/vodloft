import {createSelectRegistry} from "../utils/selectRegistry";

export const MediaTypeReg = createSelectRegistry("PreferredFormat", {
  'format_1080p': {label: "Video", help: "Stream video"},
  'format_audio_only': {label: "Audio Only", help: "Stream audio only"},
});

export const RssVideoOutputModeReg = createSelectRegistry("RssVideoOutputMode", {
  'audio_hls': {
    label: "HLS video stream with audio fallback (recommended)",
    help: "Stream video directly using a stream- friendly protocol serving multiple quality levels depending on the connection speed. Provides an audio fallback for compatibility.",
  },
  'audio_mp4': {
    label: "Serve as mp4 with audio fallback",
    help: "Stream as mp4 downloaded by VODLoft. Requires the mp4 to be downloaded by VODLoft before it can start streaming. Provides an audio fallback for compatibility.",
  },
  'mp4': {
    label: "Serve mp4 video only",
    help: "Normal mp4 enclosure without audio fallback. Not recommended if 'Use The Daily Wire stream' is enabled.",
  },
  'mp4_hls': {
    label: "HLS video stream with mp4 fallback",
    help: "Streams video using HLS, and provides mp4 as the fallback. This ensures the podcasting app will always play video if it supports video at all. Might be unexpectedly slow however because mp4 videos still need to be pre- downloaded by VODLoft.",
  },
});

export const RssHlsOutputModes = new Set(['audio_hls', 'mp4_hls'])
export const RssMp4OutputModes = new Set(['audio_mp4', 'mp4', 'mp4_hls'])

export const IptvBetweenLiveEpisodesReg = createSelectRegistry("IptvBetweenLiveEpisodes", {
  'newest_episode': {
    label: "Newest episode",
    help: "plays the newest episode the channel aired, on a loop, until the next one starts.",
  },
  'off_air': {
    label: "Off air",
    help: "shows an off-air screen until the next episode starts.",
  },
  'hide_channel': {
    label: "Hide channel",
    help: "lists the channel only while one of its episodes is live. Your TV app may only notice when it next reloads the playlist.",
  },
});

export const WebdavSeasonFoldersReg = createSelectRegistry("WebdavSeasonFolders", {
  'season': {label: "One per season", help: "puts each season's episodes in a Season 01 folder, and names them S01E05."},
  'year': {label: "One per year", help: "puts each year's episodes in a Season 2026 folder, and names them by date."},
  'none': {label: "All in one folder", help: "puts every episode in the show's folder, named by date."},
});

export const WebdavMetadataFilesReg = createSelectRegistry("WebdavMetadataFiles", {
  'nfo_and_artwork': {label: "NFO files and artwork", help: "lists tvshow.nfo, season.nfo and an NFO file per episode, with the show's poster and each episode's picture."},
  'artwork': {label: "Artwork only", help: "lists the show's poster and each episode's picture, for players that look up the rest themselves."},
  'none': {label: "Media files only", help: "lists only the episodes."},
});
