# Troubleshooting

| Symptom | Check |
| --- | --- |
| URL is rejected | It must be public HTTP/HTTPS with no embedded credentials. Choose a Source that recognizes the URL. |
| Source asks for authentication | Open its saved connection and complete the challenge/update credentials; application login is separate. |
| Source missing after update | Inspect runtime history, Python/helper compatibility, saved connection schema, channel/pin, and trusted bundle/catalogue configuration. Roll back an installed version. |
| Collection refresh stops early | Known members are preserved. Inspect the incomplete scan and retry with the same Source/account; avoid starting unbounded nested expansion. |
| Download remains failed | Inspect its failed stage/error code, attempt budget, and disk/mount. Explicit retry/resume clears intentional suppression. |
| No feed enclosure | Ensure a matching portable MP3/M4A audio or MP4 video rendition, selected profiles, filters, and feed preparation have completed. Live items need an archive. |
| Podcast URL stops working | Rotation/revocation changes authorization. Copy the user's current feed URL. |
| Server export is pending/failed | Test the connection, library ID, shared mount prefixes, and scanner/agent. Retry delivery separately from acquisition. |
| Audiobookshelf progress cannot import | Verify the granted target and explicit remote user mapping/token. Progress is not inferred from usernames. |
| Media appears missing after restart | Check the actual mount and configured download root before creating/removing files. Restore state and media together from backup. |

Use `docker compose logs vodloft` for startup errors. The initial image installs both Source runtimes before the API starts, so the first build/start can take longer. Keep configuration/media volumes when recreating it.
