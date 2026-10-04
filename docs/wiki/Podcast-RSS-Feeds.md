# Podcast and video RSS feeds

Attach a **Collection Stream Profile** to a Collection. Choose audio or video, maximum items, optional feed title, Source/account reference, Local Media Profiles, refresh interval, and the same date/title/group/role filters used for collection acquisition.

For portable enclosures, audio feeds publish MP3/M4A and video feeds publish MP4. Select **local files only** to publish existing compatible files. Otherwise VodLoft prepares missing portable renditions through its normal acquisition queue. Rendition fallback is an explicit choice.

Choose **Get feed** and copy the URL into your podcast app. Each local user's subscription has its own unguessable token. Treat the URL as a credential. **Rotate URL** revokes the previous URL; **Revoke my feed** removes that subscription and its published copies.

Published enclosure URLs keep the same bytes, MIME type, and length even when an upstream item, profile, or canonical local file changes. They support HEAD and byte-range requests. Feed publication and local download retention are separate.

Live admission persists while an item transitions from live to archived. Local-only live admission needs a compatible enabled Download Profile. RSS itself publishes a portable local archive when it is available; browser playback may use the upstream lease meanwhile.

Audiobookshelf can pull the feed and own its downloaded copies. See [Media-server integrations](Media-Server-Integrations.md) for ownership and progress mapping.
