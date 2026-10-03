# Library and discovery

VodLoft supports **Videos**, **Movies**, **Movie Extras**, and **Collections**. Shows, channels, playlists, and seasons are represented as Collections or grouped Collection membership. The same canonical item may appear in several Collections without creating separate media files.

**Discover** accepts public URLs and offers search for Sources that advertise it. Search and URL resolution are previews; import happens only when you choose it. **Library** provides text filtering, item details, references, available formats, Source snapshots, local files, playback, and Collection policies.

Choose a Source/account reference explicitly when an item has several. Refreshing details updates upstream information while preserving your title, description, and classification edits. Source history lets you restore an earlier upstream snapshot without erasing those edits.

A Movie's Extras are strong parent relationships rather than ordinary playlist entries. A shared extra can belong to multiple Movies. Its upstream role may differ by Movie; editing the parent list or extra type preserves your choices during subsequent refreshes.

Refresh Collections to discover members. A failed or partial scan keeps previously known entries and exposes its incomplete checkpoint. Nested Collections expand explicitly with depth/count limits and cycle detection.

The browser player can use a local file or an upstream session. It supports queues, resume, playback speed, chapter navigation, and available subtitle tracks. An upstream session keeps its chosen delivery and Source runtime if a local download finishes while it is playing.

Removing a Collection removes its policies and membership, while preserving canonical items and files still required elsewhere. See [Downloads and file integrity](Downloads-and-File-Integrity.md) before removing local media.
